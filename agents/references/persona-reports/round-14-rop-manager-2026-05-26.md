# UX-as-rop + UX-as-manager — раунд 14 (2026-05-26)

Reviewer: Claude Opus 4.7 (1M context). Версия: v0.38.0.

Контекст: post-feature review по фичам спринтов v0.35-0.38 после раунда 13
synthesis'а. Проверены 18 задач (LEAD-080..097 + HYP-001/003/004/005/006).
Фокус Z2 — командные/managerial процессы.

---

## --as ROP

«Понедельник утро, открываю SellerFriends — что делаю?»

### Scoreboard pre-aggregation (TASK-LEAD-087)

**Что работает:**

- **Архитектура чистая.** `manager_weekly_scoreboard` (миграция 0061) с
  composite PK `(tenant, manager_user_id, week_start)`. Celery beat
  `sync.manager_scoreboard` в `04:30 МСК` — сразу после `sync_report_detail`
  (04:15) — закрытые цифры свежие к утреннему открытию. `_WEEKS_TO_AGGREGATE
  = 4` (текущая + 3 закрытые) — sane default для типичного UI use-case.
- **Endpoint `/by-manager` корректно fallback'ит на live-compute** если
  таблица пустая для (tenant, week_start). Поле `source: "scoreboard" |
  "live"` есть в API-ответе. Идемпотентность через `on_conflict_do_update`.
- **Сортировка та же** (revenue desc, no_brands в хвост) — frontend на
  стороне сервера и в кэш-таблице одинаковая. Не будет drift.
- **Latency win:** на 10+ менеджерах было N×`compute_dashboard` (3-5s),
  теперь — простое `SELECT WHERE tenant + week_start` (50ms). Зафиксировано
  в docstring `weekly_report.py:88`.
- **Per-tenant trigger:** `sync_manager_scoreboard(tenant_id=X)` для ad-hoc
  вызовов — например после backfill'а report_detail.

**Боль / шероховатости:**

- **`source` field в API не отрисован в UI.** Frontend (`WeeklyReport.tsx:
  scoreboardQ`) принимает только `items` и не показывает «scoreboard» vs
  «live» — а это полезный signal для debug'а (РОП видит свежий manager
  без data, идёт в Celery beat status проверять). Можно добавить:
  - badge «🟢 кеш / 🟡 live-compute» в углу секции «По менеджерам»
  - tooltip «обновлено: {scoreboard.updated_at}» (хранится в таблице, но
    в API не возвращается — нужно расширить DTO)
- **Stale check отсутствует.** Если beat не отработал 2 дня (Celery worker
  упал), endpoint молча отдаёт старые цифры. Имеет смысл сравнивать
  `updated_at > NOW() - 26h` → fallback на live + warn.
- **Когда таблица частично заполнена** (5 из 10 менеджеров pre-aggregated,
  5 новых) — endpoint возвращает только pre-aggregated 5. Логика
  «если rows → не делаем fallback» (`weekly_report.py:97-108`) =
  partial data без warning'а. Для нового менеджера будет «менеджер не
  виден» до следующего nightly run'а. Лучше: если len(rows) < live_count →
  augment либо warning.
- **`task_session_scope` без tenant_id в loop'е:** `_aggregate_all_async`
  выбирает tenants одним session, потом для каждого открывает свой
  `task_session_scope`. На большом числе тенантов (RNP single-tenant, но
  архитектурно — multi-cabinet) — N сессий + N connections. На текущем
  проде нерелевантно, но архитектурный flag.

**Что предложить:**

- **TASK: показать `source` + `updated_at` в UI scoreboard'а** — badge
  + tooltip. Низкоприоритетно, но helpful для debug'а.
- **TASK: stale-check (updated_at > 26h → live fallback + warn)** —
  защита от долгого простоя Celery.

### ManagerSummary page (HYP-005)

**Что работает:**

