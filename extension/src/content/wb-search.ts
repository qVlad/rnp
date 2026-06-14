/**
 * Content script на www.wildberries.ru/catalog/*.
 *
 * Задача: трекинг позиций карточек, участвующих в активных A/B-тестах РНП,
 * по ключевикам поиска. Это позволит на странице теста показать селлеру:
 * «Вариант A был на 3-й странице → 1230 показов. Вариант B на 1-й странице
 * → 9800 показов». Большая разница в показах между вариантами при ротации
 * обычно объясняется именно сменой позиции.
 *
 * Логика:
 *   1. На любой странице каталога/поиска получаем кеш активных тестов из
 *      service worker.
 *   2. Парсим выдачу через wb-parsers.findSearchCards.
 *   3. Для каждой найденной карточки которая есть в активных тестах —
 *      отправляем событие в SW через bg-bridge: { type: "postPositions",
 *      payload: { nmId, query, position, page, collectedAt } }.
 *   4. SW шлёт POST /api/extension/positions на backend РНП.
 *
 * Что мы НЕ делаем (важно):
 *   • Не парсим чужие карточки (не наши SKU) — не делаем спай-функционал.
 *   • Не дёргаем поиск автоматически (это спам в WB) — работаем только с
 *     тем, что пользователь сам открыл в браузере.
 *   • Не сохраняем cookies, токены, личные данные пользователя.
 */

import {
  isSearchPage,
  isCatalogPage,
  extractSearchQuery,
  findSearchCards,
} from "@/lib/wb-parsers";
import { getCachedActiveTests, getSettings } from "@/lib/storage";
import { bgRequest } from "@/lib/bg-bridge";

async function collectPositions(): Promise<void> {
  const settings = await getSettings();
  if (!settings.enablePositionTracking) {
    console.debug("[rnp-ext] position tracking disabled");
    return;
  }

  if (!isSearchPage() && !isCatalogPage()) return;

  const query = extractSearchQuery() || derivePseudoQueryFromCatalogUrl();
  if (!query) return;

  const cards = findSearchCards();
  if (cards.length === 0) {
    console.debug("[rnp-ext] no cards found on", location.href);
    return;
  }

  const page = derivePageNumberFromUrl();
  const collectedAt = new Date().toISOString();

  // DEV-085 — конкурентное сравнение: шлём ПОЛНЫЙ ранг выдачи (наши +
  // конкуренты), но только для реального поиска (не каталог-броузинга — меньше
  // шума). Бэкенд сохраняет ранг ТОЛЬКО если в нём есть наша карточка
  // (анти-спай-гард на сервере) — произвольные чужие запросы не пишутся.
  if (isSearchPage()) {
    try {
      await bgRequest({
        type: "postSearchRanking",
        payload: {
          query,
          page,
          collectedAt,
          cards: cards.map((c) => ({ nmId: c.nmId, position: c.position })),
        },
      });
    } catch (e) {
      console.warn("[rnp-ext] bgRequest postSearchRanking failed:", e);
    }
  }

  // A/B-трекинг позиций наших тестовых карточек (как раньше) + подсветка.
  const activeTests = await getCachedActiveTests();
  if (activeTests.length === 0) return;
  const trackedNmIds = new Set(activeTests.map((t) => t.nmId));
  const matches = cards.filter((c) => trackedNmIds.has(c.nmId));
  if (matches.length === 0) {
    console.debug(
      `[rnp-ext] no tracked cards on "${query}" page ${page} (${cards.length} total cards)`,
    );
    return;
  }

  console.log(
    `[rnp-ext] found ${matches.length} tracked cards on "${query}" page ${page}`,
  );
  for (const c of matches) {
    try {
      await bgRequest({
        type: "postPositions",
        payload: {
          nmId: c.nmId,
          query,
          position: c.position,
          page,
          collectedAt,
        },
      });
    } catch (e) {
      console.warn("[rnp-ext] bgRequest postPositions failed:", e);
    }
    highlightTrackedCard(c.element);
  }
}

function derivePseudoQueryFromCatalogUrl(): string | null {
  // Каталог без явного search — используем последний сегмент URL как «query»
  // (например, /catalog/elektronika/list.aspx → "elektronika").
  try {
    const u = new URL(location.href);
    const segments = u.pathname.split("/").filter(Boolean);
    const idx = segments.findIndex((s) => s === "catalog");
    if (idx !== -1 && segments[idx + 1]) return segments[idx + 1];
  } catch {
    /* noop */
  }
  return null;
}

function derivePageNumberFromUrl(): number {
  try {
    const u = new URL(location.href);
    const p = u.searchParams.get("page");
    if (p) {
      const n = Number.parseInt(p, 10);
      return Number.isFinite(n) ? n : 1;
    }
  } catch {
    /* noop */
  }
  return 1;
}

function highlightTrackedCard(el: Element): void {
  const target = el as HTMLElement;
  if (target.dataset.rnpHighlighted === "1") return;
  target.dataset.rnpHighlighted = "1";
  target.style.outline = "2px solid #3b82f6";
  target.style.outlineOffset = "2px";
  target.style.borderRadius = "8px";
}

// ---- Lifecycle ----

// Первичный запуск с задержкой (карточки рендерятся лениво).
setTimeout(collectPositions, 1500);

// При скролле/подгрузке новых карточек повторяем сбор.
// На WB подгрузка через scroll — отслеживаем через IntersectionObserver
// на footer или через debounced scroll listener.
let scrollDebounce: number | undefined;
window.addEventListener(
  "scroll",
  () => {
    if (scrollDebounce) window.clearTimeout(scrollDebounce);
    scrollDebounce = window.setTimeout(collectPositions, 800);
  },
  { passive: true },
);

// SPA-роутинг — поиск/каталог переключаются без полной перезагрузки.
const _push = history.pushState.bind(history);
history.pushState = function (...args) {
  _push(...args);
  setTimeout(collectPositions, 1500);
};
window.addEventListener("popstate", () => setTimeout(collectPositions, 1500));
