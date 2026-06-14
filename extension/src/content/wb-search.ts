/**
 * Content script (ISOLATED) на www.wildberries.ru — приём ранга выдачи.
 *
 * Источник данных — MAIN-world interceptor `wb-search-interceptor-main.ts`,
 * который перехватывает JSON поискового API (search.wb.ru) и шлёт сюда через
 * window.postMessage. DOM-скрейпинг (старый `findSearchCards`) больше НЕ
 * используется для сбора — он хрупкий на виртуализированной выдаче WB.
 *
 * Делаем:
 *   1. Принимаем { __rnp: "wb-search-ranking", query, page, cards }.
 *   2. Шлём полный ранг в SW (`postSearchRanking`) — backend сохранит только
 *      если в выдаче есть наша карточка (анти-спай-гард, DEV-085).
 *   3. Для nmId из активных A/B-тестов — дополнительно `postPositions`
 *      (трекинг позиций вариантов) + подсветка карточки в DOM (best-effort).
 *
 * Что НЕ делаем: не дёргаем поиск сами (только то, что юзер открыл), не
 * храним cookies/токены. Сбор гейтится настройкой `enablePositionTracking`.
 */
import { getCachedActiveTests, getSettings } from "@/lib/storage";
import { bgRequest } from "@/lib/bg-bridge";

type RankingMessage = {
  __rnp: "wb-search-ranking";
  query: string;
  page: number;
  cards: { nmId: number; position: number }[];
};

// Дедуп — interceptor уже дедупит по query|page 3с, но при SPA-навигации
// content script может получить повтор; держим короткую память.
const handled = new Set<string>();

async function onRanking(msg: RankingMessage): Promise<void> {
  const settings = await getSettings();
  if (!settings.enablePositionTracking) return;
  if (!msg.query || !Array.isArray(msg.cards) || msg.cards.length === 0) return;

  const key = `${msg.query}|${msg.page}|${msg.cards.length}`;
  if (handled.has(key)) return;
  handled.add(key);
  if (handled.size > 200) handled.clear();

  const collectedAt = new Date().toISOString();

  // 1) Полный ранг (наши + конкуренты) — backend фильтрует по нашей карточке.
  try {
    await bgRequest({
      type: "postSearchRanking",
      payload: {
        query: msg.query,
        page: msg.page,
        collectedAt,
        cards: msg.cards.map((c) => ({ nmId: c.nmId, position: c.position })),
      },
    });
  } catch (e) {
    console.warn("[rnp-ext] postSearchRanking failed:", e);
  }

  // 2) A/B-трекинг позиций тестовых карточек + подсветка.
  let trackedNmIds: Set<number>;
  try {
    const activeTests = await getCachedActiveTests();
    trackedNmIds = new Set(activeTests.map((t) => t.nmId));
  } catch {
    return;
  }
  if (trackedNmIds.size === 0) return;

  for (const c of msg.cards) {
    if (!trackedNmIds.has(c.nmId)) continue;
    try {
      await bgRequest({
        type: "postPositions",
        payload: {
          nmId: c.nmId,
          query: msg.query,
          position: c.position,
          page: msg.page,
          collectedAt,
        },
      });
    } catch (e) {
      console.warn("[rnp-ext] postPositions failed:", e);
    }
    highlightTrackedCard(c.nmId);
  }
}

function highlightTrackedCard(nmId: number): void {
  // Best-effort — DOM может отличаться, тогда просто no-op.
  const el = document.querySelector(`[data-nm-id="${nmId}"]`) as HTMLElement | null;
  if (!el || el.dataset.rnpHighlighted === "1") return;
  el.dataset.rnpHighlighted = "1";
  el.style.outline = "2px solid #3b82f6";
  el.style.outlineOffset = "2px";
  el.style.borderRadius = "8px";
}

window.addEventListener("message", (ev: MessageEvent) => {
  if (ev.source !== window) return;
  const data = ev.data as RankingMessage | undefined;
  if (!data || data.__rnp !== "wb-search-ranking") return;
  void onRanking(data);
});

console.debug("[rnp-ext] wb-search receiver ready on", location.href);
