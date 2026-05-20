/**
 * Proxy для WB shifts API (перераспределение остатков).
 *
 * Архитектура: backend РНП не может авторизоваться в seller-weekly-report.wildberries.ru
 * напрямую — WB пинит сессию к IP/cookies браузера пользователя. Решение —
 * расширение делает fetch с credentials:'include' к WB-домену с куками
 * пользователя, и возвращает результат backend'у РНП.
 *
 * Этот модуль — низкоуровневый fetch wrapper. Поверх него `background/index.ts`
 * выставляет message-handler'ы для popup и для polling jobs (фаза 2).
 *
 * Требует host_permissions: https://seller-weekly-report.wildberries.ru/*
 * (manifest.config.ts) — без него SW-fetch с credentials:'include' блокируется.
 */

const SHIFTS_BASE = "https://seller-weekly-report.wildberries.ru/ns/shifts/analytics-back/api/v1";

/**
 * Достать все cookies для wildberries.ru через chrome.cookies API и собрать
 * в строку для Cookie header.
 *
 * Зачем: fetch из SW с `credentials:'include'` к WB **не** прикрепляет куки
 * автоматически, потому что origin = `chrome-extension://...`, а куки
 * scope'ятся к origin'у. Chrome'у нужно явное `host_permissions` ИЛИ ручной
 * Cookie header. Manifest даёт `permissions:["cookies"]` — этого достаточно
 * чтобы прочитать куки и сложить в header.
 */
async function buildCookieHeader(url: string): Promise<string> {
  try {
    const all = await chrome.cookies.getAll({ url });
    return all.map((c) => `${c.name}=${c.value}`).join("; ");
  } catch (e) {
    console.warn("[wb-shifts-proxy] cookies.getAll failed:", e);
    return "";
  }
}

/**
 * Достать AuthorizeV3 и Wb-Seller-Lk из cookies (на случай если WB их
 * именно через cookies отдаёт). Если они в cookies — добавим в одноимённые
 * headers (WB shifts API проверяет именно headers, не cookies).
 */
async function extractAuthHeaders(url: string): Promise<Record<string, string>> {
  const out: Record<string, string> = {};
  try {
    const cookies = await chrome.cookies.getAll({ url });
    for (const c of cookies) {
      const n = c.name.toLowerCase();
      if (n === "authorizev3" || n === "wb-authorize-v3" || n === "wbauthorizev3") {
        out.AuthorizeV3 = c.value;
      }
      if (n === "wb-seller-lk" || n === "wbsellerlk" || n === "wb_seller_lk") {
        out["Wb-Seller-Lk"] = c.value;
      }
    }
  } catch {
    /* ignore */
  }
  return out;
}

export type ShiftsProxyOK<T = unknown> = {
  ok: true;
  status: number;
  data: T;
};
export type ShiftsProxyErr = {
  ok: false;
  status: number;
  reason: string;
  body?: string;
};
export type ShiftsProxyResult<T = unknown> = ShiftsProxyOK<T> | ShiftsProxyErr;

/**
 * Headers которые WB-фронт seller.wildberries.ru шлёт ко всем shifts-вызовам
 * (по HAR 2026-05-19). credentials:'include' прикрепит куки автоматически,
 * AuthorizeV3 / Wb-Seller-Lk не нужны — они частично избыточны если есть
 * cookies (browser session), но WB всё равно проверяет их если они есть.
 * Лучше всего совсем не передавать их — пусть WB полагается на cookies.
 */
function buildHeaders(): HeadersInit {
  return {
    Accept: "*/*",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    "Content-Type": "application/json",
    Origin: "https://seller.wildberries.ru",
    Referer: "https://seller.wildberries.ru/",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
  };
}

async function callShifts<T = unknown>(
  method: "GET" | "POST",
  path: string,
  options: { params?: Record<string, string | number>; body?: unknown } = {},
): Promise<ShiftsProxyResult<T>> {
  let url = `${SHIFTS_BASE}${path}`;
  if (options.params) {
    const qs = new URLSearchParams(
      Object.entries(options.params).map(([k, v]) => [k, String(v)]),
    ).toString();
    if (qs) url += `?${qs}`;
  }
  // Ручное прикрепление cookies — credentials:'include' из chrome-extension://
  // origin'а не работает. См. buildCookieHeader().
  const cookieHeader = await buildCookieHeader(url);
  const authHeaders = await extractAuthHeaders(url);
  const headers: Record<string, string> = {
    ...buildHeaders(),
    ...authHeaders,
  };
  if (cookieHeader) headers.Cookie = cookieHeader;
  console.log("[wb-shifts-proxy] fetch", method, url, {
    cookieCount: cookieHeader.split(";").length,
    hasAuthV3: "AuthorizeV3" in headers,
    hasWbSellerLk: "Wb-Seller-Lk" in headers,
  });
  // 10-секундный timeout — иначе при сетевых проблемах popup висит вечно.
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
  // WB-envelope: {data: ..., error: bool, errorText: string}
  try {
    const parsed = JSON.parse(text);
    if (parsed && typeof parsed === "object" && parsed.error === true) {
      return {
        ok: false,
        status: resp.status,
        reason: `WB-logical error: ${parsed.errorText ?? "unknown"}`,
        body: text.slice(0, 500),
      };
    }
    const data = (parsed && typeof parsed === "object" && "data" in parsed)
      ? (parsed.data as T)
      : (parsed as T);
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

// ─── Endpoints ────────────────────────────────────────────────────────

export type Quota = number;

export async function getQuota(
  officeId: number,
  kind: "src" | "dst" = "src",
): Promise<ShiftsProxyResult<{ quota: Quota }>> {
  return callShifts("GET", "/quota", {
    params: { officeID: officeId, type: kind },
  });
}

export type StocksOffice = {
  officeID: number;
  officeName: string;
  inStock: Array<{ chrtID: number; count: number; techSize?: string }>;
};

export async function getStocks(
  nmId: number,
): Promise<ShiftsProxyResult<{ src: StocksOffice[] }>> {
  return callShifts("GET", "/stocks", { params: { nmID: nmId } });
}

export async function searchNms(
  pattern: string,
): Promise<ShiftsProxyResult<{ nms: Array<{ nmID: number; subjectName?: string }> }>> {
  return callShifts("GET", "/nms", { params: { pattern } });
}

export type CreateOrderItem = { chrtID: number; count: number };

export async function createOrder(args: {
  src: number;
  dst: number;
  nmID: number;
  count: CreateOrderItem[];
}): Promise<ShiftsProxyResult<{ success: boolean }>> {
  return callShifts("POST", "/order", {
    body: { order: args },
  });
}
