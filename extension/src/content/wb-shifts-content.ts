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
 * Архитектура: SW получает запрос от popup'а / backend'а → шлёт
 * chrome.tabs.sendMessage в открытую вкладку seller.wildberries.ru →
 * content script (этот файл) делает fetch → отдаёт результат обратно.
 *
 * Требование: у юзера должна быть открыта вкладка seller.wildberries.ru
 * (любая страница кабинета). Без неё proxy не работает — нужно открыть
 * (программно через chrome.tabs.create или попросить юзера).
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

/**
 * Достать JWT-токены WB из localStorage (если они там есть).
 * WB seller-portal хранит токены в разных ключах — пробуем известные имена.
 * Если не нашли — fetch может всё равно сработать благодаря cookies.
 */
function readWbTokens(): { authorizeV3?: string; wbSellerLk?: string } {
  const out: { authorizeV3?: string; wbSellerLk?: string } = {};
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (!k) continue;
      const v = localStorage.getItem(k);
      if (!v) continue;
      const lower = k.toLowerCase();
      if (lower.includes("authorizev3") || lower === "wb-authorize-v3") {
        out.authorizeV3 = v.replace(/^"|"$/g, "");
      }
      if (lower.includes("seller-lk") || lower === "wb-seller-lk") {
        out.wbSellerLk = v.replace(/^"|"$/g, "");
      }
    }
  } catch {
    /* ignore */
  }
  return out;
}

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
  const tokens = readWbTokens();
  const headers: Record<string, string> = {
    Accept: "*/*",
    "Content-Type": "application/json",
    "Root-Version": "v1.93.1",
  };
  if (tokens.authorizeV3) headers.AuthorizeV3 = tokens.authorizeV3;
  if (tokens.wbSellerLk) headers["Wb-Seller-Lk"] = tokens.wbSellerLk;

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
      console.log("[wbab-ext content] shifts proxy op=", msg.op);
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
      sendResponse(result);
    } catch (e) {
      const errMsg = e instanceof Error ? e.message : String(e);
      sendResponse({ ok: false, status: 0, reason: `content handler error: ${errMsg}` });
    }
  })();
  return true; // async sendResponse
});

console.log("[wbab-ext content] wb-shifts-content.ts loaded on", location.href);
