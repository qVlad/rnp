/**
 * MAIN-world interceptor для тарифов транзитных направлений (TASK-LEAD-078).
 *
 * Зачем: WB Tariffs API публично не отдаёт тарифы транзита. Они доступны
 * только в ЛК `seller.wildberries.ru` на странице «Поставки и заказы →
 * Поставки (FBW) → Транзитные направления». Расширение перехватывает
 * internal-fetch'и WB-фронта, разбирает response body и шлёт через
 * `window.postMessage` в ISOLATED world (`wb-transit-tariffs-content.ts`).
 *
 * Почему MAIN world: страница seller.wildberries.ru имеет CSP без
 * `unsafe-inline`. Файл-ресурс расширения исполняется как обычный script
 * с world:MAIN (Chrome 111+, MV3) — CSP его пропускает.
 *
 * Гибкая стратегия: точный URL endpoint'а ЛК для транзитных тарифов на
 * 2026-05 не задокументирован. Поэтому мы НЕ фильтруем по URL — слушаем
 * все fetch/XHR на `*.wildberries.ru` и определяем «похоже на тариф
 * транзита» по shape данных (см. `looksLikeTransitTariffs` ниже).
 *
 * Если структура поменяется — правится одна функция.
 */
(() => {
  const TAG = "[rnp-ext MAIN transit]";
  console.log(`${TAG} interceptor loaded on ${location.href}`);

  /** Snake_case + camelCase + kebab-case lookup. */
  function pick<T = unknown>(
    obj: Record<string, unknown>,
    keys: string[],
  ): T | undefined {
    for (const k of keys) {
      const variants = [
        k,
        k.toLowerCase(),
        k.replace(/_/g, ""),
        k.replace(/_([a-z])/g, (_, c) => c.toUpperCase()), // snake → camel
        k.replace(/([A-Z])/g, "_$1").toLowerCase(), // camel → snake
      ];
      for (const v of variants) {
        if (v in obj && obj[v] !== null && obj[v] !== undefined) {
          return obj[v] as T;
        }
      }
    }
    return undefined;
  }

  /** Достать массив строк из произвольного response-объекта.
   *  WB любит оборачивать в `{data: [...]}`, `{items: [...]}`,
   *  `{result: {items: [...]}}` etc. */
  function unwrapArray(raw: unknown): unknown[] | null {
    if (Array.isArray(raw)) return raw;
    if (raw === null || typeof raw !== "object") return null;
    const obj = raw as Record<string, unknown>;
    for (const key of ["data", "items", "routes", "directions", "tariffs", "result", "rows"]) {
      const v = obj[key];
      if (Array.isArray(v)) return v;
      if (v && typeof v === "object") {
        const inner = unwrapArray(v);
        if (inner) return inner;
      }
    }
    return null;
  }

  type TransitRow = {
    hub_name: string;
    destination_warehouse: string;
    rate_small: number | null;
    rate_large: number | null;
    threshold_l: number | null;
  };

  const toNum = (v: unknown): number | null => {
    if (v === null || v === undefined) return null;
    const n = typeof v === "number" ? v : Number(v);
    return Number.isFinite(n) && n >= 0 ? n : null;
  };

  /** Двухступенчатый тариф ₽/л из `tariffTable.perVolume`.
   *  Реальный shape WB (transitTariffsV2, 2026-06):
   *    perVolume = [{from:0,to:1500,value:5.8},{from:1500,to:0,value:4.1}]
   *  где `to:0` у верхней ступени = «до бесконечности», порог = `to` нижней. */
  function parseVolumeTiers(o: Record<string, unknown>): {
    small: number | null;
    large: number | null;
    threshold: number | null;
  } | null {
    const tt = o["tariffTable"];
    if (!tt || typeof tt !== "object") return null;
    const pv = (tt as Record<string, unknown>)["perVolume"];
    if (!Array.isArray(pv) || pv.length === 0) return null;
    const tiers = pv
      .map((t) => {
        const r = (t || {}) as Record<string, unknown>;
        return {
          from: toNum(r["from"]),
          to: toNum(r["to"]),
          value: toNum(r["value"]),
        };
      })
      .filter((t) => t.value !== null)
      .sort((a, b) => (a.from ?? 0) - (b.from ?? 0));
    if (tiers.length === 0) return null;
    const lower = tiers[0];
    const upper = tiers.length > 1 ? tiers[tiers.length - 1] : null;
    return {
      small: lower.value,
      large: upper ? upper.value : null,
      threshold: lower.to && lower.to > 0 ? lower.to : null,
    };
  }

  /** Попытка распарсить один элемент массива в `TransitRow`. */
  function tryParseRow(item: unknown): TransitRow | null {
    if (!item || typeof item !== "object") return null;
    const o = item as Record<string, unknown>;
    const hub = pick<string>(o, [
      "transitWarehouseName", // реальный shape WB (transitTariffsV2, 2026-06)
      "warehouseFrom",
      "hubName",
      "hub",
      "sourceWarehouse",
      "transitWarehouse",
      "fromWarehouse",
      "warehouse_from",
    ]);
    const dest = pick<string>(o, [
      "destinationWarehouseName", // реальный shape WB (transitTariffsV2, 2026-06)
      "warehouseTo",
      "destinationWarehouse",
      "destination",
      "targetWarehouse",
      "finalWarehouse",
      "toWarehouse",
      "warehouse_to",
    ]);
    if (typeof hub !== "string" || typeof dest !== "string") return null;
    if (!hub.trim() || !dest.trim()) return null;

    // 1) Реальный формат WB — двухступенчатый perVolume.
    const tiers = parseVolumeTiers(o);
    let rs = tiers?.small ?? null;
    let rl = tiers?.large ?? null;
    let threshold = tiers?.threshold ?? null;

    // 2) Fallback на плоские поля (если WB вернёт другой формат).
    if (rs === null && rl === null) {
      rs = toNum(
        pick<number | string>(o, [
          "rateSmall", "priceSmall", "pricePerLiterSmall", "tariffSmall",
          "rate", "price", "pricePerLiter", "tariff", "ratePerLiter",
        ]),
      );
      rl = toNum(
        pick<number | string>(o, [
          "rateLarge", "priceLarge", "pricePerLiterLarge", "tariffLarge",
          "rateBig", "priceBig",
        ]),
      );
    }
    if (threshold === null) {
      threshold = toNum(
        pick<number | string>(o, [
          "thresholdL", "threshold", "volumeThreshold", "thresholdLiters", "tierThreshold",
        ]),
      );
    }

    // Нет per-liter тарифа (паллетные/СГТ маршруты: perVolume пустой,
    // только плоский currentTariff) — пропускаем, наша модель per-liter.
    if (rs === null && rl === null) return null;
    return {
      hub_name: hub.trim(),
      destination_warehouse: dest.trim(),
      rate_small: rs,
      rate_large: rl,
      threshold_l: threshold ?? 1500,
    };
  }

  function looksLikeTransitTariffs(raw: unknown): TransitRow[] | null {
    const arr = unwrapArray(raw);
    if (!arr || arr.length === 0) return null;
    const rows: TransitRow[] = [];
    for (const item of arr) {
      const row = tryParseRow(item);
      if (row) rows.push(row);
    }
    // Хотим увидеть хотя бы 2 строки чтобы считать что это таблица
    // транзитных тарифов (одна строка может прилететь случайно от
    // другого ЛК endpoint'а где случайно совпали поля).
    if (rows.length < 2) return null;
    return rows;
  }

  let postedCount = 0;
  let lastPostedAt = 0;
  const debuggedUrls = new Set<string>();
  function maybePost(url: string, raw: unknown): void {
    const rows = looksLikeTransitTariffs(raw);
    if (!rows) {
      // Near-miss диагностика: URL похож на транзитный (transit/tariff), но
      // распарсить не вышло → логируем ключи первого элемента (раз на URL).
      // Помогает быстро поймать смену shape WB в будущем.
      if (/transit|tariff/i.test(url) && !debuggedUrls.has(url)) {
        debuggedUrls.add(url);
        const arr = unwrapArray(raw);
        const sample =
          Array.isArray(arr) && arr[0] && typeof arr[0] === "object"
            ? Object.keys(arr[0] as Record<string, unknown>)
            : null;
        console.warn(
          `${TAG} transit-like URL, но parse не дал строк:`,
          url,
          "| ключи 1-го элемента:",
          sample,
        );
      }
      return;
    }
    // Дедуп по timing — не чаще раз в 2 сек на тот же URL.
    const now = Date.now();
    if (now - lastPostedAt < 2000) return;
    lastPostedAt = now;
    postedCount++;
    if (postedCount <= 3) {
      console.log(`${TAG} matched transit tariffs (${rows.length} rows) from`, url);
    }
    window.postMessage(
      { __rnp: "wb-transit-tariffs", url, rows },
      "*",
    );
  }

  /** Проверка: стоит ли вообще пытаться парсить ответ. */
  function shouldInspect(url: string): boolean {
    // Любой WB-хост. Не сужаем — точный endpoint неизвестен.
    return /\.wildberries\.ru\b/i.test(url);
  }

  // ---- fetch interceptor ----
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
        // Клонируем — иначе если страница уже читает body, второй .text()
        // упадёт. Не блокирующее: разбираем async, не задерживаем основной
        // flow страницы.
        const clone = resp.clone();
        // fire-and-forget
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

  // ---- XHR interceptor ----
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
  // load event — после полного получения ответа
  const origAddEventListener = OrigXHR.prototype.addEventListener;
  // Hook через прокси — но проще установить общий listener в send():
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
  void origAddEventListener;

  console.log(`${TAG} fetch+XHR transit interceptor installed`);
})();
