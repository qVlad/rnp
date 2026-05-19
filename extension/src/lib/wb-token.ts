/**
 * Авто-получение Personal WB API token через cabinet JSON-RPC.
 *
 * Endpoint (обнаружен через HAR-анализ кабинета WB 2026):
 *   POST https://seller-content.wildberries.ru/ns/suppliers-auth-tokens/
 *        suppliers-portal-core/api/v1/tokensjrpc
 *   headers:
 *     authorizev3: <JWT с client_id=seller-portal>   ← ОБЯЗАТЕЛЬНО
 *     wb-seller-lk: <JWT с Z-Sccode/Z-Sfid/...>      ← ОБЯЗАТЕЛЬНО (контекст)
 *   body: {"method":"generateToken","params":{"team":"render"},"jsonrpc":"2.0","id":"json-rpc_N"}
 *   response: { "result": { "token": "<JWT>" } }
 *
 * ⚠ Cookies для tokensjrpc НЕ используются — WB ждёт оба JWT в кастомных
 * хедерах. Без них → 401. Эти токены WB кабинет хранит в localStorage
 * текущей вкладки seller.wildberries.ru (имена ключей меняются от версии
 * к версии — поэтому ищем по СОДЕРЖИМОМУ JWT, а не по имени ключа).
 *
 * Эта функция дёргается:
 *   1. Из content script на seller.wildberries.ru при первом заходе
 *      пользователя (если enableAutoToken=true).
 *   2. Из service worker периодически (раз в N мин) если
 *      backend сказал needsRefresh=true.
 *      В SW localStorage страницы НЕ доступен → SW путь работает только
 *      когда content script одной из открытых вкладок передал токены через
 *      postMessage (TODO, пока не реализовано). Основной путь — content script.
 */

const TOKENSJRPC_URL =
  "https://seller-content.wildberries.ru/ns/suppliers-auth-tokens/suppliers-portal-core/api/v1/tokensjrpc";

type TokenJrpcResponse = {
  jsonrpc?: string;
  id?: string;
  result?: { token?: string };
  error?: { code?: number; message?: string };
};

/**
 * Декодирует JWT payload без верификации. Возвращает разобранный объект
 * или null если формат не JWT.
 */
function tryDecodeJwt(s: string): Record<string, unknown> | null {
  if (typeof s !== "string" || s.length < 20) return null;
  const parts = s.split(".");
  if (parts.length !== 3) return null;
  try {
    const payloadB64 = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    const padded = payloadB64 + "=".repeat((4 - (payloadB64.length % 4)) % 4);
    return JSON.parse(atob(padded));
  } catch {
    return null;
  }
}

/**
 * Сканирует localStorage страницы seller.wildberries.ru и ищет два JWT:
 *   • authorizev3 — это JWT где payload.client_id === "seller-portal"
 *   • wb-seller-lk — это JWT где payload.data?.["Z-Sccode"] существует
 *
 * Возвращает оба токена или null если хотя бы один не найден.
 *
 * Почему не по имени ключа: WB меняет имена ключей localStorage между
 * версиями кабинета (видели как "access-token-v3", "authorizev3",
 * "wb.cabinet.access-token-v3" и т.п.). Содержимое JWT — стабильный
 * признак.
 */
export function extractWbAuthHeaders(): {
  authorizev3: string;
  wbSellerLk: string;
} | null {
  if (typeof localStorage === "undefined") return null;
  let authv3: string | null = null;
  let lk: string | null = null;
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i);
    if (!key) continue;
    const val = localStorage.getItem(key);
    if (!val) continue;
    // Значение может быть JWT напрямую, либо JSON с полем token/value
    const candidates: string[] = [val];
    try {
      const parsed = JSON.parse(val);
      if (typeof parsed === "string") candidates.push(parsed);
      else if (parsed && typeof parsed === "object") {
        for (const f of ["token", "value", "accessToken", "jwt"]) {
          if (typeof (parsed as Record<string, unknown>)[f] === "string") {
            candidates.push((parsed as Record<string, string>)[f]);
          }
        }
      }
    } catch {
      // не JSON — это OK
    }
    for (const cand of candidates) {
      const payload = tryDecodeJwt(cand);
      if (!payload) continue;
      if (!authv3 && payload.client_id === "seller-portal") {
        authv3 = cand;
        console.log(`[wbab-ext] found authorizev3 в localStorage["${key}"], user=${payload.user}`);
      }
      const data = (payload as { data?: Record<string, unknown> }).data;
      if (!lk && data && typeof data === "object" && "Z-Sccode" in data) {
        lk = cand;
        console.log(`[wbab-ext] found wb-seller-lk в localStorage["${key}"], Z-Sfid=${data["Z-Sfid"]}`);
      }
      if (authv3 && lk) break;
    }
    if (authv3 && lk) break;
  }
  if (!authv3 || !lk) {
    console.warn(
      `[wbab-ext] WB auth tokens НЕ найдены в localStorage (authorizev3=${!!authv3}, wb-seller-lk=${!!lk}). ` +
        `Возможно вы не залогинены в seller.wildberries.ru, или WB сменил формат хранения токенов.`,
    );
    return null;
  }
  return { authorizev3: authv3, wbSellerLk: lk };
}

