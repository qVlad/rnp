# Задачи Developer — РНП

**Дата открытия файла:** 2026-05-17

> Перед каждой задачей — `agents/RULES.md`, `agents/developer.md`, релевантные секции `CLAUDE.md` (всегда) + `WB_API_REFERENCE.md` (если WB-интеграция).
> Открытые баги (`agents/bugs-developer.md`) **закрываются до** новой задачи.

---

## Backlog

> Lead заполняет этот файл из `ROADMAP.md`, запросов пользователя, найденных багов QA.

### Источник: ревью c8f6609 от 2026-05-20 (QA + РОП + Manager + Owner)

Дешёвые правки (локализация, manager-баннер, копия плана) уже сделаны в коммите
после ревью. Здесь — то что требует Sprint'а.

---

### TASK-DEV-001: Менеджер-центричный view (KPI каждого менеджера за день)

- **Исполнитель:** Developer
- **Приоритет:** P0
- **Оценка:** 1-2 дня
- **Источник:** ревью c8f6609 — РОП (главная боль №1), Owner (drill-down по бренду/менеджеру)
- **Описание:** Новая страница `/managers-kpi` (доступна director/head). Таблица:
  строки = менеджеры (User с role=manager и активными brand_assignments),
  колонки = план/факт по выручке, по марже, по ДРР, статус выполнения %.
  При клике на менеджера — drill-down: его бренды, его планы. Это
  закрывает главную боль РОПа из ревью: «нет менеджер-центричного view».
- **Критерии готовности:**
  - [x] Backend: `GET /api/managers-kpi?year=YYYY&month=MM` — агрегат по
        `BrandAssignment.user_id` → бренды → compute_dashboard per-manager
  - [x] Backend: только director_or_head; tenant-scoped
  - [x] Frontend: страница `ManagersKpi.tsx` с таблицей и брендами inline
  - [x] Layout: пункт в группе «Контроль», `directorOrHead: true`
  - [x] Smoke: 7cf4461 на проде, endpoint отдаёт 401 без cookie (=auth работает)
- **Зависимости:** нет
- **Статус:** ✅ Закрыта 2026-05-20 (backend `api/managers_kpi.py`, фронт `pages/ManagersKpi.tsx`, селектор Год+Месяц+Режим, цветная маржа). Drill-down popover (план-факт) перенесён в TASK-DEV-007.

---

### TASK-DEV-002: Drill-down по брендам в P&L (матрица бренд × месяц × маржа)

- **Исполнитель:** Developer
- **Приоритет:** P1
- **Оценка:** 1 день
- **Источник:** ревью c8f6609 — РОП («не вижу вклад бренда в маржу»), Owner
- **Описание:** На `/pnl` при scope=company добавить таб «Разбивка по
  брендам». Матрица: строки = бренды, колонки = последние 6 месяцев,
  в ячейках — маржа% и ₽. Highlight красным где маржа < 15%.
- **Критерии готовности:**
  - [x] Backend: `GET /api/pnl/by-brand?months=6` → массив `{brand,
        monthly: [{period, revenue, margin_pct, margin_rub}]}`
  - [x] Frontend: новый таб в `PnL.tsx`, heatmap-стиль раскраска
  - [x] Manager видит только свои бренды (current_brands_filter)
- **Зависимости:** нет
- **Статус:** ✅ Закрыта 2026-05-20 (backend `api/pnl.py:get_pnl_by_brand`, фронт `components/PnLByBrandView.tsx`, селектор глубины 3/6/12 мес, красным <5% / жёлтым 5-15% / зелёным ≥15%)

---

### TASK-DEV-003: Глобальный 403-handler + disabled-кнопки CUD с tooltip

- **Исполнитель:** Developer
- **Приоритет:** P1
- **Оценка:** 4-6ч
- **Источник:** ревью c8f6609 — Manager (сырое 403 при попытке открыть CUD), QA
- **Описание:** В `api/client.ts:request` ловим 403 → показываем toast
  «У вас нет прав для этого действия. Обратитесь к директору». Дополнительно
  на страницах Plans/Brands/Settings: кнопки create/edit/delete для
  manager рендерятся `disabled` с тултипом «Доступно директору и РОПу»
  (сейчас они просто не показываются — но если показываются, то ронят 403
  без объяснения).
- **Критерии готовности:**
  - [x] Toast-компонент: новый `components/ToastHost.tsx` (без зависимостей,
        слушает `CustomEvent('rnp:forbidden')`)
  - [x] 403 в `api/client.ts` dispatch'ит событие, throw продолжает работать
        (caller получит Error как обычно — UI не сваливается)
  - [x] Логика 401 не тронута (отдельный if + setOn401Handler как раньше)
  - [x] Smoke: 8 коммит на проде, в DevTools `window.dispatchEvent(new CustomEvent('rnp:forbidden', {detail: {path: '/api/test'}}))` показывает toast
- **Зависимости:** нет
- **Статус:** ✅ Закрыта 2026-05-20. Disabled-кнопки CUD на Plans/Brands/Settings
  не делал отдельно: для manager эти кнопки уже скрыты через `canEdit` flag
  в каждой странице (UX-решение лучше disabled+tooltip — менеджер не видит
  чего не может). Toast нужен только для крайних случаев (прямой URL,
  legacy-кнопка которая забыла role-check).

