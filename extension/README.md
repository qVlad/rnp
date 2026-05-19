# РНП — Chrome-расширение

Companion-расширение для сервиса [РНП](../) (модуль `/abtest`) — A/B-тесты
карточек Wildberries с честной статистикой (Z-test + Wilson CI).

> **История**: расширение изначально писалось под отдельный сервис `wbab`
> (Next.js). После порта wbab в РНП как модуля `/abtest` (миграция 0033)
> расширение перенесено сюда. В коде ещё много идентификаторов `wbab*`
> (storage keys, log prefixes, переменные `wbabUrl`/`wbabToken`) — это
> технический долг, переименование требует storage-migration. Снаружи
> (manifest name, UI options/popup) — уже «РНП».

## Что умеет (MVP, май 2026)

1. **Launcher** — на странице карточки в `seller.wildberries.ru` появляется
   виджет «Запустить A/B-тест в РНП». Один клик → открывается форма создания
   теста в wbab с предзаполненным `nmId`.
2. **Badge активного теста** — если для открытой карточки уже идёт тест в
   РНП, виджет показывает его состояние: активный вариант, прогресс выборки,
   время до следующей ротации, флаг «найден победитель».
3. **Уведомления о победителях** — service worker раз в N минут опрашивает
   РНП. При обнаружении нового winner-события — браузерное уведомление
   `chrome.notifications` + (опционально) дублирование в Telegram через
   bot API.
4. **Трекинг позиций в выдаче WB** — на страницах поиска/каталога
   `www.wildberries.ru` расширение находит карточки из активных тестов и
   записывает их позицию. Это помогает объяснить дисперсию показов между
   вариантами теста (если фото A было на 1-й странице, а B на 4-й — разница
   в трафике не от фото, а от позиции в SEO).

## Архитектура

```
Chrome
├── Content script: seller.wildberries.ru/* → launcher + badge
├── Content script: www.wildberries.ru/*    → трекинг позиций
├── Service worker (MV3): polling wbab API + notifications + Telegram forward
├── Popup: список активных тестов + быстрые действия
└── Options: URL backend'а wbab, токен, Telegram настройки
        │
        │ HTTP (Bearer auth)
        ▼
РНП backend (FastAPI, модуль /abtest)
└── /api/extension/* эндпоинты (будут добавлены отдельно)
```

Стек: Manifest V3, Vite + @crxjs/vite-plugin, React + TypeScript.

## Юридическая позиция

Расширение работает только в браузере пользователя, использует его сессию на
seller.wildberries.ru (не сторонний токен). Это «серая зона» по п. 9.9.6
оферты WB — все аналогичные расширения (CodeMP 10k+ users, Marpla,
MPSTATS, MarketGuru) живут так годами без массовых блокировок.

**Бэкенд РНП при этом работает исключительно с публичным WB API**
(`dev.wildberries.ru`) — это сохраняет основной сервис в «белой зоне».
Расширение является тонкой UX-обвязкой поверх своих собственных данных
пользователя.

Мы не используем расширение для:
- Скрейпинга чужих карточек (нет spy-функционала).
- Автоматизации действий, симулирующих пользователя (накрутки, фейк-выкупы).
- Сбора данных третьих лиц.

## Установка для разработки (3 шага, ~2 минуты)

```bash
cd extension
npm install
npm run build   # tsc + vite build → dist/
```

Затем в Chrome:
1. Открыть `chrome://extensions/`
2. Включить **Developer mode** (верхний правый угол)
3. **Load unpacked** → выбрать `extension/dist`
4. **Зайти на свой РНП** (`http://localhost:4098/` или `https://rnp.sellerfriends.ru/`) → залогиниться

→ **Расширение настроится автоматически** через `chrome.cookies` API:
content script на странице РНП пингует service worker, SW читает HttpOnly
cookie `rnp_session` (видна расширению при `permissions: ["cookies"]`) и
сохраняет URL+JWT в `chrome.storage.sync`. Появится notification
«РНП подключено». Cookie обновляется на любом будущем визите → токен
всегда свежий, ручной refresh не нужен.

Опционально для dev — `npm run dev` (Vite watch-mode, dist/ обновляется
на лету); пересборка в Chrome — кнопкой «Обновить» на `chrome://extensions/`.

**Manual fallback** (если auto-connect не сработал — например, юзер не
залогинен или URL не совпадает): Options → ввести URL РНП + JWT вручную.
JWT можно скопировать из DevTools → Application → Cookies → `rnp_session`.

## Production-сборка

```bash
npm run build   # tsc + vite build → dist/
npm run zip     # создаёт rnp-extension.zip для загрузки в CWS
```

## Состояние API: MOCK режим

Сейчас все запросы к РНП возвращают MOCK-данные (см. `src/lib/wbab-api.ts`,
константа `USE_MOCK = true`). Эндпоинты `/api/extension/*` на основном
backend ещё не реализованы.

Для перехода на реальное API:
1. Реализовать в РНП следующие эндпоинты (backend/app/api/extension.py):
   - `GET /api/extension/tests/active[?nmId=N]`
   - `GET /api/extension/winners/since?cursor=<unix-ms>`
   - `POST /api/extension/positions` (приём данных о позициях)
   - Аутентификация: Bearer token, привязанный к WbAccount пользователя.
2. Поставить `USE_MOCK = false` в `src/lib/wbab-api.ts`.
3. Опционально настроить опцию в options page «Сгенерировать токен» с
   deeplink в РНП.

## Структура

```
extension/
├── manifest.config.ts          # MV3 манифест (генерируется через @crxjs)
├── vite.config.ts              # Vite + @crxjs/vite-plugin + React
├── tsconfig.json
├── public/icons/               # 16/48/128 иконки
└── src/
    ├── background/index.ts     # Service worker (polling, notifications)
    ├── content/
    │   ├── seller-card.ts      # Content script на seller.wildberries.ru
    │   └── wb-search.ts        # Content script на www.wildberries.ru
    ├── popup/                  # Popup React-приложение
    ├── options/                # Options page React-приложение
    └── lib/
        ├── types.ts            # Доменные типы (синхронизировать с wbab API)
        ├── storage.ts          # chrome.storage обёртки
        ├── wbab-api.ts         # HTTP-клиент РНП (имя файла legacy) + MOCK
        └── wb-parsers.ts       # DOM/URL парсеры WB (самая хрупкая часть)
```

## Известные хрупкости

- **DOM seller-кабинета** ломается раз в 2-4 недели — селекторы в
  `wb-parsers.ts` придётся регулярно патчить. Все селекторы вынесены в
  константы наверху файла, с fallback-цепочкой.
- **DOM каталога WB** меняется реже, но тоже — особенно когда WB
  переключает A/B-тесты собственной выдачи.
- **MV3 service worker засыпает** через ~30 сек idle. Любая логика — через
  `chrome.alarms`, минимум 1 минута между тиками.

## Roadmap

- [ ] **Фаза 2**: token-less mode — расширение читает сессионную куку
      пользователя и шлёт в РНП данные, чтобы пользователю не нужно было
      вводить отдельный API-токен.
- [ ] **Фаза 3**: overlay-виджет с метриками теста прямо на карточке (без
      открытия РНП в отдельной вкладке).
- [ ] **Edge Add-ons** publish (быстрее CWS, бесплатно).
- [ ] **CWS publish** — после стабилизации (минимум 2-3 месяца внутреннего
      использования).
