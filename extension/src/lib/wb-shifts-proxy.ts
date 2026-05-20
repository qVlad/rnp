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

async function trySendMessage<T>(
  tabId: number,
  msg: Record<string, unknown>,
): Promise<{ ok: true; resp: ShiftsProxyResult<T> } | { ok: false; err: string }> {
  try {
    const resp = (await chrome.tabs.sendMessage(tabId, msg)) as
      | ShiftsProxyResult<T>
      | undefined;
    if (!resp) {
      return { ok: false, err: "no response" };
    }
    return { ok: true, resp };
  } catch (e) {
    return { ok: false, err: e instanceof Error ? e.message : String(e) };
  }
}

/**
 * Re-inject content scripts в seller-вкладку через chrome.scripting API.
 * Не используется в текущей версии — вместо этого делаем tabs.reload (надёжнее
 * для MAIN-world cache JWT). Оставлен на случай если в будущем понадобится
 * мягкая перезагрузка без reload страницы.
 */
// @ts-expect-error: unused fallback helper, оставлен на будущее
async function reinjectContentScripts(tabId: number): Promise<void> {
  try {
    const m = chrome.runtime.getManifest();
    const allScripts = m.content_scripts ?? [];
    let isolatedFile: string | null = null;
    let mainFile: string | null = null;
    for (const cs of allScripts) {
      const js = cs.js ?? [];
      for (const p of js) {
        if (p.includes("wb-shifts-content")) isolatedFile = p;
        if (p.includes("wb-shifts-interceptor-main")) mainFile = p;
      }
    }
    if (isolatedFile) {
      await chrome.scripting.executeScript({
        target: { tabId },
        files: [isolatedFile],
        world: "ISOLATED",
      });
    }
    if (mainFile) {
      await chrome.scripting.executeScript({
        target: { tabId },
        files: [mainFile],
        world: "MAIN",
      });
    }
    console.log(
      "[wb-shifts-proxy] re-injected scripts into tab",
      tabId,
      { isolatedFile, mainFile },
    );
  } catch (e) {
    console.warn("[wb-shifts-proxy] reinject failed:", e);
    // Fallback — полный reload вкладки. Юзер увидит "флэш" но content scripts
    // гарантированно встанут через MV3 content_scripts.
    try {
      await chrome.tabs.reload(tabId);
      // Ждём ~3 сек до завершения load + initial JS execution
      await new Promise((r) => setTimeout(r, 3000));
      console.log("[wb-shifts-proxy] fallback: reloaded tab", tabId);
    } catch (e2) {
      console.warn("[wb-shifts-proxy] reload fallback failed:", e2);
    }
  }
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
  // Первая попытка — обычный sendMessage
  let r = await trySendMessage<T>(tabId, msg);
  if (r.ok) return r.resp;
  // Если "Receiving end does not exist" / "no response" — content script
  // orphaned (после reload extension'а). Полный reload вкладки — самый
  // надёжный путь: MV3 content_scripts с document_start гарантированно
  // встанут, MAIN-world interceptor поймает свежие JWT из стартовых
  // WB-фронт запросов (validate / abac / balances).
  const isOrphan =
    r.err.includes("Receiving end does not exist") ||
    r.err.includes("Could not establish connection") ||
    r.err === "no response";
  if (isOrphan) {
    console.log("[wb-shifts-proxy] orphaned content script — reloading tab");
    try {
      await chrome.tabs.reload(tabId);
    } catch (e) {
      console.warn("[wb-shifts-proxy] tab.reload failed:", e);
    }
    // Ждём загрузку страницы + первые WB-вызовы фронта чтобы interceptor
    // закешировал JWT. 5 сек — компромисс между задержкой и надёжностью.
    await new Promise((res) => setTimeout(res, 5000));
    r = await trySendMessage<T>(tabId, msg);
    if (r.ok) return r.resp;
  }
  return {
    ok: false,
    status: 0,
    reason: `tabs.sendMessage failed: ${r.err}`,
  };
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