- **Drill-down открыт.** Scoreboard → клик на имя менеджера → `/manager-
  summary?manager_id=X&week_start=Y`. Page composes 5 секций:
  - Top-KPI (revenue/margin/orders/returns + WoW)
  - Top-3 рекомендации (post-filter по brand-scope менеджера)
  - Top-5 SKU by revenue + by margin
  - Активные алерты (system-wide, без brand-filter — честно
    задокументировано в комментарии)
  - Per-brand комментарии менеджера + общий
- **RBAC frontend:** `canAccess = director || head_of_sales`. Manager
  попадает на URL → видит баннер «Доступ только для director / head_of_sales».
- **No_brands защита:** в scoreboard'е имя менеджера без брендов не
  кликабельно (`m.no_brands || m.brands.length === 0 ? plain : Link`).
  Sane — открывать summary без брендов бессмысленно.
- **Empty state**: если менеджер не нашёлся в scoreboard — «Менеджер не
  найден в scoreboard'е за YYYY-MM-DD» + ссылка обратно. Не падает.
- **Top-N=50 → slice(5)** — backend отдаёт top-50 SKU, post-filter
  оставляет тех, чей `brand ∈ manager.brands`, затем slice(0,5). Это
  hack для отсутствующего brand-фильтра в backend'е, но работает.

**Боль:**