/**
 * Получить свежий JWT от cabinet.
 * Возвращает { jwt, expiresAt } или null если запрос провалился (нет
 * сессии, blocked, error).
 *
 * @param scope - параметр "team" в JSON-RPC, default "render".
 *                Другие известные scopes (требуют экспериментов):
 *                  "content", "adv", "analytics", "marketplace"
 */
export async function generateWbToken(
  scope = "render",
): Promise<{ jwt: string; expiresAt: number | null } | null> {
  // Достаём авторизационные токены из localStorage страницы seller.wb.ru.
  // Без них WB вернёт 401 (cookies для этого endpoint он не использует).
  const auth = extractWbAuthHeaders();
  if (!auth) {
    return null;
  }
  const rpcId = `wbab-ext-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  // 10-сек таймаут на запрос. Без явного AbortController наблюдали в проде
  // "(fetch-api): user aborted the request" когда SPA-навигация WB ломала
  // pending fetch. С AbortSignal поведение детерминированное: либо успех за 10с,
  // либо явный timeout error с понятным сообщением.
  const ctrl = new AbortController();
  const timeoutId = setTimeout(() => ctrl.abort("wbab-timeout-10s"), 10_000);
  try {
    const res = await fetch(TOKENSJRPC_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        // КРИТИЧЕСКИЕ хедеры — без них 401:
        authorizev3: auth.authorizev3,
        "wb-seller-lk": auth.wbSellerLk,
      },
      credentials: "include", // на всякий случай — некоторые сабрауты WB всё же читают куки
      signal: ctrl.signal,
      body: JSON.stringify({
        method: "generateToken",
        params: { team: scope },
        jsonrpc: "2.0",
        id: rpcId,
      }),
    });
    clearTimeout(timeoutId);

    if (!res.ok) {
      console.warn(`[wbab-ext] tokensjrpc returned ${res.status} ${res.statusText}`);
      return null;
    }

    const data = (await res.json()) as TokenJrpcResponse;
    if (data.error) {
      console.warn(`[wbab-ext] tokensjrpc error:`, data.error);
      return null;
    }
    const jwt = data.result?.token;
    if (!jwt || typeof jwt !== "string") {
      console.warn(`[wbab-ext] tokensjrpc returned empty token`);
      return null;
    }

    const expiresAt = decodeJwtExp(jwt);
    console.log(
      `[wbab-ext] tokensjrpc OK, token length=${jwt.length}, expires=${expiresAt ? new Date(expiresAt).toISOString() : "unknown"}`,
    );
    return { jwt, expiresAt };
  } catch (e) {
    clearTimeout(timeoutId);
    const err = e as Error;
    // AbortError бывает в двух случаях:
    //  1. Наш собственный timeout 10с — это обычно WB сильно тормозит.
    //  2. Внешний abort (например, страница ушла на другой URL и браузер
    //     отменил pending fetches). Тоже норм — попробуем при следующем заходе.
    if (err.name === "AbortError" || ctrl.signal.aborted) {
      console.warn(
        `[wbab-ext] tokensjrpc aborted (reason: ${String(ctrl.signal.reason ?? "external")}). Это могло быть от SPA-навигации WB либо нашего 10с timeout — попробуем при следующем заходе.`,
      );
      return null;
    }
    console.warn(`[wbab-ext] tokensjrpc fetch failed:`, err.message);
    return null;
  }
}

/**
 * Декодирует exp-claim из JWT без верификации подписи (мы не валидируем
 * подпись — это делает WB при использовании токена). Просто читаем
 * exp чтобы знать когда обновлять.
 *
 * Возвращает unix-ms или null если JWT невалидный по формату.
 */
function decodeJwtExp(jwt: string): number | null {
  try {
    const parts = jwt.split(".");
    if (parts.length !== 3) return null;
    // base64url → base64
    const payloadB64 = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    const padded = payloadB64 + "=".repeat((4 - (payloadB64.length % 4)) % 4);
    const payload = JSON.parse(atob(padded)) as { exp?: number };
    if (typeof payload.exp === "number") {
      return payload.exp * 1000; // sec → ms
    }
    return null;
  } catch {
    return null;
  }
}
