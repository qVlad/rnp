/**
 * MAIN-world interceptor выдачи поиска WB (DEV-085 — конкурентное сравнение).
 *
 * Зачем: DOM-скрейпинг выдачи (`findSearchCards`) хрупкий — WB рендерит
 * виртуализированный список, `data-nm-id` появляется не всегда. Надёжнее
 * перехватить JSON-ответ поискового API напрямую.
 *
 * WB-фронт (`www.wildberries.ru`) дёргает поиск на хостах `search.wb.ru` /
 * `catalog.wb.ru` (домен `wb.ru`, НЕ wildberries.ru). Ответ:
 *   { data: { products: [{ id: <nmId>, ... }, ...] } }   (порядок = ранг)
 * URL содержит `query=<запрос>` и `page=<N>`.
 *
 * Перехватываем fetch+XHR, достаём query + упорядоченный список nmId, шлём
 * через `window.postMessage` в ISOLATED (`wb-search.ts`), который отправляет
 * на backend (`postSearchRanking`). Бэкенд пишет ранг только если в нём есть
 * наша карточка (анти-спай-гард).
 */
(() => {
  const TAG = "[rnp-ext MAIN search]";
  console.log(`${TAG} interceptor loaded on ${location.href}`);
  const PAGE_SIZE = 100; // WB отдаёт ~100 товаров на страницу выдачи

  function extractProducts(raw: unknown): unknown[] | null {
    if (raw === null || typeof raw !== "object") return null;
    const obj = raw as Record<string, unknown>;
    // {products:[...]} (новые версии) или {data:{products:[...]}}
    if (Array.isArray(obj.products)) return obj.products;
    const data = obj.data;
    if (data && typeof data === "object") {
      const p = (data as Record<string, unknown>).products;
      if (Array.isArray(p)) return p;
    }
    return null;
  }

  function parseUrlMeta(url: string): { query: string | null; page: number } {
    try {
      const u = new URL(url, location.href);
      const query =
        u.searchParams.get("query") || u.searchParams.get("search") || null;
      const pageRaw = u.searchParams.get("page");
      const page = pageRaw ? Math.max(1, Number.parseInt(pageRaw, 10) || 1) : 1;
      return { query: query ? query.trim() : null, page };
    } catch {
      return { query: null, page: 1 };
    }
  }

  /** Запрос из URL текущей страницы (search.aspx?search=… / ?query=…) — fallback,
   *  если у API-эндпоинта query в теле/не в URL. */
  function pageQuery(): string | null {
    try {
      const sp = new URL(location.href).searchParams;
      const q = sp.get("search") || sp.get("query");
      return q ? q.trim() : null;
    } catch {
      return null;
    }
  }

  const lastByQuery = new Map<string, number>();
  const candidateLogged = new Set<string>();

  function maybePost(url: string, raw: unknown): void {
    const products = extractProducts(raw);
    if (!products || products.length === 0) return;

    // Нашли products[] — это кандидат на выдачу. Диагностика (раз на URL).
    const urlKey = url.split("?")[0];
    if (!candidateLogged.has(urlKey)) {
      candidateLogged.add(urlKey);
      console.log(`${TAG} CANDIDATE products[] (${products.length}) at`, url);
    }

    // Запрос: из URL API, иначе из URL страницы (search.aspx?search=…).
    const meta = parseUrlMeta(url);
    const query = meta.query || pageQuery();
    if (!query) return; // не поиск (каталог-броузинг без запроса) — пропускаем
    const page = meta.page;

    const cards: { nmId: number; position: number }[] = [];
    let idx = 0;
    for (const p of products) {
      idx++;
      if (!p || typeof p !== "object") continue;
      const id = (p as Record<string, unknown>).id;
      const nmId = typeof id === "number" ? id : Number(id);
      if (!Number.isFinite(nmId) || nmId <= 0) continue;
      cards.push({ nmId, position: (page - 1) * PAGE_SIZE + idx });
    }
    if (cards.length === 0) return;

    // Дедуп: не чаще раза в 3 сек на один и тот же запрос (WB дёргает поиск
    // несколько раз при скролле/фильтрах).
    const now = Date.now();
    const key = `${query}|${page}`;
    if (now - (lastByQuery.get(key) || 0) < 3000) return;
    lastByQuery.set(key, now);

    console.log(`${TAG} search ranking: q=%o page=%o cards=%o`, query, page, cards.length);
    window.postMessage(
      { __rnp: "wb-search-ranking", query, page, cards },
      "*",
    );
  }

  function shouldInspect(url: string): boolean {
    // Любой wb.ru-хост (search/catalog/u-search/… — точный неизвестен, WB меняет).
    return /\bwb\.ru\b/i.test(url) || /\/exactmatch\//i.test(url);
  }

  // ---- Диагностика: ловит ли WB поиск через Web Worker (тогда window.fetch
  //      в MAIN не видит запрос). Логируем создание воркеров.
  try {
    const OrigWorker = window.Worker;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    window.Worker = function (this: unknown, ...args: any[]) {
      try {
        console.log(`${TAG} Worker created:`, String(args[0]).slice(0, 80));
      } catch {
        /* noop */
      }
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      return new (OrigWorker as any)(...args);
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any;
    window.Worker.prototype = OrigWorker.prototype;
  } catch {
    /* never break */
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
        resp
          .clone()
          .text()
          .then((text) => {
            const trimmed = (text || "").trim();
            if (!trimmed.startsWith("{")) return;
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
  const origSend = OrigXHR.prototype.send;
  OrigXHR.prototype.send = function (this: XHRWithMeta) {
    try {
      this.addEventListener("load", () => {
        try {
          const url = this.__rnpUrl || "";
          if (!url || !shouldInspect(url)) return;
          const text = this.responseText;
          const trimmed = (text || "").trim();
          if (!trimmed.startsWith("{")) return;
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

  console.log(`${TAG} fetch+XHR search interceptor installed`);
})();
