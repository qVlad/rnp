/**
 * MAIN-world скрипт: интерсептор fetch+XHR на seller.wildberries.ru.
 *
 * Зачем отдельный файл и MAIN world: страница seller.wildberries.ru
 * накатывает CSP `script-src` без `unsafe-inline`, поэтому динамическая
 * инъекция <script> с textContent блокируется. Файл-ресурс
 * `chrome-extension://...` исполняется как обычный ресурс и CSP его
 * пропускает (он whitelisted в src-elem default-src по правилам
 * расширения).
 *
 * MV3 manifest_v3 поддерживает `"world": "MAIN"` в content_scripts с
 * Chrome 111+ — этот файл регистрируется именно так в manifest.config.ts.
 *
 * Передача наружу (в ISOLATED world) — через window.postMessage.
 * Получатель: src/content/wb-shifts-content.ts.
 */

(() => {
  const TAG = "[rnp-ext MAIN]";

  /** Извлечь все headers из fetch init или Request. Ключи в lowercase. */
  function extractHeaders(
    input: RequestInfo | URL,
    init?: RequestInit,
  ): Record<string, string> {
    const out: Record<string, string> = {};
    if (init?.headers) {
      const h = init.headers;
      if (h instanceof Headers) {
        h.forEach((v, k) => {
          out[k.toLowerCase()] = v;
        });
      } else if (Array.isArray(h)) {
        for (const [k, v] of h) out[k.toLowerCase()] = v;
      } else {
        for (const k of Object.keys(h as Record<string, string>)) {
          out[k.toLowerCase()] = (h as Record<string, string>)[k];
        }
      }
    }
    if (input instanceof Request) {
      input.headers.forEach((v, k) => {
        if (!out[k.toLowerCase()]) out[k.toLowerCase()] = v;
      });
    }
    return out;
  }

  function isWbApiUrl(u: string): boolean {
    return (
      u.includes("seller-weekly-report.wildberries.ru") ||
      u.includes("seller.wildberries.ru/ns/")
    );
  }

  function maybePost(url: string, headers: Record<string, string>): void {
    if (!isWbApiUrl(url)) return;
    if (!headers["authorizev3"] && !headers["wb-seller-lk"]) return;
    window.postMessage({ __rnp: "wb-headers", url, headers }, "*");
  }

  // fetch
  const origFetch = window.fetch.bind(window);
  window.fetch = function (input, init) {
    try {
      const url =
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.toString()
            : input instanceof Request
              ? input.url
              : String(input);
      maybePost(url, extractHeaders(input, init));
    } catch {
      /* never break the page */
    }
    return origFetch(input as RequestInfo, init);
  };

  // XHR
  type XHRWithMeta = XMLHttpRequest & {
    __rnpUrl?: string;
    __rnpHeaders?: Record<string, string>;
  };
  const OrigXHR = window.XMLHttpRequest;
  const origOpen = OrigXHR.prototype.open;
  const origSetRH = OrigXHR.prototype.setRequestHeader;
  const origSend = OrigXHR.prototype.send;
  OrigXHR.prototype.open = function (
    this: XHRWithMeta,
    _method: string,
    url: string | URL,
    ..._rest: unknown[]
  ) {
    this.__rnpUrl = typeof url === "string" ? url : url.toString();
    this.__rnpHeaders = {};
    // eslint-disable-next-line prefer-rest-params, @typescript-eslint/no-explicit-any
    return origOpen.apply(this, arguments as any);
  };
  OrigXHR.prototype.setRequestHeader = function (
    this: XHRWithMeta,
    k: string,
    v: string,
  ) {
    if (this.__rnpHeaders) this.__rnpHeaders[k.toLowerCase()] = v;
    // eslint-disable-next-line prefer-rest-params, @typescript-eslint/no-explicit-any
    return origSetRH.apply(this, arguments as any);
  };
  OrigXHR.prototype.send = function (this: XHRWithMeta) {
    try {
      const u = this.__rnpUrl || "";
      if (u && this.__rnpHeaders) maybePost(u, this.__rnpHeaders);
    } catch {
      /* never break */
    }
    // eslint-disable-next-line prefer-rest-params, @typescript-eslint/no-explicit-any
    return origSend.apply(this, arguments as any);
  };

  console.log(TAG, "fetch+XHR interceptor installed");
})();