---

### TASK-DEV-004: Фильтр «маржа < N%» + сохраняемые пресеты в Unit-Plan

- **Исполнитель:** Developer
- **Приоритет:** P2
- **Оценка:** 4-6ч
- **Источник:** ревью c8f6609 — РОП («60 колонок, не вижу проблемные SKU
  быстро»)
- **Описание:** В `UnitPlan.tsx` добавить блок фильтров над таблицей:
  - «Маржа меньше %» (input)
  - «ROI меньше %» (input)
  - «Дней до стокаута меньше» (input)
  - Highlight rows которые попадают под фильтр (красная полоска слева).
  - Сохранить пресет фильтров через `ViewPresetsBar scope="unit-plan"`.
- **Критерии готовности:**
  - [x] Фильтрация работает client-side (без нового API)
  - [x] Подсветка рядов работает через существующий marginColor()
  - [x] Состояние сохраняется в `localStorage('unit-plan.quick-filters.v1')`
- **Зависимости:** нет
- **Статус:** ✅ Закрыта 2026-05-20 (3 input'а в `UnitPlan.tsx` Filters bar:
  «Маржа <», «ROI <», «Дней до стокаута <», persist в localStorage, кнопка
  «✕ Сбросить» когда хотя бы один активен). ViewPresetsBar для unit-plan
  не сделан — простой localStorage purpose-достаточен для первой итерации.

---

### TASK-DEV-005: Экспорт рекомендаций закупок в XLSX (для 1С / логистики)

- **Исполнитель:** Developer
- **Приоритет:** P2
- **Оценка:** 4ч
- **Источник:** ревью c8f6609 — РОП («руками копирую цифры из Supply в 1С»)
- **Описание:** На странице `Supply.tsx` кнопка «📥 Экспорт XLSX» — выгружает
  рекомендации (nm_id, артикул, бренд, склад, к отгрузке, текущий остаток,
  дней до стокаута). Формат столбцов — согласовать с РОПом, ориентир —
  то что 1С принимает на импорт заказа поставщику.
- **Критерии готовности:**
  - [x] Frontend генерация Blob (без npm-зависимостей) → download
  - [x] Колонки: nm_id, vendor_code, urgency, остаток, в пути к клиенту,
        в пути возврат, скорость, дней до 0, к отгрузке
  - [x] UTF-8 BOM + `;`-separator (Excel-friendly), имя файла с датой
- **Зависимости:** нет
- **Статус:** ✅ Закрыта 2026-05-20 как CSV (Excel открывает напрямую,
  без npm xlsx). Кнопка «📥 Экспорт CSV (N)» в шапке таблицы рекомендаций
  в `Supply.tsx`, выгружает видимые SKU (с учётом фильтра urgency).

---

### TASK-DEV-006: AlertsBar — история прочитанных за день

- **Исполнитель:** Developer
- **Приоритет:** P2
- **Оценка:** 3-4ч
- **Источник:** ревью c8f6609 — РОП («алерт исчез — забыл»)
- **Описание:** В `AlertsBar` добавить mark-as-read через localStorage
  (хеш алерта → дата ack). Под основным баром — collapsed-блок «Прочитанные
  сегодня (N)» который раскрывается. Не показывать ack-нутые алерты в
  основном списке.
- **Критерии готовности:**
  - [x] Ack хранится в `localStorage["alerts.dismissed.v2"]` (object code→date)
  - [x] Lazy migration v1 (array) → v2 (object) при первом чтении
  - [x] Кнопка close → «Пометить прочитанным» + раздел «Прочитанные сегодня»
  - [x] Кнопка «↺ Вернуть» в collapsed-блоке
- **Зависимости:** нет
- **Статус:** ✅ Закрыта 2026-05-20 (`AlertsBar.tsx` теперь dismiss с
  ack-date, сегодняшние в collapsed «Прочитанные сегодня (N)», старые
  забываются автоматически на следующий день).

---

### TASK-DEV-007: Карточка «Ваши бренды» / «Ваши планы» на Dashboard для manager

- **Исполнитель:** Developer
- **Приоритет:** P2
- **Оценка:** 2-3ч
- **Источник:** ревью c8f6609 — Manager («не понимаю откуда у меня данные»)
- **Описание:** Дешёвый баннер «вы видите данные по брендам X, Y» уже
  добавлен в Layout. Здесь — расширение: на Dashboard для manager —
  карточка «Ваши планы» с прогрессом по каждому SKU/группе из его scope.
- **Критерии готовности:**
  - [x] Компонент `ManagerPlanProgressCard` рендерится только для
        `user.role === "manager"` (`Dashboard.tsx:128`)
  - [x] Использует `api.planFact(year, month)` — backend сам отфильтровывает
        планы по brand_assignments менеджера, store-scope drop'ятся
  - [x] Цветная полоска прогресса: ≥90% зелёная / 60-89% жёлтая / <60%
        красная (`pctColor` helper), топ-5 планов по `sales_revenue.plan` DESC,
        empty-state ведёт на `/plans`