- **RBAC только на фронте.** API endpoints `/weekly-report/by-manager`,
  `/top-skus`, `/recommendations`, `/alerts`, `/comment/all` — каждый
  имеет свой guard, но они **не валидируют, что вызывающий имеет право
  смотреть конкретного `manager_id`**. Manager-роль:
  - `by-manager` → 403 (`require_director_or_head`). ✓
  - `top-skus` → brand-scope (видит только свои бренды). Manager
    не получит чужих SKU автоматически — RBAC через `current_brands_filter`.
  - `recommendations` → brand-scope (то же).
  - `alerts` → tenant-wide (manager увидит все алерты).
  - `comment/all` → manager видит только overall + свои brand-комментарии
    (`weekly_report_comment.py:14`). Чужой бренд = не вернётся.
  - Итог: manager напрямую запросить `?manager_id=OTHER` через URL —
    данные он не получит (frontend 403 не пустит к API, и даже если
    обойти — RBAC всех endpoint'ов фильтрует). **Защита OK по сути,
    но через 2 слоя.**
- **`scoreboardQ` грузит ВЕСЬ scoreboard** (всех менеджеров tenant'а)
  чтобы найти одного по `manager_id`. Излишне — лучше дедикейтный
  endpoint `/by-manager/{manager_user_id}?week_start=...` (или
  `/manager-summary` который агрегирует всё).
- **`recsQ` без brand-сужения на backend.** Recs приходят по полному
  scope'у текущего user'а (director видит все), потом frontend фильтрует
  по `manager.brands`. На больших tenant'ах с 100+ рекомендациями —
  лишний трафик. Можно `?brands=A,B` query param.
- **«Активные алерты» — system-wide.** Если у менеджера 0 brand-
  релевантных алертов, а tenant имеет 5 alerts по другим брендам —
  manager-summary покажет все 5. Сбивает контекст РОП'а: «это
  Петров провалил или это вообще?». Комментарий в коде это признаёт,
  но в UI нет дисклеймера.
- **Отсутствует ссылка на «открыть weekly-report этого менеджера»**
  с фильтром `?brand=A,B`. Сейчас «← к /weekly-report» возвращает на
  общий — теряется brand-контекст.

**Что предложить:**

- **TASK: backend RBAC на `?manager_id=X`** — guard который проверяет
  что target_user.tenant == caller.tenant и (caller.role in
  director/head). Защита defence-in-depth, даже если frontend не пустит.
- **TASK: dedicated `/manager-summary` endpoint** — один SQL, все
  данные о менеджере. Меньше N+1, меньше over-fetch'а.
- **TASK: alerts с brand-filter.** Передавать `?brands=...` если
  alert-движок brand-aware.
- **TASK: «← weekly-report с brand-фильтром этого менеджера»** в actions
  ManagerSummary.

### Per-brand comment (HYP-004)

**Что работает:**

- **Brand-selector в Comment section:** dropdown «Общий / Бренд · A /
  Бренд · B». Для manager'а default = первый его бренд (`defaultBrand =
  availableBrands[0]`). Для РОПа default = «Общий».
- **isReadOnlyComment** — `manager && selectedBrand === null` → textarea
  disabled, placeholder «Общий комментарий пишет РОП / собственник. У
  тебя — read-only». Чисто, не скрывает функционал, объясняет
  ограничение.
- **«Другие комментарии за эту неделю»** — список под textarea: автор +
  scope (общий / бренд X) + ago. Манагер видит, что коллеги писали.
  РОП видит сводно overall + все brand-комментарии.
- **`/api/weekly-report/comment/all`** — RBAC корректный (manager видит
  свои + overall, director/head — всё).
- **Legacy localStorage migration** — при первом open пустого overall
  scope подгружает старый ключ. Не теряется.
- **Per-brand persist в queryKey** (`["weekly-report-comment", week,
  brand]`) — переключение brand не теряет ввод (TanStack кэш).
- **Cancel `setDirty(false)` после save** — кнопка «Сохранено» серая
  до следующего ввода. UX clear.

**Боль:**

- **Default «общий» для РОПа — он не сразу видит per-brand комментарии
  менеджеров.** РОП открывает weekly-report → textarea пустая (overall не
  заполнен) → ниже мелким «Другие комментарии за эту неделю: 3».
  Если эти 3 — содержательные («бренд X пострадал от акции» Петров,
  «бренд Y нашли дубли карточек» Иванов), РОП должен SCROLL вниз чтобы
  их найти. **Лучше:** если есть other-comments, в свёрнутом виде
  показывать первый/последние 2 в шапке секции; или флаг «N
  комментариев от менеджеров» в заголовке.
- **Конфликт автор'ства не показан.** Если оба РОПа пишут в overall —
  кто последний сохранил, того и видно. `commentQ.data.author_name` +
  `updated_at` есть, но нет «overwrite warning» если local `dirty` =
  true и пришёл свежий update.
- **Brand-selector не сохраняется per-tab.** РОП открыл бренд «X» в
  сессии 1 → перешёл в другой раздел → вернулся → selectedBrand
  сброшен на default («Общий»). Минор, но мешает workflow'у «пишу
  ответ менеджеру».
- **Quick-reply UX отсутствует.** РОП видит «Иванов: бренд X
  пострадал от акции» — хочет ответить. Сейчас: переключить
  selector на бренд X → написать → save. 3 действия. Лучше: inline
  «Ответить» под чужим комментарием → auto-switch scope.
- **`commentsAllQ` запрашивается всегда** (даже для manager'а без
  brand'ов). Не критично — лёгкий запрос.

**Что предложить:**

- **TASK: показать счётчик/превью other-comments в заголовке секции.**
  «Комментарий за неделю (3 от команды)» — кликабельно, разворачивает.
- **TASK: brand-selector persist в localStorage** —
  `weekly-report.comment-scope.v1`.
- **TASK: «Ответить» под комментарием коллеги** — auto-switch scope
  + focus textarea.

### Localization per-SKU recommendation (TASK-LEAD-088)

**Что работает:**

- **Backend per-SKU расчёт** — `WorstSkuLocalization.recommended_warehouse:
  str | None`, на основе per-nm_id buyer-cluster агрегата (модальный
  кластер этого SKU × top-склад tenant'а в этом кластере). См.
  `localization.py:516-543`. Корректное решение — оставляем tenant-wide
  как fallback.
- **Frontend гибрид per-SKU + tenant-wide fallback** —
  `Localization.tsx:374-431`. Логика:
  ```
  perSkuWh = s.recommended_warehouse
  useWh = perSkuWh ?? recommendedWarehouse?.warehouse ?? null
  recSource = perSkuWh ? "per_sku" : tenant-wide ? "tenant_wide" : "none"
  ```
- **Звёздочка `*` рядом с warehouse'ом** для tenant-wide fallback'ов:
  «⚠ tenant-wide fallback — у SKU не нашлось buyer-cluster'а». Хорошо
  отличается от per-SKU.
- **Tooltip multi-line** с пояснением «Рекомендация per-SKU на основе
  фактического распределения покупателей этого артикула» / «Fallback:
  tenant-wide эвристика».
- **Описание сверху таблицы обновлено** — «Рекомендация per-SKU на
  основе фактического распределения покупателей этого артикула
  (TASK-LEAD-088). Fallback на tenant-wide эвристику...» — РОП понимает
  что у него «лучшая логика», и где fallback.

**Боль:**

- **`*` без явного значка (просто символ).** Цвет `text-warn`, размер
  `text-[10px]`. На мобиле может быть нечитаемо. Лучше — emoji-tag
  «★ per-SKU / ☆ tenant-wide».
- **Empty case (`useWh === null`):** колонка показывает «—», кнопка
  «→ Поставка» не рендерится. РОП в строке видит «куда=—» без объяснения
  «не хватило данных для рекомендации». Можно tooltip + микро-пояснение.
- **Threshold per-SKU** не упомянут. Backend требует «≥ 5 заказов» —
  это для **всей таблицы** worst_skus. Но per-SKU buyer-cluster
  расчёт — что если у SKU 5 заказов, и все 5 в разных кластерах
  (по 1)? Модальный = noisy. Backend код `localization.py:516`:
  «низкая локализация при достаточном объёме (>= 5 заказов)» — для
  попадания в список. Расчёт `recommended_warehouse` — отдельная
  функция, может выдавать noise для маленьких SKU.
- **«TASK-LEAD-088 в tasks-lead.md помечен «Открыта»** — фича
  реализована (commit `4495a60`), но статус не обновлён. Stale.

**Что предложить:**

- **TASK: per-SKU rec min-confidence threshold** — если top-кластер
  имеет < 60% доли заказов SKU, не отдавать рекомендацию (NULL → fallback).
- **TASK: явный значок per-SKU (★) vs fallback (☆)** — заметнее
  на mobile.
- **CHORE: закрыть TASK-LEAD-088 статус** → Выполнено.

### Redistribution expanders (HYP-003)

**Что работает:**

- **3 expander'а после PageHeader:** «📍 Локализация заказов» / «🚚
  Калькулятор обычной поставки» / «🚛 Калькулятор транзита». Свёрнуты
  по default'у (`defaultOpen=false`), persist в localStorage с разными
  ключами. Standalone-страницы остаются работающими.
- **Workflow покрыт:** РОП открыл /redistribution → раскрыл «Локализация» →
  увидел % + top-5 worst SKU → выбрал артикул → раскрыл «Калькулятор» →
  посчитал → закрыл expander → пошёл к рекомендациям внизу.
- **Mini-компоненты в `frontend/src/components/redistribution/`** —
  чистая факторизация, `LocalizationMini` фиксирует период «last 7d»
  (без DateRangePicker), показывает hero KPI + top-5 worst SKU + ссылку
  «→ полная версия на /localization». `SupplyCalculatorMini` /
  `TransitCalculatorMini` — то же.
- **`/localization` standalone остаётся** для manager-scope (manager не
  имеет доступа к /redistribution, поэтому expander для него закрыт по
  RBAC).

**Боль:**

- **Workflow не оптимален.** Сценарий «Локализация → Поставка → Транзит»
  предполагает движение сверху вниз. Все 3 expander'а свёрнуты по
  default'у — РОП должен **раскрыть каждый** руками. Если эта страница
  становится «командным центром» — стоит first-open default = open
  для Локализации (она entry point'ом).
- **Mini = не full.** В LocalizationMini период — фиксированный 7d,
  без DateRangePicker. РОП за полный месяц не посмотрит — нужно
  переходить на standalone `/localization`. Это OK как design choice
  («expander = quick-look»), но без CTA «полная версия →» в подвале
  expander'а можно потеряться.
- **Дублирование квот.** Expander LocalizationMini + standalone
  /localization дают РОПу два пути. Не путаница, но «куда лучше идти»
  не очевидно — нужен hint «начни с expander'ов; для глубокого анализа —
  full pages» в шапке `/redistribution`.
- **Если LK не подключена** — generateMut.mutate() не работает.
  Calculators в expander'ах работают (они не требуют LK). Хорошо.
- **Expander mini не помечает RBAC.** Если bookkeeper зайдёт на
  /redistribution (он не должен, но...) — увидит expander'ы. Backend
  guard есть, но визуально не отделено «это director-only».

**Что предложить:**

- **TASK: defaultOpen=true для Локализация expander'а** (первый шаг
  workflow'а, sane default).
- **TASK: «↗ Полная версия на /localization» CTA в подвале expander'ов.**
  Минимизирует «куда лучше идти» путаницу.
- **TASK: hint в шапке `/redistribution`** — «Quick-view виджеты ниже.
  Для глубокого анализа — полные страницы в меню».

### Notifications в РОП whitelist (TASK-LEAD-091)

**Что работает:**

- **`PROFILE_WHITELIST.rop` теперь содержит `/notifications`** —
  Layout.tsx:176. Inline-комментарий: «Без notifications РОП не настроит
  TG-алерты». Корректно.
- **Покрытие 17 пунктов в РОП profile** — Dashboard, P&L, WeeklyReport,
  Managers KPI, Units, ABC, Plans, Supply, Redistribution, Localization,
  Calculators, Funnel, Ads, **Notifications**. Daily workflow покрыт.

**Боль:** нет. Фича закрыта.

**Что предложить:** ничего.

### TG-share manager warn (TASK-LEAD-089) + Dialog (TASK-LEAD-090)

**Что работает:**

- **Native `confirm()` заменён на `<Dialog>`** — все 4 случая (share-self,
  share-directors, pdf-fallback-no-tg, pdf-fallback-no-directors)
  используют один Dialog-компонент. Mobile UX улучшен.
- **Warn-подпись в share-self dialog'е** для manager'а:
  ```
  ⚠ Сейчас отчёт отправится в твою личку (твой users.tg_chat_id).
  Чтобы передать РОПу — попроси добавить вашего РОПа в общий чат с
  ботом, или используй PDF-кнопку рядом.
  ```
  bg-warn-subtle, не пугающее. Объясняет «куда полетит» + «как сделать
  правильно». Меньше confusing'а раунда 13.
- **PDF-fallback dialog'и** — отдельные case'ы для «нет привязки» vs
  «нет директоров с привязкой». Объяснение «Привязать чат: /settings →
  Мой Telegram-чат».

**Боль:**

- **Warn явно объясняет проблему, но не решает.** РОП не в чате — это
  системная проблема (нет `boss_id`). Manager получает workaround
  «попроси РОПа в чат». OK как promo-полу-фикс, но stratify это
  не лечит. Это в roadmap (LEAD-089 описание).
- **Warn только в share-self dialog'е.** Если manager попадает в
  share-directors flow (не должен — но if RBAC бага) — warn'а нет.
  Defensive — не нужно, но flag.
- **«Используй PDF-кнопку рядом»** — на скриншоте PDF-кнопка перед
  TG-кнопкой. Если user уже кликнул «📨 в Telegram» — он не знает,
  что PDF где-то рядом (это кнопка справа). Можно добавить inline
  кнопку «↓ Скачать PDF вместо» прямо в Dialog.

**Что предложить:**

- **TASK: inline «↓ Скачать PDF вместо» в share-self dialog'е** —
  меньше movement.
- **HYP / TASK: User.boss_id для manager → his ROP delivery** —
  стратегический; нужен product call.

---

## --as MANAGER

«Я менеджер бренда X. Открываю SellerFriends...»

### Per-brand comment (HYP-004)

**Что работает:**

- **Default brand = первый мой бренд** — `defaultBrand =
  availableBrands[0]`. Открыл /weekly-report → comment section
  показывает мой бренд (не «Общий», где я read-only). Меньше
  trial-and-error для нового пользователя.
- **Placeholder персонализирован:** «Что произошло на бренде «X» за
  неделю?». Знаю что писать.
- **Read-only для overall scope** объяснён в placeholder'е и
  disabled-button title'е. Не «silent fail» как в раунде 13.
- **Видны другие комментарии** — РОП написал в overall + коллеги-
  менеджеры по другим брендам. Менеджер видит контекст команды.
- **Save → invalidate `commentsAllQ`** — после моего сохранения список
  «Другие комментарии» актуальный.

**Боль:**

- **Brand-selector не focused.** Менеджер открывает страницу — courseur
  в выпадающем списке (Scope) не выделен, нужно scroll'ить чтобы
  увидеть default. Можно auto-focus textarea (минимизирует поиск).
- **`isReadOnlyComment` = `manager && selectedBrand === null`** —
  manager может **выбрать другой scope** через selector. У него в
  dropdown'е будут только его brand'ы (`availableBrands = user.brands`
  для manager'а). Overall (null) тоже виден — он там read-only. Но если
  у manager'а 3 бренда — он выбирает scope, у каждого бренда свой
  textarea. ОК как UX — multi-brand manager редкость.
- **«Сохранить» disabled пока `!dirty`** — РОП может думать «почему
  кнопка серая». title объясняет «Нет изменений», но не intuitive.

**Что предложить:**

- **TASK: auto-focus textarea на open для manager'а** — quick-win.
- (Минор: feedback раунда 13 закрыт по сути.)

### TG-share manager warn

**Что работает:**

- **Менеджер кликает «📨 в Telegram» → Dialog «Отправить отчёт в
  Telegram? — отправится в твою личку».** Объяснение чётко: куда
  полетит и как сделать «как ожидалось» (РОП в чат / PDF).
- **Если нет tg_chat_id** → отдельный Dialog «не привязан → скачать
  PDF?» с ссылкой на /settings.

**Боль:**

- **Менеджер всё равно не получит «передать РОПу одним кликом».** Warn
  объясняет почему, но не решает. Это **architectural gap** (нужен
  boss_id), не UI-bug. Раздел "что отбросить" для round 14.
- **Если у manager'а tg_chat_id привязан, но в чате он один (нет
  РОПа)** — отчёт улетит ему же в личку. Backend (broadcast логика)
  отправит на `tg_chat_id` user'а; кто в этом чате присутствует — WB-
  агностично. Это **honest** behavior.

**Что предложить:**

- (См. ROP-секцию выше: inline «↓ Скачать PDF вместо» в Dialog'е.)

### Scoreboard pre-aggregation

**Что работает:** manager не видит scoreboard (`canSeeScoreboard =
director || head_of_sales`). Performance улучшение его не затронуло — ОК.

### ManagerSummary page

**Что работает:**

- **RBAC frontend:** manager на `/manager-summary` → «Доступ только для
  director / head_of_sales». Понятно, не падает.
- **Backend защита:** даже если manager обойдёт frontend и вызовет API
  `?manager_id=OTHER_USER` — `by-manager` endpoint 403 (require_director_or_head),
  `top-skus` отфильтрует через brand-scope, comments вернёт только
  своё. **Defence-in-depth работает.**

**Боль:**

- **Manager может попытаться открыть `?manager_id=SELF`** — увидит
  тот же баннер «доступ запрещён». Можно add: если `manager_id ==
  current_user.id` → редирект на `/weekly-report` (свой отчёт).

**Что предложить:**

- **TASK (XS): если `manager_id == current_user.id` → редирект на
  /weekly-report.** Прозрачно для случайного перехода.

---

## Coverage gaps

### Round 13 — что не дошло до production

**Большинство (LEAD-080..097 + HYP-001/003/004/005) реализовано в
v0.34.1 – v0.38.0.** Открытые из раунда 13:

- **TASK-LEAD-079** — Per-SKU bookmarking на /units — статус не
  проверял в этом раунде (вне scope'а Z2).
- **TASK-LEAD-092** — Auto-suggest boostPct из истории — поглощён в
  Инициативу «PromoCalculator — прогноз спроса под акцию».

### Stale статусы в `agents/tasks-lead.md`

**Все из v0.35-0.38 (10+ задач) помечены «Открыта», хотя
закоммичены и в проде:**

- TASK-LEAD-086 (manager → drill) — v0.35.0
- TASK-LEAD-087 (scoreboard pre-aggregation) — v0.38.0
- TASK-LEAD-088 (per-SKU localization rec) — v0.38.0
- TASK-LEAD-089 (TG-share warn) — v0.38.0
- TASK-LEAD-090 (Dialog vs confirm()) — v0.38.0
- TASK-LEAD-091 (notifications в РОП) — v0.38.0
- TASK-LEAD-093 (TransitCalculator wizard) — частично в v0.38.0
- TASK-LEAD-094 (Transit stale-tariff banner) — v0.38.0
- TASK-LEAD-095 (DocPage whitelist) — v0.38.0
- TASK-LEAD-096 (ReconciliationHero split) — v0.38.0
- TASK-LEAD-097 (WeekProfit «vs 4-week avg») — v0.38.0

Lead должен запустить chore-pass на «Выполнено». Это **повторяется
третий раунд подряд** — нужен process-fix, например auto-close в
release-скрипте по grep'у task ID в commit message.

### USER_GUIDE.md — gap'ы

USER_GUIDE.md за раунд 13 не обновлён для:

- **HYP-005 ManagerSummary** — нет страницы / описания
- **HYP-004 per-brand comment** — упоминается только серверный
  комментарий из LEAD-062, без per-brand расширения
- **LEAD-087 scoreboard pre-aggregation** — невидим юзеру, но
  performance note в FAQ был бы полезен
- **LEAD-088 per-SKU localization rec + tooltip * fallback** —
  пользователю не объяснено что значит `*`
- **LEAD-091 /notifications в РОП profile** — мелочь, но profile
  documentation давно не обновлялось
- **LEAD-089 TG-share warn** — упоминание warn'а для manager'а полезно
  в onboarding

### Регрессии

1. **Scoreboard `source` field неотрисован в UI** — endpoint возвращает
   `"scoreboard"`/`"live"`, но фронт игнорирует. Не баг (cosmetic), но
   debug-trail отсутствует.
2. **ManagerSummary alerts — system-wide без brand-filter.** РОП может
   спутать «алерты по этому менеджеру» vs «алерты всего tenant'а».
   Документировано в коде, не в UI.
3. **Backend RBAC `?manager_id=X` нет.** Защита через RBAC отдельных
   endpoint'ов + frontend guard — defence in depth работает, но
   formal guard был бы чище.
4. **Per-brand комментарии «прячутся» под текстарой.** РОП может не
   заметить N комментариев менеджеров в чейн-overlapping раскладке.
5. **Expander'ы в /redistribution закрыты по default.** РОП должен
   раскрывать 3 секции — если это «командный центр», sane default = open
   first one.
6. **Stale-check для scoreboard pre-aggregation нет.** Если Celery
   упал, endpoint молча отдаёт старые цифры без warn'а.
7. **Per-SKU localization rec с малым sample size** может давать noise
   (top-кластер 1 из 5 заказов = 20% доля = слабый сигнал).

### Дублирование

- **scoreboard ведёт на /manager-summary, но `?brand=...` в /weekly-report
  тоже работает** (backward-compat через LEAD-086, для прямых
  bookmarks). Не путает — это **разные сценарии**: `?brand=...` —
  «фокусированный отчёт» (KPI остаются по полному скоупу, фильтр
  только Top-SKU и recommendations), `/manager-summary` — «карточка
  менеджера» (KPI per-manager, alerts, comments). Документировано в
  баннере «фильтр применён к Top-5 SKU и рекомендациям; KPI остаются
  по полному скоупу».

---

## Итог

### Кандидаты на TASK (Lead/PM решит куда положить)

#### Performance / Architecture
- **TASK: scoreboard stale-check (updated_at > 26h → live + warn)** — защита
  от долгого простоя Celery.
- **TASK: dedicated `/manager-summary` endpoint** — один запрос вместо
  N+1 (scoreboard + top-revenue + top-margin + recs + alerts + comments).
- **TASK: backend RBAC guard на `?manager_id=X`** — defence-in-depth,
  даже если frontend не пустит.
- **TASK: показать `source` + `updated_at` scoreboard'а в UI** —
  badge + tooltip.

#### Localization
- **TASK: per-SKU rec min-confidence threshold** (top-кластер ≥ 60% доли).
- **TASK: явный значок per-SKU (★) vs fallback (☆)** — заметнее
  на mobile.
- **TASK: empty case tooltip «недостаточно данных»** для recommendation.

#### Comment workflow
- **TASK: счётчик/превью other-comments в заголовке секции
  Comment** — «(3 от команды)» кликабельно.
- **TASK: brand-selector persist в localStorage** —
  `weekly-report.comment-scope.v1`.
- **TASK: «Ответить» под комментарием коллеги** — auto-switch scope.
- **TASK: auto-focus textarea на open для manager'а**.

#### Redistribution expanders
- **TASK: defaultOpen=true для Локализация expander'а** (entry point).
- **TASK: «↗ Полная версия на /localization» CTA в подвале expander'ов**.
- **TASK: hint в шапке /redistribution** — «quick-view ниже; для
  глубокого — full pages».

#### TG-share
- **TASK: inline «↓ Скачать PDF вместо» в share-self dialog'е**.
- **TASK: ManagerSummary alerts с brand-filter (если alert-движок brand-aware)**.

#### ManagerSummary
- **TASK: «← weekly-report с brand-фильтром этого менеджера»** в
  ManagerSummary actions row.
- **TASK (XS): manager_id == self → редирект на /weekly-report**.

#### Process / Docs
- **CHORE: закрыть stale статусы tasks-lead.md** — LEAD-086/087/088/089/090/
  091/093/094/095/096/097 → Выполнено. Process-fix: auto-close скрипт.
- **TASK: USER_GUIDE.md update** для HYP-004/005, LEAD-087/088/091 + per-SKU
  fallback `*` объяснение.

### Кандидаты на HYP (стратег пусть проверит)

- **HYP: User.boss_id для «manager → his ROP delivery»** — фундаментальное
  решение для TG-share manager confusion. Затрагивает все broadcast'ы.
- **HYP: ManagerSummary становится «карточкой менеджера на ревью»** —
  расширить до 1-on-1 prep page (история комментариев, тренды, текущие
  заявки на правку плана и т.д.).

### BUG-кандидаты

- (Нет hard-bug'ов в этом раунде. RBAC `?manager_id=X` — UX-debt /
  defence-in-depth gap, не критичный.)

### Что reaffirm'ить — фичи работают как ожидалось

- **Scoreboard pre-aggregation** — архитектура чистая, fallback на live-
  compute грамотный, schedule sane (04:30 МСК после report_detail).
  Latency win существенный.
- **ManagerSummary page** — drill-down закрывает gap «РОП увидел Петров
  просел — где детали?». Composition из существующих endpoint'ов
  работает, RBAC через каждый endpoint = defence in depth.
- **Per-brand comment** — менеджер пишет в свой бренд (default),
  read-only для overall (явно объяснено), РОП видит overall + per-brand
  списком. Logical extension LEAD-062.
- **Localization per-SKU recommendation** — fallback на tenant-wide
  c `*` пометкой = honest UX. РОП понимает где «лучшая логика», где
  fallback.
- **Redistribution expanders** — workflow «локализация → калькулятор
  поставки → калькулятор транзита» в одной странице покрыт. Standalone-
  страницы back-compat'ятся.
- **Layout /notifications в РОП whitelist** — корректно реализовано.
- **TG-share Dialog'и + warn для manager'а** — заменили `confirm()`,
  Mobile UX улучшился, manager confusion смягчён (не решён, но
  объяснён).

### Что отбросить

- **Backend brand-filter для alerts движка в ManagerSummary** —
  alerts система-wide исторически (стокаут не привязан к brand'у в
  алертах), переделка большая. Документировать в UI как «system-wide
  алерты» и оставить.
- **Brand-selector default = «общий» для РОПа** — change на «бренд с
  последним комментарием» = умно, но фичу-defending без сильного
  signal'а. Оставить «общий».
- **User.boss_id для manager → ROP delivery** — стратегический, не
  отбрасывать, но и не делать без product-call (см. HYP выше).
