/**
 * Парсеры DOM/URL Wildberries. Самая хрупкая часть расширения —
 * WB меняет вёрстку и URL-схемы ~раз в 2-4 недели, селекторы ломаются.
 *
 * Чтобы упростить поддержку:
 *   • все селекторы вынесены в константы наверху файла
 *   • каждый парсер возвращает null при «ничего не нашли» (не кидает)
 *   • в идеале — иметь fallback-цепочку: пробуем актуальный селектор,
 *     потом deprecated, потом универсальный (data-* атрибут)
 *
 * При первом ломании WB-вёрстки чинить **только тут**.
 */

// ---- URL-сигнатуры seller-кабинета (на 2026) ----
// WB многократно менял URL-схему. Реальные примеры на май 2026:
//   • НОВЫЙ (с 2026): /new-goods/card?nmID=173245249&type=EXIST_CARD
//     ← nmId в query parameter "nmID" (заглавный D), путь без него
//   • Промежуточный (2024-2025): /products/edit/12345678
//   • Старый: /products/cards/edit/12345678, /content/products/edit/12345678
// Регексы пробуются по очереди, первый match — используется.
const SELLER_CARD_URL_PATTERNS: RegExp[] = [
  // Query-форма: ...?nmID=12345  (case-insensitive под WB-вариативность)
  /[?&]nm[iI][dD]=(\d{6,12})(?:&|$|#)/,
  // Path-формы (legacy):
  /\/products\/(?:cards\/)?(?:edit\/)?(\d{6,12})(?:\?|\/|$)/i,
  /\/content\/products\/(?:edit\/)?(\d{6,12})(?:\?|\/|$)/i,
  // Новый раздел «Карточки» в URL path:
  /\/new-goods\/(?:card|edit)\/(\d{6,12})(?:\?|\/|$)/i,
];

const PRODUCT_LIST_URL_PATTERN = /\/(?:products|content\/products|new-goods)\/(?:list|cards|catalog)?\/?$/i;

/**
 * Извлечь nmId со страницы редактирования карточки.
 *
 * Поддерживает как URL-path-формы (legacy), так и query-параметры
 * (новый формат WB 2026 — /new-goods/card?nmID=...).
 */
export function extractNmIdFromSellerUrl(url: string = window.location.href): number | null {
  for (const re of SELLER_CARD_URL_PATTERNS) {
    const m = url.match(re);
    if (m && m[1]) {
      const n = Number.parseInt(m[1], 10);
      if (Number.isFinite(n)) return n;
    }
  }
  return null;
}

export function isProductListPage(url: string = window.location.href): boolean {
  return PRODUCT_LIST_URL_PATTERN.test(new URL(url, "https://seller.wildberries.ru").pathname);
}

/**
 * Страница встроенного A/B-теста WB (Джем):
 *   https://seller.wildberries.ru/product-card-a-b
 *   https://seller.wildberries.ru/product-card-a-b/...
 *
 * На этой странице мы показываем **overview-виджет** всех running wbab-тестов —
 * это глобальный список A/B, не привязанный к конкретной карточке.
 */
const AB_TEST_PAGE_PATTERN = /\/product-card-a-b(?:\/|$|\?)/i;

export function isABTestListPage(url: string = window.location.href): boolean {
  return AB_TEST_PAGE_PATTERN.test(
    new URL(url, "https://seller.wildberries.ru").pathname,
  );
}

// ---- URL-сигнатуры публичного каталога WB ----
// Примеры:
//   https://www.wildberries.ru/catalog/0/search.aspx?search=куртка%20мужская
//   https://www.wildberries.ru/catalog/elektronika/list.aspx
const SEARCH_URL_PATTERN = /\/catalog\/.*?\/search\.aspx/i;
const CATALOG_URL_PATTERN = /\/catalog\/.+/i;

export function isSearchPage(url: string = window.location.href): boolean {
  return SEARCH_URL_PATTERN.test(url);
}

export function isCatalogPage(url: string = window.location.href): boolean {
  return CATALOG_URL_PATTERN.test(url) && !SEARCH_URL_PATTERN.test(url);
}

export function extractSearchQuery(url: string = window.location.href): string | null {
  try {
    const u = new URL(url);
    return u.searchParams.get("search") || u.searchParams.get("query");
  } catch {
    return null;
  }
}

// ---- Парсеры карточек в выдаче ----
// На 2026 WB использует data-nm-id в product-card элементах.

const SEARCH_CARD_SELECTORS = [
  // Современный (2026): data-nm-id на корне карточки
  "[data-nm-id]",
  // Старый fallback: класс product-card с числовым id в href
  ".product-card a[href*='/catalog/']",
];

export type SearchCardInfo = {
  nmId: number;
  position: number; // 1-based в выдаче на странице
  element: Element;
};

/**
 * Найти все карточки на странице каталога/выдачи с их nmId и позицией.
 *
 * @note Позиция — это порядковый номер карточки в DOM. Не учитывает баннеры,
 *   рекламные блоки между карточками, бесконечную подгрузку. На странице
 *   обычно 100 карточек, при скролле подгружается ещё.
 */
export function findSearchCards(root: ParentNode = document): SearchCardInfo[] {
  const seen = new Set<number>();
  const results: SearchCardInfo[] = [];

  // Пробуем актуальный селектор первым
  const nodes = Array.from(root.querySelectorAll(SEARCH_CARD_SELECTORS[0]));

  let position = 0;
  for (const el of nodes) {
    position++;
    const raw = el.getAttribute("data-nm-id");
    if (!raw) continue;
    const nmId = Number.parseInt(raw, 10);
    if (!Number.isFinite(nmId) || seen.has(nmId)) continue;
    seen.add(nmId);
    results.push({ nmId, position, element: el });
  }

  // Fallback: парсим из href, если data-* нет (WB поменял атрибут)
  if (results.length === 0) {
    const links = Array.from(root.querySelectorAll(SEARCH_CARD_SELECTORS[1])) as HTMLAnchorElement[];
    let pos = 0;
    for (const a of links) {
      pos++;
      const m = a.href.match(/\/catalog\/(\d{6,12})\//i);
      if (!m) continue;
      const nmId = Number.parseInt(m[1], 10);
      if (!Number.isFinite(nmId) || seen.has(nmId)) continue;
      seen.add(nmId);
      results.push({ nmId, position: pos, element: a });
    }
  }

  return results;
}

// ---- Парсеры seller-кабинета ----

/**
 * Заголовок («якорь») страницы редактирования карточки — куда инжектить
 * launcher-кнопку и badge.
 *
 * WB многократно менял разметку — нужны fallback'и от самого специфичного
 * к самому общему. На странице /new-goods/card (новый формат 2026) может
 * не быть `<main>` тега, поэтому ищем шире.
 */
export function findSellerCardHeaderAnchor(): Element | null {
  // Стратегия 1: специфичные классы товарного заголовка
  const headerByClass = document.querySelector(
    "[class*='Product-header'], [class*='ProductHeader'], [class*='product-header']," +
      "[class*='Card-header'], [class*='CardHeader'], [class*='card-header']," +
      "[class*='Goods-header'], [class*='GoodsHeader']",
  );
  if (headerByClass) return headerByClass;

  // Стратегия 2: h1 на странице — самый общий маркер заголовка
  const h1 = document.querySelector("main h1, [class*='product'] h1, [class*='card'] h1, [class*='goods'] h1, h1");
  if (h1) return h1;

  // Стратегия 3: header tag в типичных контейнерах
  const headerTag = document.querySelector("#app header, #root header, main header, header");
  if (headerTag) return headerTag;

  // Стратегия 4 (последний шанс): первый видимый top-level контейнер
  // с aria-label про карточку
  const ariaCard = document.querySelector(
    "[aria-label*='карточк' i], [aria-label*='товар' i], [aria-label*='card' i]",
  );
  if (ariaCard) return ariaCard;

  return null;
}

/**
 * Получить название товара со страницы редактирования (для отображения
 * в badge). Не критично — используется только декоративно.
 */
export function extractProductName(): string | null {
  // Пробуем разные места куда WB может класть название.
  const candidates = [
    "main h1",
    "[class*='product'] h1",
    "[class*='card'] h1",
    "[class*='goods'] h1",
    "h1",
    "[class*='ProductName'], [class*='product-name']",
    "[class*='Title'] h1, [class*='title'] h1",
  ];
  for (const sel of candidates) {
    const el = document.querySelector(sel);
    const text = el?.textContent?.trim();
    if (text && text.length > 0 && text.length < 200) return text;
  }
  return null;
}