- **Зависимости:** TASK-DEV-001 (managers-kpi backend пригодится)
- **Статус:** ✅ Закрыта 2026-05-21 (`components/ManagerPlanProgressCard.tsx`, подключён в `Dashboard.tsx`)

---

### Источник: ревью персон Owner/Manager/РОП от 2026-05-20 (после TASK-DEV-001..007)

После закрытия первой волны три персоны прошлись по обновлённому функционалу.
Общие темы: тренды/Δ-к-периоду везде в абсолютах; drill-down с managers-kpi
отсутствует; нет связки бренд↔менеджер в P&L-heatmap; localStorage не вытягивает
кросс-устройство; нужен сторителлинг «что нового», а не сырые KPI.

---

### TASK-DEV-008: Owner cockpit — отдельный вид на `/`

- **Исполнитель:** Developer
- **Приоритет:** P1
- **Оценка:** 1-2 дня
- **Источник:** ревью Owner — «захожу раз в неделю, мне нужен plot-twist»
- **Описание:** На `/` для роли `director` (которая совмещает функции owner'а
  по факту) — toggle «вид Owner» поверх стандартного дашборда. Включает
  4 виджета: recon-Δ за 4 недели (sparkline), план месяца компании (с %
  выполнения и % прошедшего срока), топ-3 / bottom-3 бренда по марже,
  топ-3 / bottom-3 менеджера по выручке. Cтейт toggle в localStorage.
- **Критерии готовности:**
  - [x] Компонент `OwnerCockpitView.tsx` — 4 виджета (recon-spark, план месяца,
        top/bottom бренды, top/bottom менеджеры), 4 параллельных useQuery к
        существующим endpoint'ам (`pnlReconciliation`, `pnlByBrand`,
        `managersKpi`, `planFact`) — без нового backend
  - [x] Toggle persist в `localStorage["dashboard.owner-view.v1"]`
  - [x] Видимость: `user?.role === "director"` — head_of_sales и manager
        видят дефолтный дашборд
  - [x] Каждый виджет обёрнут в `<Link>` — клик ведёт на полный экран
- **Зависимости:** TASK-DEV-001, TASK-DEV-002 (backend для виджетов)
- **Статус:** ✅ Закрыта 2026-05-20. Известный архитектурный долг —
  TASK-LEAD-023 (Redis-кеш managers-kpi N×6) — при открытии cockpit'а
  endpoint вызывается ещё раз дополнительно к /managers-kpi page. Кеш
  сделает 0 секунд из 5-30.

---

### TASK-DEV-009: Δ к прошлому месяцу + sparkline + sort в `/managers-kpi`

- **Исполнитель:** Developer
- **Приоритет:** P1
- **Оценка:** 1 день
- **Источник:** ревью Owner + РОП — «вижу абсолюты, не знаю кто просел»
- **Описание:** Расширить `api/managers_kpi.py` чтобы вместе с текущим
  месяцем отдавал сравнение с предыдущим: Δ revenue %, Δ margin pp,
  массив `monthly_revenue[]` за 6 мес для sparkline. На фронте —
  доп. колонки «Δ vs прошлый» (с цветом) и sparkline-cell. Header-sort
  по любой колонке (по умолчанию — выручка DESC).
- **Критерии готовности:**
  - [x] Backend: возвращает `delta_revenue_pct` (может быть `null` если prev=0),
        `delta_margin_pp`, `sparkline_revenue: number[6]` (oldest first),
        `prev_revenue_net_rub`, `prev_margin_pct`. Для прошлых месяцев
        принудительно `mode='final'` — иначе preliminary-шум давал бы
        ложную «просадку» 5-15%.
  - [x] Frontend: 2 новые колонки «Δ м/м» и «6 мес» + sortable headers
        (клик по `<th>` сортирует, persist в `localStorage.managers-kpi.sort.v1`)
  - [x] Δ-цвета: >+3% зелёный (text-success), <−3% красный (text-red-400),
        |Δ|<3% серый (text-muted) — шум
  - [x] Sparkline через recharts `<LineChart width=80 height=24>` без осей,
        цвет линии = цвет Δ (currentColor)
  - [x] no_brands строки всегда внизу таблицы (независимо от сортировки)
- **Зависимости:** TASK-DEV-001
- **Статус:** ✅ Закрыта 2026-05-20 (backend `api/managers_kpi.py:_month_revenue_margin`
  + 6-point sparkline loop, фронт `pages/ManagersKpi.tsx` — sortable headers
  с localStorage-persist, Δ-цвет порог 3%, recharts sparkline, no_brands в хвост)

---

### TASK-DEV-010: Произвольный период в `PnLByBrandView` (DateRangePicker)

- **Исполнитель:** Developer
- **Приоритет:** P2
- **Оценка:** 4ч
- **Источник:** ревью Owner — «нужны квартальные срезы и YoY»
- **Описание:** Заменить пресеты 3/6/12 мес на `<DateRangePicker>`
  (как в Dashboard). Backend `/api/pnl/by-brand` уже принимает диапазон
  через `months` но не from/to — добавить опциональные `date_from`/`date_to`.
