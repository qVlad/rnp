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

// Дедуп для auto-connect: in-memory hash последней отправленной ПАРЫ
// (AuthV3 + Wb-Seller-Lk). Содержит last-12 chars каждого через ":".
// BUG-DEV-006: раньше был только AuthV3 — но он валиден ~1 год, не
// меняется. Wb-Seller-Lk живёт 5 мин, должен обновляться каждый fetch.
// Со старым дедупом content script отправлял пару один раз и больше
// никогда — короткий токен на backend протухал.
// SW делает второй уровень дедупа (chrome.storage.local) — оба теперь
// сравнивают композитный hash.
let lastSentTokensHash: string | null = null;

function maybeForwardLkAutoConnect(): void {
  if (!cachedAuthV3 || cachedAuthV3.length < 32) return;
  const a = cachedAuthV3.slice(-12);
  const l = cachedWbSellerLk ? cachedWbSellerLk.slice(-12) : "none";
  const hash = `${a}:${l}`;
  if (hash === lastSentTokensHash) return;
  lastSentTokensHash = hash;
  chrome.runtime
    .sendMessage({
      type: "rnp:lk-autoconnect",
      authorize_v3: cachedAuthV3,
      wb_seller_lk: cachedWbSellerLk,
      root_version: cachedRootVersion,
    })
    .then((r) => {
      console.log("[rnp-ext content] lk-autoconnect →", r);
    })
    .catch((e) => {
      // SW мог проснуться/уснуть — сбрасываем hash чтобы повторить на след. tick'е
      console.warn("[rnp-ext content] lk-autoconnect failed:", e);
      lastSentTokensHash = null;
    });
}

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
  maybeForwardLkAutoConnect();
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
  // Сначала пробуем разобрать JSON-тело — WB на 4xx тоже возвращает
  // структурированный {error:true, errorText, additionalErrors:{placement:[…]}}.
  // Без этого reason оказывается просто "Bad Request" и юзер не понимает
  // что у склада-источника квота исчерпана.
  let parsed: unknown = null;
  try {
    parsed = JSON.parse(text);
  } catch {
    /* not JSON — обработаем ниже */
  }
  const isWbErrorBody =
    parsed !== null &&
    typeof parsed === "object" &&
    (parsed as { error?: boolean }).error === true;

  if (isWbErrorBody) {
    const p = parsed as {
      errorText?: string;
      additionalErrors?: { placement?: string[] } & Record<string, unknown>;
    };
    const placement = p.additionalErrors?.placement;
    const extra =
      placement && placement.length > 0 ? ` [${placement.join(",")}]` : "";
    return {
      ok: false,
      status: resp.status,
      reason: `WB-logical error: ${p.errorText ?? "unknown"}${extra}`,
      body: text.slice(0, 500),
    };
  }
  if (!resp.ok) {
    return {
      ok: false,
      status: resp.status,
      reason: resp.headers.get("x-reason") || resp.statusText,
      body: text.slice(0, 500),
    };
  }
  if (parsed === null) {
    return {
      ok: false,
      status: resp.status,
      reason: "JSON parse failed",
      body: text.slice(0, 500),
    };
  }
  const data =
    typeof parsed === "object" && parsed !== null && "data" in (parsed as object)
      ? (parsed as { data: unknown }).data
      : parsed;
  return { ok: true, status: resp.status, data };
}

chrome.runtime.onMessage.addListener((rawMsg, _sender, sendResponse) => {
  const typed = rawMsg as { type?: string };
  // Debug-snapshot: что у content script сейчас в кеше токенов и сколько
  // fetch'ей перехватил MAIN interceptor. Вызывается из SW DevTools:
  //   chrome.runtime.sendMessage({type:"rnp:debug-status"}, console.log)
  if (typed?.type === "rnp:debug-status") {
    sendResponse({
      origin: location.origin,
      href: location.href,
      interceptCount,
      hasAuthV3: !!cachedAuthV3,
      authV3Suffix: cachedAuthV3 ? cachedAuthV3.slice(-12) : null,
      hasWbSellerLk: !!cachedWbSellerLk,
      wbSellerLkSuffix: cachedWbSellerLk ? cachedWbSellerLk.slice(-12) : null,
      rootVersion: cachedRootVersion,
      lastSentHash: lastSentTokensHash,
    });
    return true;
  }
  if (typed?.type !== "wbShiftsProxyContent") return false;
  const msg = rawMsg as ProxyMsg;
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
