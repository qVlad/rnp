import { defineManifest } from "@crxjs/vite-plugin";
import pkg from "./package.json" with { type: "json" };

/**
 * Manifest V3 — обязателен с июня 2025 (MV2 deprecated).
 *
 * host_permissions:
 *   • https://seller.wildberries.ru/* — content script на странице карточки;
 *     чтение DOM и (через сессионную куку пользователя) запросы к внутреннему
 *     API кабинета. Это серая зона по п. 9.9.6 оферты WB, но все игроки
 *     (CodeMP, Marpla, MPSTATS, MarketGuru) живут так годами.
 *   • https://www.wildberries.ru/* — content script на выдаче поиска для
 *     трекинга позиций карточки по ключевикам теста.
 *   • https://rnp.sellerfriends.ru/* — наш собственный backend РНП
 *     (получение состояния тестов, отправка собранных данных).
 *   • https://wbab.sellerfriends.ru/* — legacy wbab инстанс, оставлен для
 *     совместимости со старыми настройками. Удалить после миграции юзеров.
 *   • http://localhost:4098/* — для dev-разработки rnp (nginx proxy → backend:8000).
 *   • http://localhost:3000/* — legacy wbab dev (Next.js).
 *
 * permissions:
 *   • storage — хранение настроек (URL backend'а, токены, кеш активных тестов)
 *   • notifications — алерт «победитель найден»
 *   • alarms — periodic polling SW
 *   • cookies — фаза 2 (token-less mode): чтение сессионной куки seller.wildberries.ru,
 *     чтобы РНП мог дёргать внутренний API кабинета от имени пользователя
 *     без отдельного API-токена. Текущая реализация это пока не использует —
 *     пермиссия запрашивается заранее, чтобы при включении фазы 2 не пугать
 *     пользователя ре-prompt'ом.
 */
export default defineManifest({
  manifest_version: 3,
  name: "РНП — A/B тесты Wildberries",
  short_name: "РНП",
  version: pkg.version,
  description:
    "Запуск и мониторинг A/B-тестов карточек Wildberries прямо из seller-кабинета. " +
    "Companion-расширение к сервису РНП (Z-test + Wilson CI).",
  icons: {
    "16": "icons/icon-16.png",
    "48": "icons/icon-48.png",
    "128": "icons/icon-128.png",
  },
  action: {
    default_popup: "src/popup/index.html",
    default_title: "РНП — A/B тесты",
    default_icon: {
      "16": "icons/icon-16.png",
      "48": "icons/icon-48.png",
      "128": "icons/icon-128.png",
    },
  },
  options_page: "src/options/index.html",
  background: {
    service_worker: "src/background/index.ts",
    type: "module",
  },
  content_scripts: [
    {
      // Карточка товара в seller-кабинете: launcher + badge активного теста.
      // URL'ы вида:
      //   /products/edit/:nmId
      //   /products/cards/:nmId
      //   /content/products/list (массовый список — там badge тоже хочется)
      matches: ["https://seller.wildberries.ru/*"],
      js: ["src/content/seller-card.ts"],
      run_at: "document_idle",
    },
    {
      // Поиск/каталог WB — трекинг позиций карточек, участвующих в активных
      // тестах, по ключевикам, заданным в настройках теста.
      // URL'ы вида:
      //   /catalog/0/search.aspx?search=<query>
      //   /catalog/*/list.aspx
      matches: ["https://www.wildberries.ru/*"],
      js: ["src/content/wb-search.ts"],
      run_at: "document_idle",
    },
    {
      // Auto-connect: на любой странице РНП content script говорит SW
      // «здесь РНП», SW через chrome.cookies API достаёт rnp_session
      // (HttpOnly) и сохраняет URL+JWT в settings. Юзеру не нужно
      // копировать токен руками — достаточно зайти в РНП в Chrome.
      // Добавлять новые домены сюда по мере появления production-инстансов.
      matches: [
        "http://localhost:4098/*",
        "https://rnp.sellerfriends.ru/*",
      ],
      js: ["src/content/rnp-detector.ts"],
      run_at: "document_idle",
    },
  ],
  host_permissions: [
    "https://seller.wildberries.ru/*",
    // seller-content — суб-домен который раздаёт cabinet endpoints, в т.ч.
    // tokensjrpc для auto-token. Без явного host_permissions SW-fetch с
    // credentials:'include' блокируется CORB.
    "https://seller-content.wildberries.ru/*",
    "https://www.wildberries.ru/*",
    // Продакшен-инстансы РНП (добавлять домены по мере деплоев).
    "https://rnp.sellerfriends.ru/*",
    // Legacy wbab-инстанс (совместимость со старыми настройками).
    "https://wbab.sellerfriends.ru/*",
    // Локальная разработка: РНП frontend по умолчанию слушает 4098.
    "http://localhost:4098/*",
    "http://localhost:3000/*",
  ],
  permissions: ["storage", "notifications", "alarms", "cookies"],
});