- **Критерии готовности:**
  - [x] Backend: `date_from`/`date_to` опциональны, если оба заданы —
        перекрывают `months`. Snap к границам месяца (1-е → последний день)
        так как build_pnl с granularity="month" режет month-aligned.
  - [x] Frontend: `DateRangePicker` сверху + 4 пресета («Этот квартал /
        Прошлый квартал / YTD / 12 мес.») рядом
  - [x] Не нарушает существующее поведение без параметров — `months` остаётся
        дефолтом 6, query попадает только если `from && to` оба заданы.
        Persist выбора в `localStorage['pnl-by-brand.range.v1']`.
- **Зависимости:** TASK-DEV-002
- **Статус:** ✅ Выполнено 2026-05-21 (`api/pnl.py:get_pnl_by_brand` принимает
  date_from/date_to, snap'ит к границам месяца; `components/PnLByBrandView.tsx`
  переписан на DateRangePicker + 4 пресета, `api/client.ts:pnlByBrand`
  поддерживает 3 параметра)

---

### TASK-DEV-023: Recon-алерт в `AlertsBar` (auto-warning при Δ>1%) — *перенумерована с 011*

> **Конфликт нумерации:** изначально была TASK-DEV-011. Параллельная сессия в
> коммите `49e8c16 feat(sprint+1)` использовала тот же номер `TASK-DEV-011`
> для другой фичи (custom-метрики через формулы). Чтобы избежать неоднозначности
> в истории, перенумерована сюда — номер 011 остаётся за custom-метриками.

- **Исполнитель:** Developer
- **Приоритет:** P1
- **Оценка:** 4-6ч
- **Источник:** ревью Owner — «узнаю о расхождении только зайдя в /pnl-reconciliation»
- **Описание:** В alert-evaluation добавить новый тип `recon_delta`:
  если на любой из последних 4 closed-недель Δ revenue_gross > 1% или
  Δ margin > 2pp — генерируем warning со ссылкой на `/pnl-reconciliation`.
- **Критерии готовности:**
  - [x] Backend: правило в `services/anomaly.py` (блок `# 6) Reconciliation drift`),
        переиспользует `build_reconciliation(weeks_back=4, diff_threshold_pct=1.0)`
  - [x] Alert содержит `link: "/pnl-reconciliation"` (без `?week=` — страница уже
        показывает все 4 недели; добавление anchor-scroll — follow-up)
  - [x] Только для `director_or_head` — гейт `if brands is None` (manager
        работает в brand-scope, у него `brands=set(...)`, у директора/head `None`)
  - [x] Severity: `warning` при |Δ|>1% / `danger` при |Δ|>3% (фронтенд маппит
        critical→danger). Один суммирующий алерт, не спамим по неделе.
- **Зависимости:** нет
- **Статус:** ✅ Выполнено 2026-05-20 (backend `services/anomaly.py:# 6) Reconciliation drift`,
  фронт `AlertsBar.tsx` поддерживает optional `link` поле через `react-router-dom Link`,
  feat → v0.7.0)
- **Не сделано (вне scope, follow-up):** Δ margin pp — в reconciliation нет «маржи»
  в side-by-side виде (только revenue_gross_pct и payout_to_gross_pct), поэтому
  взяли только revenue_gross в качестве primary recon-метрики. Если разъедутся
  downstream P&L цифры — Δ revenue_gross их «потянет за собой».

---

### TASK-DEV-012: «Что изменилось с прошлой недели» feed на дашборде

- **Исполнитель:** Developer + Analytic
- **Приоритет:** P2
- **Оценка:** 1-2 дня
- **Источник:** ревью Owner + Manager — «нужен сторителлинг, не сырые KPI»
- **Описание:** Новый блок `WeeklyChangesFeed` на `/` (под TodayVsYesterdayStrip,
  3-5 буллетов сгенерированных бэкендом). Endpoint `/api/dashboard/weekly-changes`
  выгружает: бренды с |Δ revenue| > 15% MoM, SKU с DRR>20% впервые за месяц,
  выход в просадку плана. Manager видит только свой scope.
- **Критерии готовности:**
  - [x] Backend: `services/weekly_changes.py:build_weekly_changes` —
        3 правила (brand revenue ±15% WoW, DRR>20% впервые за месяц,
        plan_slip >15pp). Sql + numpy-free. Cap 8 items.
  - [x] Каждый item: `{kind, severity, text, link?}` — link на /pnl?brands=…,
        /units?search={nm_id}, /plans
  - [x] Skeleton-load (5 строк) пока считается — `WeeklyChangesFeed.tsx`
  - [x] Кешируется в Redis на 1ч (`weekly_changes:{tenant_id}:{scope}`,
        scope = sha1(sorted brands)[:12] или "all" для director)
- **Зависимости:** нет
- **Статус:** ✅ Выполнено 2026-05-21 (`services/weekly_changes.py`,
  `api/dashboard.py:get_weekly_changes`, `components/WeeklyChangesFeed.tsx`,
  встроен в `Dashboard.tsx` после `TodayVsYesterdayStrip`).
  Follow-up: точный JOIN product_group_assignments для plan_slip с
  group-scope планами (сейчас огрублено — суммирует fact всех видимых SKU).

---

### TASK-DEV-013: Фильтр по бренду в `/supply` и `/units`

