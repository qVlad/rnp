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

  /** Детект сводки отчёта реализации `/reports-weekly/{id}` (без /details).
   *  Shape: `{data: {totalSale, forPay, deliveryRub, dateFrom, dateTo, ...}}`.
   *  Это ГОТОВЫЕ итоги недели — единый fetch, без пагинации. Предпочтительнее
   *  detail-строк (которые ЛК отдаёт по 15 на страницу). */
  function looksLikeReportSummary(
    raw: unknown,
  ): Record<string, unknown> | null {
    if (raw === null || typeof raw !== "object") return null;
    const obj = raw as Record<string, unknown>;
    const data = (obj.data ?? obj) as Record<string, unknown>;
    if (!data || typeof data !== "object") return null;
    // Характерные поля сводки: forPay + deliveryRub + dateFrom/dateTo.
    const hasForPay = "forPay" in data;
    const hasDelivery = "deliveryRub" in data;
    const hasDates = "dateFrom" in data && "dateTo" in data;
    if (hasForPay && hasDelivery && hasDates) {
      return data;
    }
    return null;
  }

  function summaryHash(s: Record<string, unknown>): string {
    const str = JSON.stringify({
      f: s.forPay,
      d: s.deliveryRub,
      df: s.dateFrom,
      dt: s.dateTo,
      id: s.id,
    });
    let h = 0x811c9dc5;
    for (let i = 0; i < str.length; i++) {
      h ^= str.charCodeAt(i);
      h = (h + ((h << 1) + (h << 4) + (h << 7) + (h << 8) + (h << 24))) >>> 0;
    }
    return `sum-h${h.toString(16)}`;
  }

  // TASK-LEAD-141: реклама (Продвижение → Финансы) и воронка.
  let lastAdvHash = "";
  let lastFunnelHash = "";

  function maybePostExtra(url: string, raw: unknown): boolean {
    if (raw === null || typeof raw !== "object") return false;
    const obj = raw as Record<string, any>;

    // 1. Реклама: cmp.wildberries.ru/api/v6/upd → {upd_total_amount, upd_info}.
    if ("upd_total_amount" in obj && Array.isArray(obj.upd_info)) {
      const total = Number(obj.upd_total_amount);
      // Период — из URL ?from=2026-05-18T... . Backend снапит к понедельнику.
      const fromMatch = url.match(/[?&]from=([^&]+)/);
      const fromDate = fromMatch
        ? decodeURIComponent(fromMatch[1]).slice(0, 10)
        : null;
      if (!fromDate || !Number.isFinite(total)) return true;
      const hash = `adv-${fromDate}-${total}`;
      if (hash === lastAdvHash) return true;
      lastAdvHash = hash;
      console.log(`${TAG} matched ADV finance: ${total}₽ from ${fromDate}`, url);
      window.postMessage(
        { __rnp: "wb-adv-finance", week_start: fromDate, ad_cost: total },
        "*",
      );
      return true;
    }

    // 2. Воронка: .../sales-funnel/report → data.chart.byWeek[0].
    const byWeek = obj?.data?.chart?.byWeek;
    if (Array.isArray(byWeek) && byWeek.length > 0 && byWeek[0] &&
        typeof byWeek[0] === "object" && "orderCount" in byWeek[0]) {
      const w = byWeek[0] as Record<string, any>;
      const weekStart = typeof w.date === "string" ? w.date.slice(0, 10) : null;
      const orderCount = Number(w.orderCount);
      const orderSum = Number(w.orderSum);
      if (!weekStart) return true;
      const hash = `funnel-${weekStart}-${orderCount}-${orderSum}`;
      if (hash === lastFunnelHash) return true;
      lastFunnelHash = hash;
      console.log(
        `${TAG} matched FUNNEL: ${orderCount} заказов / ${orderSum}₽ week ${weekStart}`,
        url,
      );
      window.postMessage(
        {
          __rnp: "wb-funnel",
          week_start: weekStart,
          orders_count: Number.isFinite(orderCount) ? orderCount : null,
          orders_sum: Number.isFinite(orderSum) ? orderSum : null,
        },
        "*",
      );
      return true;
    }
    return false;
  }

  function maybePost(url: string, raw: unknown): void {
    // 0. Реклама/воронка (TASK-LEAD-141) — отдельные страницы ЛК.
    if (maybePostExtra(url, raw)) return;
    // 1. Приоритет — сводка (единый fetch с итогами).
    const summary = looksLikeReportSummary(raw);
    if (summary) {
      const hash = summaryHash(summary);
      if (hash === lastPostedHash) return;
      lastPostedHash = hash;
      console.log(`${TAG} matched report SUMMARY from`, url, summary);
      window.postMessage(
        { __rnp: "wb-realization-report", url, summary, hash },
        "*",
      );
      return;
    }
    // 2. Fallback — массив detail-строк (если ЛK когда-нибудь вернёт всё разом).
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
      { __rnp: "wb-realization-report", url, rows: arr, hash },
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
