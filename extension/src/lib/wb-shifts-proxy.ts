/**
 * Proxy для WB shifts API (перераспределение остатков) — **router** в SW.
 *
 * Архитектура (см. также `src/content/wb-shifts-content.ts`):
 *   1. SW не может сам fetch'ить seller-weekly-report.wildberries.ru —
 *      origin=chrome-extension://, cookies третьей стороны не прикрепляются,
 *      `Cookie` header forbidden в JS.
 *   2. Поэтому fetch выполняется content script'ом на вкладке
 *      seller.wildberries.ru — там origin совпадает, cookies нативные,
 *      localStorage с JWT-токенами доступен.
 *   3. Этот файл = роутер: находит вкладку seller.wildberries.ru →
 *      chrome.tabs.sendMessage → content script возвращает результат.
 *
 * Требование: у юзера должна быть открыта хотя бы одна вкладка
 * seller.wildberries.ru с залогиненной сессией. Если нет — возвращаем
 * ошибку с указанием открыть кабинет.
 */

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
 * Найти активную вкладку seller.wildberries.ru. Возвращает tabId или null
 * если ни одна вкладка не открыта.
 */
async function findSellerTab(): Promise<number | null> {
  const tabs = await chrome.tabs.query({
    url: "https://seller.wildberries.ru/*",
  });
  if (tabs.length === 0) return null;
  // Предпочитаем активную вкладку в активном окне
  const active = tabs.find((t) => t.active) ?? tabs[0];
  return active.id ?? null;
}

async function dispatchToContent<T = unknown>(
  msg: Record<string, unknown>,
): Promise<ShiftsProxyResult<T>> {
  const tabId = await findSellerTab();
  if (tabId == null) {
    return {
      ok: false,
      status: 0,
      reason:
        "no_seller_tab: открой вкладку https://seller.wildberries.ru/ в этом браузере (и убедись что залогинен)",
    };
  }
  try {
    const resp = (await chrome.tabs.sendMessage(tabId, msg)) as
      | ShiftsProxyResult<T>
      | undefined;
    if (!resp) {
      return {
        ok: false,
        status: 0,
        reason:
          "content_script_no_response: content script не ответил. Обнови страницу seller.wildberries.ru (Cmd+R) и повтори",
      };
    }
    return resp;
  } catch (e) {
    const errMsg = e instanceof Error ? e.message : String(e);
    return {
      ok: false,
      status: 0,
      reason: `tabs.sendMessage failed: ${errMsg}`,
    };
  }
}

// ─── Endpoints ────────────────────────────────────────────────────────

export type Quota = number;

export async function getQuota(
  officeId: number,
  kind: "src" | "dst" = "src",
): Promise<ShiftsProxyResult<{ quota: Quota }>> {
  return dispatchToContent({
    type: "wbShiftsProxyContent",
    op: "quota",
    officeId,
    kind,
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
  return dispatchToContent({
    type: "wbShiftsProxyContent",
    op: "stocks",
    nmId,
  });
}

export async function searchNms(
  pattern: string,
): Promise<ShiftsProxyResult<{ nms: Array<{ nmID: number; subjectName?: string }> }>> {
  return dispatchToContent({
    type: "wbShiftsProxyContent",
    op: "searchNms",
    pattern,
  });
}

export type CreateOrderItem = { chrtID: number; count: number };

export async function createOrder(args: {
  src: number;
  dst: number;
  nmID: number;
  count: CreateOrderItem[];
}): Promise<ShiftsProxyResult<{ success: boolean }>> {
  return dispatchToContent({
    type: "wbShiftsProxyContent",
    op: "createOrder",
    ...args,
  });
}
