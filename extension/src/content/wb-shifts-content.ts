/**
 * Content script на seller.wildberries.ru — proxy для shifts API.
 *
 * Зачем: fetch из service worker'а к `seller-weekly-report.wildberries.ru` с
 * credentials:'include' **не** прикрепляет куки (origin = chrome-extension://,
 * Chrome не шлёт cross-origin cookies третьей стороны). И `Cookie` header в
 * JS нельзя выставить (forbidden header).
 *
 * Решение: запросы делаются ИЗ контекста страницы seller.wildberries.ru.
 * Origin страницы = seller.wildberries.ru → same-site CORS к
 * seller-weekly-report.wildberries.ru → куки + JWT-токены из localStorage
 * (если WB их там хранит) прикрепляются как в обычном браузерном XHR.
 *
 * JWT-токены (AuthorizeV3, Wb-Seller-Lk) у WB **не** в localStorage и **не**
 * в DOM-видимых cookies — они в коде WB-фронта, который сам их выдаёт в
 * headers через свой fetch wrapper. Поэтому мы делаем **fetch interceptor
 * в MAIN world**: перехватываем все исходящие fetch/XHR от WB-фронта,
 * вытаскиваем AuthorizeV3 и Wb-Seller-Lk headers, кешируем для нашего proxy.
 *
 * Архитектура:
 *   1. MAIN world script (через chrome.scripting.executeScript world:'MAIN'
 *      ИЛИ через инжект <script>): подменяет window.fetch/XHR.send,
 *      шлёт перехваченные headers в ISOLATED world через window.postMessage.
 *   2. Этот файл (ISOLATED world): слушает postMessage, кеширует headers,
 *      использует их при proxy-вызовах от SW.
 */

const SHIFTS_BASE =
  "https://seller-weekly-report.wildberries.ru/ns/shifts/analytics-back/api/v1";

type ProxyMsg =
  | { type: "wbShiftsProxyContent"; op: "quota"; officeId: number; kind: "src" | "dst" }
  | { type: "wbShiftsProxyContent"; op: "stocks"; nmId: number }
  | { type: "wbShiftsProxyContent"; op: "searchNms"; pattern: string }
  | {
      type: "wbShiftsProxyContent";
      op: "createOrder";
      src: number;
      dst: number;
      nmID: number;
      count: Array<{ chrtID: number; count: number }>;
    };

type ProxyResp =
  | { ok: true; status: number; data: unknown }
  | { ok: false; status: number; reason: string; body?: string };

// Кеш перехваченных JWT-токенов. Обновляется fetch-интерсептором в MAIN world.
let cachedAuthV3: string | null = null;
let cachedWbSellerLk: string | null = null;
let cachedRootVersion: string | null = null;
let interceptCount = 0;

window.addEventListener("message", (e: MessageEvent) => {
  if (e.source !== window) return;
  if (e.data?.__rnp !== "wb-headers") return;
  const h = e.data.headers as Record<string, string>;
  if (h["authorizev3"]) cachedAuthV3 = h["authorizev3"];
  if (h["wb-seller-lk"]) cachedWbSellerLk = h["wb-seller-lk"];
  if (h["root-version"]) cachedRootVersion = h["root-version"];
  interceptCount++;
  if (interceptCount <= 3) {
    console.log("[rnp-ext content] intercepted headers from", e.data.url, {
      authV3: !!cachedAuthV3,
      wbSellerLk: !!cachedWbSellerLk,
    });
  }
});

// MAIN-world interceptor живёт в отдельном файле
// `src/content/wb-shifts-interceptor-main.ts` — он регистрируется
// в manifest.config.ts с `world: "MAIN"` чтобы обойти CSP страницы WB.
// Сюда (ISOLATED world) он шлёт перехваченные headers через postMessage.

async function doShiftsCall(
  method: "GET" | "POST",
  path: string,
  options: { params?: Record<string, string | number>; body?: unknown } = {},
): Promise<ProxyResp> {
  let url = `${SHIFTS_BASE}${path}`;
  if (options.params) {
    const qs = new URLSearchParams(
      Object.entries(options.params).map(([k, v]) => [k, String(v)]),
    ).toString();
    if (qs) url += `?${qs}`;
  }
  const headers: Record<string, string> = {
    Accept: "*/*",
    "Content-Type": "application/json",
    "Root-Version": cachedRootVersion ?? "v1.93.1",
  };
  if (cachedAuthV3) headers.AuthorizeV3 = cachedAuthV3;
  if (cachedWbSellerLk) headers["Wb-Seller-Lk"] = cachedWbSellerLk;

  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 10_000);
  let resp: Response;
  try {
    resp = await fetch(url, {
      method,
      headers,
      credentials: "include",
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
      signal: ctrl.signal,
    });
  } catch (e) {
    clearTimeout(timer);
    const msg = e instanceof Error ? e.message : String(e);
    return {
      ok: false,
      status: 0,
      reason: ctrl.signal.aborted ? "timeout (10s)" : `network error: ${msg}`,
    };
  }
  clearTimeout(timer);

  const text = await resp.text();
  if (!resp.ok) {
    return {
      ok: false,
      status: resp.status,
      reason: resp.headers.get("x-reason") || resp.statusText,
      body: text.slice(0, 500),
    };
  }
  try {
    const parsed = JSON.parse(text);
    if (parsed && typeof parsed === "object" && (parsed as { error?: boolean }).error === true) {
      return {
        ok: false,
        status: resp.status,
        reason: `WB-logical error: ${(parsed as { errorText?: string }).errorText ?? "unknown"}`,
        body: text.slice(0, 500),
      };
    }
    const data =
      parsed && typeof parsed === "object" && "data" in (parsed as object)
        ? (parsed as { data: unknown }).data
        : parsed;
    return { ok: true, status: resp.status, data };
  } catch (e) {
    return {
      ok: false,
      status: resp.status,
      reason: `JSON parse failed: ${e instanceof Error ? e.message : String(e)}`,
      body: text.slice(0, 500),
    };
  }
}

chrome.runtime.onMessage.addListener((msg: ProxyMsg, _sender, sendResponse) => {
  if (msg?.type !== "wbShiftsProxyContent") return false;
  (async () => {
    try {
      console.log("[rnp-ext content] shifts proxy op=", msg.op, {
        cachedAuthV3: !!cachedAuthV3,
        cachedWbSellerLk: !!cachedWbSellerLk,
        intercepts: interceptCount,
      });
      let result: ProxyResp;
      switch (msg.op) {
        case "quota":
          result = await doShiftsCall("GET", "/quota", {
            params: { officeID: msg.officeId, type: msg.kind },
          });
          break;
        case "stocks":
          result = await doShiftsCall("GET", "/stocks", {
            params: { nmID: msg.nmId },
          });
          break;
        case "searchNms":
          result = await doShiftsCall("GET", "/nms", {
            params: { pattern: msg.pattern },
          });
          break;
        case "createOrder":
          result = await doShiftsCall("POST", "/order", {
            body: {
              order: {
                src: msg.src,
                dst: msg.dst,
                nmID: msg.nmID,
                count: msg.count,
              },
            },
          });
          break;
      }
      console.log("[rnp-ext content] result =", result);
      sendResponse(result);
    } catch (e) {
      const errMsg = e instanceof Error ? e.message : String(e);
      console.error("[rnp-ext content] handler error:", e);
      sendResponse({ ok: false, status: 0, reason: `content handler error: ${errMsg}` });
    }
  })();
  return true;
});

console.log("[rnp-ext content] wb-shifts-content.ts loaded on", location.href);
