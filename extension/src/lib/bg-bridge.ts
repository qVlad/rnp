/**
 * RPC-мост: content script → service worker.
 *
 * MV3: content scripts работают в контексте страницы (origin страницы),
 * поэтому cross-origin fetch к wbab.sellerfriends.ru блокируется CORS,
 * если wbab не вернёт Access-Control-Allow-Origin: https://seller.wildberries.ru.
 *
 * Решение: все запросы к wbab делает **service worker** (там origin =
 * chrome-extension://<id>, и host_permissions работают как whitelist
 * без CORS). Content scripts шлют типизированные сообщения SW.
 *
 * Использование:
 *   const test = await bgRequest({ type: "fetchActiveTestForNmId", nmId });
 */

import type { ActiveTest, WinnerEvent } from "./types";

/** Все валидные RPC-запросы из content scripts в SW. */
export type BgRequest =
  | { type: "fetchActiveTestForNmId"; nmId: number }
  | { type: "fetchActiveTests" }
  | { type: "fetchWinnersSince"; cursor: number }
  | {
      type: "postPositions";
      payload: {
        nmId: number;
        query: string;
        position: number;
        page: number;
        collectedAt: string;
      };
    }
  | { type: "openLauncher"; nmId: number }
  | { type: "openTestPage"; testId: string }
  /**
   * Auto-token (Часть 1 ветки feature/cycles-schedule):
   * content script на seller.wildberries.ru вызывает generateWbToken
   * (см. lib/wb-token.ts), получает JWT и шлёт сюда — SW делает
   * POST /api/extension/wb-token/save на wbab backend.
   */
  | { type: "saveWbToken"; jwt: string; expiresAt: number | null }
  /**
   * Возвращает текущий статус токена от backend:
   *   { hasToken, source, expiresAt, needsRefresh }
   * Content script использует чтобы решить: нужно ли вызывать
   * generateWbToken прямо сейчас, или текущий ещё свежий.
   */
  | { type: "getWbTokenStatus" }
  /**
   * WB Shifts API proxy (LEAD-016 fallback): SW делает fetch к
   * seller-weekly-report.wildberries.ru с credentials:'include' — куки
   * пользовательской сессии прикрепляются автоматически, IP браузерный.
   * Это обход того что backend РНП с другого IP получает 401 от WB.
   *
   * Поддерживаемые операции: see `wb-shifts-proxy.ts`.
   */
  | { type: "wbShiftsProxy"; op: "quota"; officeId: number; kind: "src" | "dst" }
  | { type: "wbShiftsProxy"; op: "stocks"; nmId: number }
  | { type: "wbShiftsProxy"; op: "searchNms"; pattern: string }
  | {
      type: "wbShiftsProxy";
      op: "createOrder";
      src: number;
      dst: number;
      nmID: number;
      count: Array<{ chrtID: number; count: number }>;
    };

/** Статус токена с backend wbab (см. /api/extension/wb-token/status). */
export type WbTokenStatus = {
  hasToken: boolean;
  source: "manual" | "auto" | null;
  expiresAt: string | null;
  needsRefresh: boolean;
};

/** Ответы SW — discriminated по `kind`. */
export type BgResponse =
  | { kind: "activeTest"; data: ActiveTest | null }
  | { kind: "activeTests"; data: ActiveTest[] }
  | { kind: "winners"; data: WinnerEvent[] }
  | { kind: "ok"; recorded?: boolean }
  | { kind: "wbTokenStatus"; data: WbTokenStatus | null }
  | {
      kind: "wbShiftsProxy";
      result:
        | { ok: true; status: number; data: unknown }
        | { ok: false; status: number; reason: string; body?: string };
    }
  | { kind: "error"; error: string };

/**
 * Отправить запрос в service worker и дождаться типизированного ответа.
 * При ошибке (SW спит, нет токена и т.п.) возвращает fallback или null.
 */
export async function bgRequest(req: BgRequest): Promise<BgResponse> {
  try {
    const resp = (await chrome.runtime.sendMessage(req)) as BgResponse | undefined;
    if (!resp) return { kind: "error", error: "no response from SW" };
    return resp;
  } catch (e) {
    return { kind: "error", error: (e as Error).message };
  }
}