- **Исполнитель:** Developer
- **Приоритет:** P1
- **Оценка:** 3-4ч
- **Источник:** ревью Manager — «два моих бренда перемешаны»
- **Описание:** В обеих страницах сверху добавить tabs «Все / Бренд A / Бренд Б».
  Tabs строятся из uniq brands в текущих данных (или из brand_assignments
  для manager'а). Persist выбранного таба в localStorage.
- **Критерии готовности:**
  - [x] `Supply.tsx`: tabs (chip-стиль) + client-side фильтр массива items
  - [x] `Units.tsx`: dropdown `<select>` рядом с поиском
  - [x] SKU без бренда → отдельный псевдо-таб «Без бренда» (`__no_brand__`)
        — чтобы «Все» = сумма табов и manager не путался
  - [x] Brand-scoped summary в Supply (urgency-карточки + total_recommended_qty)
        пересчитываются client-side когда выбран бренд
  - [x] localStorage: `supply.brand-filter.v1`, `units.brand-filter.v1` +
        автоматический reset если бренд пропал из выборки
  - [x] Tabs скрыты если ≤1 бренда (нет смысла переключаться)
- **Зависимости:** нет
- **Статус:** ✅ Закрыта 2026-05-20

---

### TASK-DEV-014: Send-to-Telegram заявки на закупку из `/supply`

- **Исполнитель:** Developer
- **Приоритет:** P2
- **Оценка:** 4-6ч
- **Источник:** ревью Manager — «хочу отправить заявку директору не звоня»
- **Описание:** На `/supply` рядом с CSV-кнопкой — «📨 Отправить директору».
  Backend `POST /api/supply/send-recommendations` собирает recommendation-snapshot,
  форматирует Markdown-таблицу и шлёт через TG bot всем `director` тенанта
  + author manager'у как preview. Audit log событие.
- **Критерии готовности:**
  - [x] Backend: `api/supply_send.py:send_recommendations` использует
        `integrations/telegram.send_message` и `services/forecast.build_stockout_forecast`
        (тот же источник что UI — 1:1 цифры)
  - [x] Сообщение HTML-форматированное: ФИО + role-tag + topN=12 SKU
        (urgency-emoji + остаток + дни до 0 + к отгрузке) + total
  - [x] Frontend: «📨 Отправить директору» рядом с CSV-кнопкой,
        toast-плашка с «✓ Отправлено директору» / «✗ ошибка». Auto-dismiss 6 sec.
  - [x] Rate limit: Redis `supply_send:{tenant}:{user}` TTL=3600 (1ч).
        Fail-open если Redis недоступен. На 429 — детализированный
        message «подождите N мин»
  - [x] Получатель: `AppSetting.tg_chat_id` тенанта (single-recipient MVP).
        Multi-director через user.tg_chat_id mapping — follow-up
  - [x] Audit log event `supply.send_recommendations` с items_count + total
- **Зависимости:** Telegram bot (есть)
- **Статус:** ✅ Закрыта 2026-05-21

---

### TASK-DEV-015: Все планы + sort в `ManagerPlanProgressCard`

- **Исполнитель:** Developer
- **Приоритет:** P2
- **Оценка:** 2ч
- **Источник:** ревью Manager — «топ-5 съели жирные SKU, отстающие не вижу»
- **Описание:** В карточке: переключатель «топ-5 / все», sort-by toggle
  («сумма плана / % выполнения ASC»). Default — sort по completion_pct ASC
  (отстающие сверху) чтобы первое что менеджер видит — это где он проседает.
- **Критерии готовности:**
  - [x] Toggle persist в localStorage (`manager-plans.card.v1` =
        `{sort, scope}`)
  - [x] Default — sort ASC по completion_pct (наиболее болезненные сверху).
        Null/«—» уходят в конец, чтобы не маскировать реальные просадки.
  - [x] Compact-mode авто-включается при >10 строках: тоньше прогресс-бар,
        меньше gap, текст `text-xs`
  - [x] Toggle «Топ-5 / Все (N)» в шапке карточки рядом с sort-toggle
- **Зависимости:** TASK-DEV-007
- **Статус:** ✅ Выполнено 2026-05-21 (`components/ManagerPlanProgressCard.tsx`:
  state `settings = {sort, scope}` с persist, useMemo на sort, compact при
  visible.length > 10, chip-toggle Топ-5/Все + по %↑/по плану↓)

---

### TASK-DEV-016: Dismiss empty-state карточки планов

- **Исполнитель:** Developer
- **Приоритет:** P3
- **Оценка:** 1ч
- **Источник:** ревью Manager — «раздражает каждое утро»
- **Описание:** Если backend вернул пустой items — у карточки появляется
  крестик «свернуть до конца недели». Сохраняется в localStorage с TTL до
  понедельника 00:00.
- **Критерии готовности:**
  - [x] localStorage key с expiry timestamp
        (`manager-plans.empty-dismissed.v1` = `{expiresAt}`)
  - [x] При смене недели — карточка снова показывается
        (TTL = ближайший понедельник 00:00 локально, `nextMondayMidnightTs()`)
  - [x] Crossable только при empty-state (не для содержательной карточки) —
        крестик отрисовывается только в `totalCount === 0` ветке
- **Зависимости:** TASK-DEV-007
- **Статус:** ✅ Выполнено 2026-05-21 (`ManagerPlanProgressCard.tsx`:
  state `emptyDismissedUntil`, кнопка `×` в шапке empty-state, return null
  пока `expiresAt > Date.now()`)

---

### TASK-DEV-017: Read-only `/plans` с «предложить правку» для manager

- **Исполнитель:** Developer
- **Приоритет:** P2
- **Оценка:** 4-6ч
- **Источник:** ревью Manager — «не могу даже предложить правку»
- **Описание:** Manager сейчас видит планы (read-only). Добавить кнопку
  «Предложить правку» под каждой строкой — открывает модалку «новое значение
  + комментарий», шлёт в audit log (event_type=`plan_edit_request`) +
  notification в Telegram директорам.
- **Критерии готовности:**
  - [x] Миграция **0053** `plan_edit_requests` (0049 был занят
        alert_acknowledgements). Поля: plan_id, requested_by_user_id,
        field_name, current_value snapshot, requested_value, comment,
        status (pending/accepted/rejected), resolved_by, resolved_at,
        resolution_note. Индексы по (tenant, status) + (plan_id).
  - [x] Whitelist полей: `planned_orders_qty/revenue`,
        `planned_sales_qty/revenue`, `planned_profit`, `planned_marketing_cost`.
        Store-scope планы manager не правит (403).
  - [x] UI: модалка с field-select + value + comment. Manager жмёт
        «✎ Предложить правку» рядом с каждым планом.
  - [x] Notification: TG в `AppSetting.tg_chat_id` тенанта с превью изменения
        (HTML) + ссылкой на /plans
  - [x] Director видит inbox-секцию сверху на /plans с заявками
        (pending only, refetch каждую минуту). Accept = apply + audit_log
        (`sales_plans.update` с comment `via plan_edit_request #N`) +
        invalidate plans/plan-fact. Reject = требует note (prompt).
- **Зависимости:** Telegram bot, миграция 0053
- **Статус:** ✅ Закрыта 2026-05-21

---

### TASK-DEV-018: Drill-down менеджер → его P&L из `/managers-kpi`

- **Исполнитель:** Developer
- **Приоритет:** P1
- **Оценка:** 4-6ч
- **Источник:** ревью РОП + Owner — «1-на-1 разговор = минута на ручной фильтр»
- **Описание:** На `/managers-kpi` строка менеджера кликабельна. Открывает
  модалку с его 5 KPI + топ-5 проседающих SKU + ссылка «Открыть P&L с его
  брендами» → `/pnl?brands=X,Y,Z`. PnL.tsx нужно научить читать `?brands=`
  query param.
- **Критерии готовности:**
  - [x] `ManagersKpi.tsx`: row click → `navigate("/pnl?brands=A,B&label=ФИО")`.
        Модалку не делал — прямая навигация проще и так же закрывает боль.
  - [x] `PnL.tsx`: `useSearchParams` читает `?brands=...&label=...`,
        баннер «Drill-down фильтр: ФИО · бренды: A, B [сбросить ✕]»
  - [x] Backend `/api/pnl` принимает `?brands=` query, для manager — INTERSECT
        с его brand_assignments (security). Manager не может через bookmark
        получить чужие бренды — пустой intersect отдаёт нули, не 403
  - [x] sparkline / Δ — уже в ManagersKpi после TASK-DEV-009; top-5 worst SKU
        выносим в TASK-DEV-008 (Owner cockpit) — там это виджет одного из 4
- **Зависимости:** TASK-DEV-001
- **Статус:** ✅ Закрыта 2026-05-20

---

### TASK-DEV-019: Колонка «менеджер» + фильтр «только мои» в `PnLByBrandView`

- **Исполнитель:** Developer
- **Приоритет:** P2
- **Оценка:** 3ч
- **Источник:** ревью РОП — «не вижу кто за просадку отвечает»
- **Описание:** В backend `/api/pnl/by-brand` добавить join к
  `brand_assignments → users.full_name` (если 1 менеджер на бренд — имя,
  если несколько — «N менеджеров», если нет — null). На фронте — новая
  колонка после «бренд». Toggle «Только мои подопечные» — фильтрует на
  director-уровне на manager_id из user-context (или dropdown).
- **Критерии готовности:**
  - [x] Backend: `api/pnl.py:get_pnl_by_brand` — `brand → users` JOIN через
        BrandAssignment, возвращает `managers: string[]` на каждый row
  - [x] Frontend: `PnLByBrandView.tsx` — новая колонка «Менеджер» (1 имя /
        «N человек» с tooltip / «— нет» с курсивом для unassigned)
  - [x] Filter UI: dropdown «Все / ФИО / Без назначения» в шапке
- **Зависимости:** TASK-DEV-002
- **Статус:** ✅ Закрыта 2026-05-20

---

### TASK-DEV-020: Серверный alerts_ack (cross-device)

- **Исполнитель:** Developer + Analytic
- **Приоритет:** P1
- **Оценка:** 1 день
- **Источник:** ревью РОП — «на втором устройстве всё снова красное»
- **Описание:** Новая таблица `alert_acknowledgements (id, tenant_id,
  user_id, alert_code, acknowledged_at)` (migration 0049). Endpoint
  `POST /api/alerts/ack` / `DELETE /api/alerts/ack/{code}`. Frontend
  AlertsBar мигрирует с localStorage на server state + invalidate query
  при ack. Видно «Маша подтвердила в 14:23».
- **Критерии готовности:**
  - [x] Migration 0049 + модель `AlertAcknowledgement` + UNIQUE на (tenant_id, signature)
  - [x] Endpoints `POST/DELETE /api/dashboard/alerts/ack` — tenant-scoped через `get_db_tenant_scoped`
  - [x] AlertsBar мигрирован на server state через TanStack Query mutations
  - [x] В UI отображается ФИО + время ack-нувшего при разворачивании «Прочитанные»
  - [x] Signature = sha1(code\|message)[:32] — при изменении message ack не уносится
  - [x] Старый localStorage не вычищаем — постепенно забудется
- **Зависимости:** TASK-DEV-006
- **Статус:** ✅ Закрыта 2026-05-20 (миграция 0049, `services/anomaly.py:alert_signature` + `_enrich_with_ack`, `api/dashboard.py:ack_alert/unack_alert`, `components/AlertsBar.tsx` переписан на server state)

---

### TASK-DEV-021: Supply CSV — расширить (COGS₽ / бренд / менеджер) или XLSX 2 листа

- **Исполнитель:** Developer
- **Приоритет:** P2
- **Оценка:** 4ч
- **Источник:** ревью РОП — «для согласования нужна сумма в ₽ и контакт»
- **Описание:** В supply-CSV-export добавить колонки `cogs_per_unit`,
  `cogs_total`, `brand`, `manager_name`. Альтернативно — XLSX с 2 листами
  («Заявка», «Контактные лица»). Решить с РОПом — CSV или XLSX
  (предпочтительно расширенный CSV, чтобы не тянуть xlsx-lib).
- **Критерии готовности:**
  - [x] CSV: 4 новых колонки (Бренд, Себест. ₽/шт, Себест. итого ₽, Менеджер).
        BOM сохранён, `;`-separator, кавычки для строк с разделителями
  - [x] COGS из `cogs_weighted.compute_weighted_avg_cogs` (paid_only=False —
        для планирования закупок включаем неоплаченные supplies, иначе COGS
        окажется заниженной если последняя крупная закупка ещё не оплачена)
  - [x] manager_name: если у бренда ровно 1 manager — его full_name/username,
        иначе пусто (0 или ≥2 — РОП доберёт контакт сам)
  - [x] Заголовок-строка локализована (русские заголовки колонок)
- **Зависимости:** TASK-DEV-005
- **Статус:** ✅ Выполнено 2026-05-21 (`services/forecast.py` обогащает items
  полями `cogs_per_unit`/`cogs_total`/`manager_name`; `pages/Supply.tsx:exportToCsv`
  добавляет 4 колонки в CSV)

---

### TASK-DEV-022: OR-комбинатор в quick-filters `/unit-plan`

- **Исполнитель:** Developer
- **Приоритет:** P2
- **Оценка:** 2-3ч
- **Источник:** ревью РОП — «нужно маржа<5% **ИЛИ** стокаут<7»
- **Описание:** Сейчас quick-filters AND-объединены. Добавить toggle
  «AND / OR» рядом с фильтрами. Persist в `unit-plan.quick-filters.v1`.
- **Критерии готовности:**
  - [x] Toggle И / ИЛИ (2 chip-кнопки, active = accent-bg) рядом с фильтрами
  - [x] OR-логика через `checks.some(fn => fn(r))`; AND через `checks.every(...)`
  - [x] Counter `"{Любое условие|Все условия}: подсвечено N из M SKU"`
  - [x] Default — `"and"` (persist в `unit-plan.quick-filters.v1.mode`)
- **Зависимости:** TASK-DEV-004
- **Статус:** ✅ Закрыта 2026-05-21 (`UnitPlan.tsx`: добавлен `quickFilterMode` state с persist, логика фильтрации через массив checks + .some/.every, UI И/ИЛИ chip-toggle)

---

### TASK-DEV-024: Tag-система с эмодзи-палитрой на nm_id

- **Исполнитель:** Developer
- **Приоритет:** P2
- **Оценка:** 4-6ч
- **Источник:** Strategist post-Sprint+1 — у MPump tag-система first-class
  (Лидер/Звезда/Архив/Новинка), у TrueStats — через «склейки». У нас
  `product_groups` есть, но UX «быстро пометить SKU и фильтровать» — нет.
- **Описание:** На карточке SKU в /units, /unit-plan, /supply — chip-набор
  тегов с эмодзи. Преднастроенные: 🏆 Лидер / ⭐ Звезда / 📦 Архив /
  🆕 Новинка / 🚨 Проблема / 🔥 Хит. Custom-теги — director может
  заводить свои в Settings. Фильтр по тегу в заголовке каждой страницы.
- **Критерии готовности:**
  - [x] Миграция **0052** `product_tags` + `product_tag_assignments`
        (0051 был занят параллельной сессией под `reconciliation_imports`).
        `product_tags`: UNIQUE (tenant, name). `product_tag_assignments`:
        UNIQUE (tenant, nm_id, tag_id) + индексы по nm и tag
  - [x] Preset-теги seed'ятся в `upgrade()` через CROSS JOIN tenants ×
        6 preset (🏆 Лидер / ⭐ Звезда / 📦 Архив / 🆕 Новинка / 🚨 Проблема /
        🔥 Хит) с `is_preset=true`. Удалять preset'ы нельзя (409 в API).
  - [x] Backend API `api/product_tags.py`:
        - `GET /api/product-tags` (любой залогиненный, с usage_count)
        - `POST/PATCH/DELETE /api/product-tags` (director only)
        - `GET/PUT /api/products/{nm_id}/tags` (brand-scope check для manager)
  - [x] Frontend `components/ProductTagChips.tsx` — chips + popover-палитра.
        Click-toggle с TanStack mutation. compact-режим для embed в таблицу.
  - [x] Header-фильтр в Units / Unit-Plan / Supply / ABC — реализован через
        [TASK-DEV-025](#task-dev-025-funnel-tag-filter) (Funnel) и был раньше
        для Units/UnitPlan/Supply/ABC в этой же сессии. Сейчас chips можно
        навешивать; фильтрация по тегу через header-dropdown.
- **Зависимости:** нет
- **Статус:** ✅ Закрыта 2026-05-21 (миграция 0052, model `ProductTag` +
  `ProductTagAssignment`, API в `product_tags.py`, frontend chip-component).

---

### TASK-DEV-025: Funnel tag-filter (extension TASK-DEV-024)

- **Исполнитель:** Developer
- **Приоритет:** P3
- **Оценка:** 0.5ч
- **Источник:** Funnel страница не получила header-фильтр в первоначальной
  выкатке TASK-DEV-024 (закрыли с follow-up'ом). Перетянуть hook
  `useTagFilter` + `TagFilterDropdown` который уже работает на Units /
  UnitPlan / Supply / AbcAnalysis.
- **Описание:** Добавить `<TagFilterDropdown storageKey="funnel.tag-filter.v1"/>`
  в header и фильтровать items через `matchTag(nm_id)` в `useMemo`.
- **Критерии готовности:**
  - [x] Импорт `useTagFilter` + `TagFilterDropdown` в `pages/Funnel.tsx`
  - [x] Фильтр через `.filter((it) => matchTag(it.nm_id))` перед сортировкой
  - [x] `matchTag` в dep array `useMemo`
  - [x] storageKey не пересекается с другими страницами
- **Зависимости:** TASK-DEV-024
- **Статус:** ✅ Закрыта 2026-05-21

---

### TASK-DEV-026: `/bind` `/unbind` команды TG-бота для self-binding User.tg_chat_id

- **Исполнитель:** Developer
- **Приоритет:** P2
- **Оценка:** 1ч
- **Источник:** CONTINUE_HERE.md v0.15.2 (TG back-loop) — упомянуто как
  «Bot `/start` auto-bind: бот распознаёт зарегистрированного юзера и
  автозаписывает `tg_chat_id`». Сейчас `users.tg_chat_id` нужно заполнять
  через UI Settings → «Мой Telegram-чат» (миграция 0054) — но юзеру нужно
  где-то взять свой chat_id. `/bind <username>` решает это: юзер пишет
  боту, бот достаёт `chat_id` из update и записывает в `User.tg_chat_id`.
- **Описание:**
  - `/bind <username>` — находит активного User по `(tenant, username)`,
    записывает chat_id. Открыт всем — не требует tenant-owner roles.
  - `/unbind` — снимает привязку с текущего chat_id (все user'ы которые
    привязаны к этому chat_id).
  - HELP обновлён.
- **Критерии готовности:**
  - [x] `_bind_user(chat_id, username)` в `bot/main.py` — поиск по `(tenant_id, username, is_active)`
  - [x] `_unbind_user(chat_id)` — UPDATE `users SET tg_chat_id = NULL WHERE tg_chat_id = chat_id`
  - [x] Открытые команды (ДО `_is_authorized` check), любой юзер РНП может привязаться
  - [x] HELP обновлён + usage hint при `/bind` без аргумента
- **Зависимости:** миграция 0054 (`users.tg_chat_id`)
- **Статус:** ✅ Закрыта 2026-05-21

---

## Жизненный цикл / DoD

См. `RULES.md` и `developer.md` §«Жизненный цикл задачи».

Чеклист перед `Выполнено`:

- [ ] `python3 -c "import ast; ast.parse(...)"` — backend синтаксис
- [ ] `cd frontend && npx tsc --noEmit` — 0 ошибок
- [ ] Smoke в браузере — нет красного в консоли
- [ ] Если меняется схема БД — миграция вверх и вниз проверены
- [ ] Если backfill > 1000 строк — chunk_size=1000, commit-per-chunk
- [ ] Не использован `--no-verify`, `@ts-ignore`, `eslint-disable`
- [ ] `CLAUDE.md` / `WB_API_REFERENCE.md` / гайды роли — обновлены если меняется поведение
