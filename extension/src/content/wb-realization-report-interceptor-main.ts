/**
 * MAIN-world interceptor для финотчёта WB (TASK-LEAD-138).
 *
 * Зачем: пользователь открывает в ЛК WB страницу «Финансы → Отчёт реализации»,
 * WB-фронт делает internal fetch'и, которые возвращают массив строк отчёта
 * (формат идентичен `/api/finance/v1/sales-reports/detailed`). Мы перехватываем
 * ответ, смотрим что это «похоже на финотчёт» по shape, шлём через postMessage
 * в ISOLATED world (`wb-realization-report-content.ts`).
 *
 * Backend `POST /api/reconciliation-auto/upload-extension` принимает сырые
 * camelCase-строки, нормализует и считает 17 метрик TS — записывает в БД
 * (`extension_recon_uploads`). UI `/reconciliation-auto` подхватывает.
 *
 * Точный URL endpoint'а WB-фронта не задокументирован — детектим shape:
 *   - массив объектов
 *   - >= 50 строк (финотчёт обычно сотни-тысячи)
 *   - в первой строке есть rrdId / rrDate / realizationreportId / supplierOperName
 */
(() => {
  const TAG = "[rnp-ext MAIN recon]";
  console.log(`${TAG} interceptor loaded on ${location.href}`);

  function unwrapArray(raw: unknown): unknown[] | null {
    if (Array.isArray(raw)) return raw;
    if (raw === null || typeof raw !== "object") return null;
    const obj = raw as Record<string, unknown>;
    for (const key of ["data", "items", "result", "rows", "report", "details"]) {
      const v = obj[key];
      if (Array.isArray(v)) return v;
      if (v && typeof v === "object") {
        const inner = unwrapArray(v);
        if (inner) return inner;
      }
    }
    return null;
  }

  function looksLikeRealizationReport(raw: unknown): unknown[] | null {
    const arr = unwrapArray(raw);
    if (!arr || arr.length < 50) return null; // не финотчёт — слишком мало строк

    // Достаточно проверить первые 5 строк: если у них есть характерные поля
    // финотчёта — это он.
    const probe = arr.slice(0, 5);
    const finReportFieldVariants = [
      "rrdId",
      "rrd_id",
      "realizationreportId",
      "realization_report_id",
      "reportId",
      "supplierOperName",
      "supplier_oper_name",
      "sellerOperName",
    ];
    let matches = 0;
    for (const item of probe) {
      if (item && typeof item === "object") {
        const o = item as Record<string, unknown>;
        const hasAny = finReportFieldVariants.some((k) => k in o);
        if (hasAny) matches++;
      }
    }
    // Хотим хотя бы 4 из 5 строк с финотчётными полями.
    return matches >= 4 ? arr : null;
  }

  let lastPostedHash = "";
  function quickHash(arr: unknown[]): string {
    // Хэш по первой+последней строке + длине — достаточно для дедупа.
    const first = arr[0];
    const last = arr[arr.length - 1];
    const s = JSON.stringify({ n: arr.length, first, last });
    let h = 0x811c9dc5;
    for (let i = 0; i < s.length; i++) {
      h ^= s.charCodeAt(i);
      h = (h + ((h << 1) + (h << 4) + (h << 7) + (h << 8) + (h << 24))) >>> 0;
    }
    return `n${arr.length}-h${h.toString(16)}`;
  }

  function maybePost(url: string, raw: unknown): void {
    const arr = looksLikeRealizationReport(raw);
    if (!arr) return;
    const hash = quickHash(arr);
    if (hash === lastPostedHash) return;
    lastPostedHash = hash;
    console.log(
      `${TAG} matched realization report (${arr.length} rows) from`,
      url,
    );
    window.postMessage(
      {
        __rnp: "wb-realization-report",
        url,
        rows: arr,
        hash,
      },
      "*",
    );
  }

  function shouldInspect(url: string): boolean {
    return /\.wildberries\.ru\b/i.test(url);
  }

  // fetch interceptor
  const origFetch = window.fetch.bind(window);
  window.fetch = async function (input, init) {
    let url = "";
    try {
      url =
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.toString()
            : input instanceof Request
              ? input.url
              : String(input);
    } catch {
      /* ignore */
    }
    const resp = await origFetch(input as RequestInfo, init);
    try {
      if (url && shouldInspect(url)) {
        const clone = resp.clone();
        clone
          .text()
          .then((text) => {
            if (!text) return;
            const trimmed = text.trim();
            if (!trimmed.startsWith("{") && !trimmed.startsWith("[")) return;
            let parsed: unknown;
            try {
              parsed = JSON.parse(trimmed);
            } catch {
              return;
            }
            maybePost(url, parsed);
          })
          .catch(() => undefined);
      }
    } catch {
      /* never break the page */
    }
    return resp;
  };

  // XHR interceptor
  type XHRWithMeta = XMLHttpRequest & { __rnpUrl?: string };
  const OrigXHR = window.XMLHttpRequest;
  const origOpen = OrigXHR.prototype.open;
  OrigXHR.prototype.open = function (
    this: XHRWithMeta,
    _method: string,
    url: string | URL,
    ..._rest: unknown[]
  ) {
    this.__rnpUrl = typeof url === "string" ? url : url.toString();
    // eslint-disable-next-line prefer-rest-params, @typescript-eslint/no-explicit-any
    return origOpen.apply(this, arguments as any);
  };
  const origSend = OrigXHR.prototype.send;
  OrigXHR.prototype.send = function (this: XHRWithMeta) {
    try {
      this.addEventListener("load", () => {
        try {
          const url = this.__rnpUrl || "";
          if (!url || !shouldInspect(url)) return;
          const text = this.responseText;
          if (!text) return;
          const trimmed = text.trim();
          if (!trimmed.startsWith("{") && !trimmed.startsWith("[")) return;
          let parsed: unknown;
          try {
            parsed = JSON.parse(trimmed);
          } catch {
            return;
          }
          maybePost(url, parsed);
        } catch {
          /* swallow */
        }
      });
    } catch {
      /* never break */
    }
    // eslint-disable-next-line prefer-rest-params, @typescript-eslint/no-explicit-any
    return origSend.apply(this, arguments as any);
  };

  console.log(`${TAG} fetch+XHR realization-report interceptor installed`);
})();
