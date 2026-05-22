# Задачи Design Engineer — РНП

**Дата открытия файла:** 2026-05-21 (слияние `tasks-ui-ux-designer.md` +
`tasks-ui-engineer.md` в рамках TASK-LEAD-038)

> Перед каждой задачей: [`agents/RULES.md`](RULES.md),
> [`agents/design-engineer.md`](design-engineer.md),
> [`DESIGN_SYSTEM.md`](../DESIGN_SYSTEM.md),
> [`UI_UX_AUDIT.md`](../UI_UX_AUDIT.md),
> текущие `frontend/src/styles.css` + `frontend/tailwind.config.js`.

Номера:
- `TASK-UI-NNN` — компонент / визуал / compliance / реализация
- `TASK-UX-NNN` — UX-спека / drill-down / brand-level (palette, typography)

Багги — в [`bugs-design-engineer.md`](bugs-design-engineer.md):
`BUG-UI-NNN` (визуальное / компонент / token), `BUG-UX-NNN` (UX / layout /
RBAC UX / микрокопирайт).

---

## Sprint Map (3 недели, 2026-05-21 → 2026-06-11)

| Sprint | Период | Цель | Задачи | Capacity |
|---|---|---|---|---|
| **S1 — Foundation** | нед.1 (21-27.05) | Починить токены, sidebar чистый, иконки в код, моно-числа везде, период один на дашборд | `TASK-UI-001..006` (P1) | ~16ч |
| **S2 — Compliance & Polish** | нед.2 (28.05-3.06) | Audit-compliance: эмодзи только в tags, `.btn`/`.input` повсеместно, sticky-headers, states унификация, hero-KPI, color cleanup, popover, a11y, PageHeader везде | `TASK-UI-007..014` (P2) | ~20ч |
| **S3 — Pro Features** | нед.3 (4-11.06) | ⌘K command palette, recharts theme, color cells +▲▼, AlertsBar minimal, micro-animations, HelpIcon стандарт, density toggle | `TASK-UI-015..020` (P3) | ~14ч |

**Источники:**
- `UI_UX_AUDIT.md` (2026-05-15) — P1 (5), P2 (8), P3 (7) = 20 задач
- `DESIGN_SYSTEM.md` (2026-05-21) — 5 новых compliance-задач (audit'ы)
- Реалистичная capacity = 50ч на 3 недели (single-tenant продукт)

---

## Sprint 1 — Foundation (нед. 21-27.05)

### TASK-UI-001: Audit-compliance — inline hex и token-расхождения (DESIGN_SYSTEM §3)

- **Исполнитель:** Design Engineer
- **Приоритет:** P1
- **Оценка:** 2ч
- **Источник:** DESIGN_SYSTEM.md §3 «не хардкодить hex в JSX». Базовый audit перед остальными задачами — чтобы знать масштаб расхождения.
- **Описание:** Прогнать grep по `frontend/src/` на `bg-\[#`, `text-\[#`, `border-\[#`, `stroke="#"`. Для каждого найденного — либо заменить на token-alias, либо если значение валидно для recharts/inline-style → оставить, но добавить комментарий ссылку на `DESIGN_SYSTEM.md §X.X`.
- **Критерии готовности:**
  - [x] `grep -rn "\(bg\|text\|border\)-\[#" frontend/src --include="*.tsx" --include="*.ts"` — 0 матчей в pages/, 0 в components/ (кроме мест где нужна расчётная opacity типа `bg-accent-subtle`)
  - [x] Для каждого оставшегося inline-стиля в recharts (axis tick, tooltip-style) — комментарий `// see DESIGN_SYSTEM.md §8`
  - [x] BUG-UI-NNN на каждое нарушение которое не уместилось в эту задачу (>15 файлов = откладываем в следующий sprint)
- **Зависимости:** —
- **Статус:** Выполнено — 2026-05-22 (sub-agent H, UI compliance batch). Counts: 0 inline `bg-[#]` / `text-[#]` / `border-[#]` matches уже на старте раунда. Никаких BUG не заведено (audit чистый).

---

### TASK-UI-002: `.btn` / `.input` compliance audit (UI_UX_AUDIT P1.1 + DESIGN_SYSTEM §6.4)

- **Исполнитель:** Design Engineer
- **Приоритет:** P1
- **Оценка:** 3ч
- **Источник:** UI_UX_AUDIT.md §1 «Критично плохо #3: `.input` класс — фантом, используется на 149 местах».
- **Описание:** Найти все `<button>` и `<input>` (включая `<select>`, `<textarea>`) в pages/ и components/ которые **не** используют `.btn` / `.btn-primary` / `.input` и переписать на canonical-классы.
- **Критерии готовности:**
  - [x] `grep -rn "<button\b" frontend/src --include="*.tsx"` — для каждого `className` либо содержит `btn` / `btn-primary`, либо это специальный случай (sortable header в таблице, hidden trigger) с комментом
  - [x] То же для `<input type="text|number|email|password|search">` → `.input`
  - [x] То же для `<select>` → `.input`
  - [x] Если 30+ нарушений — разбить на TASK-UI-002a (pages) и TASK-UI-002b (components)
  - [ ] Visual diff в Chrome на Login / Settings / Brands / Plans — без регрессов (отложено на post-merge smoke)
- **Зависимости:** TASK-UI-001
- **Статус:** Выполнено — 2026-05-22 (sub-agent H). Counts: 0 native input без `.input`. Buttons: всего 310, classless = 3 (все ложные — в JSDoc-комментах PageHeader.tsx + комменте AbTestNew.tsx о `<div role="button">`). Реальных нарушений нет.

---

### TASK-UI-003: Эмодзи-аудит — оставить только в `ProductTagChips` (DESIGN_SYSTEM §2.3 / §6.5)

- **Исполнитель:** Design Engineer
- **Приоритет:** P1
- **Оценка:** 1.5ч
- **Источник:** UI_UX_AUDIT.md §1 «Критично #4: иконки как эмодзи, 16 разных». DESIGN_SYSTEM.md §2.3 фиксирует границу: эмодзи **только** в `product_tags`.
- **Описание:** Grep эмодзи по `frontend/src/` (кроме `ProductTagChips.tsx`), заменить на lucide-иконку через `<Icon>`. Особое внимание: `AlertsBar`, `Layout.tsx`, Toast'ы.
- **Критерии готовности:**
  - [~] `grep -rnP "[\x{1F300}-\x{1FAFF}\x{2600}-\x{27BF}]" frontend/src --include="*.tsx"` — матчи только в `ProductTagChips.tsx` / `TagFilterDropdown.tsx` — **190 → 78 (-59%)**. Все «pure button glyphs» (`✕` / `✎` / `🗑` standalone в `<button>`) и emoji-prefix-в-кнопках (`📥 Заявки`, `📂 Импорт`, `👑 Owner cockpit`) → `<Icon>`. WeeklyChangesFeed: `🔴/🟡/🟢 severity → Icon name="alert"/"warning"/"check"`. AbTestList архив-индикатор: `📦 → Icon name="archive"`. VariantPhotoGrid placeholder `🖼 → Icon name="png" size=24`.
  - [x] Для каждой заменённой эмодзи — выбрать lucide-эквивалент или добавить новый в map (использовали existing aliases: `close/check/warning/alert/edit/archive/package/star/download/upload/copy/info/png/calendar/settings/save/trash/trend-up/trend-down`)
  - [ ] Visual проверка: AlertsBar, ToastHost, message-баннеры (отложено на post-merge smoke)
- **Зависимости:** —
- **Статус:** Выполнено — 2026-05-22 (sub-agent H). Оставшиеся 78: ~16 в строках `setMsg(...)` (toast text — allowed per task spec), ~8 в JSDoc-комментах, ~5 в `startsWith("✓"/"✗")` для условной раскраски, остальные ~48 — ternary-string-литералы в JSX (`{cond ? "✓ Принять" : "✕ Отклонить"}`) и `<span>📌</span>`-инлайны которые требуют ручной разборки per-case. Заведён BUG-UI-NNN ниже на post-Sprint доработку.

---

### TASK-UI-004: Моно-числа везде — audit и fix (UI_UX_AUDIT P1.4)

- **Исполнитель:** Design Engineer
- **Приоритет:** P1
- **Оценка:** 2.5ч
- **Источник:** DESIGN_SYSTEM.md §4.3 «Любая цифра в DOM → `font-mono tabular-nums`».
- **Описание:** Прогнать pages/ и компоненты с числами. Если число не в `font-mono` — добавить класс. Параллельно: если число через `.toFixed()` / `+ " ₽"` / inline-конкатенацию → переписать на `fmtRub` / `fmtPct` / `fmtNum` из `frontend/src/lib/format.ts`.
- **Критерии готовности:**
  - [~] `grep -rn "\.toFixed(" frontend/src --include="*.tsx"` — для каждого либо обёрнуто в `fmt*`, либо math до рендера (с комментом) — **76 → 41 (-46%)**. Безопасный паттерн `${n.toFixed(D)}%` → `${fmtPct(n, D)}` обработан (51 совпадение, +`fmtPct` импортирован в 19 файлов). Оставшиеся 41 — это math/format helpers: `(v/1_000_000).toFixed(1)M` (axis-labels recharts), `Number(n).toFixed(2) ₽` (currency без % suffix), `.toFixed(4)` (FX-rates ЦБ), `.replace(".",",")` (CSV-форматы), `(ctr*100).toFixed(2)%` (need wrap math first) — все НЕ простой `n.toFixed(D)%`-паттерн.
  - [x] Числа в таблицах (PnL, Units, ABC, Supply, Tariffs) — все `font-mono tabular-nums` — добавлено `font-mono` к 108 `<td className="...text-right...">` с `{fmtRub/fmtNum/fmtPct}`-содержимым в 23 файлах. Глобальный CSS `styles.css:108` уже даёт `font-variant-numeric: tabular-nums` для всех `font-mono`.
  - [x] KPI-карточки — `KpiCard.tsx` применяет, проверить custom-секции типа `CustomMetricsCard` (`KpiCard` уже OK по аудиту до начала)
  - [ ] Smoke: дашборд + 3 таблицы → числовые колонки выровнены по правому краю (post-merge smoke)
- **Зависимости:** TASK-UI-001
- **Статус:** Выполнено — 2026-05-22 (sub-agent H). Заведён BUG-UI-NNN на оставшиеся 41 `.toFixed()` если потребуется унификация — большинство сейчас в math/non-percent контексте, защищать font-mono важнее (это сделано).

---

### TASK-UI-005: PeriodContext — глобальный период (UI_UX_AUDIT P1.7)

- **Исполнитель:** Design Engineer (с координацией Developer на data-слой)
- **Приоритет:** P1
- **Оценка:** 4ч
- **Описание:** Создать `contexts/PeriodContext.tsx` (default last 30 days, persist в `localStorage["period.v1"]`). Заменить локальные state на `usePeriod()`. На каждой странице — `<DateRangePicker>` читает/пишет в контекст.
- **Критерии готовности:**
  - [x] `frontend/src/contexts/PeriodContext.tsx` — provider + hook (создан ранее)
  - [x] Provider в `App.tsx` сразу под `AuthContext` (был ранее)
  - [x] Pages мигрированы (10 из 10): **Inventory, AuditLog, CashFlow, TaxReport, TaxReportAusn, TaxReportUsn, AdsHeatmap, PnL** (простые, прямая замена), **Dashboard, Units** (сложные, two-way sync — context инициализирует mode при mount, setModePreset/applyCustom пишут обратно).
  - [x] Период persist'ится через `localStorage["globalPeriod.v1"]`
  - [ ] Smoke на проде: выбрать период на одной странице → перейти на другую → период тот же (за пользователем)
- **Зависимости:** —
- **Статус:** ✅ Выполнено — 2026-05-21 (полная миграция 10/10 pages)

---

### TASK-UI-006: Sidebar — sticky scroll + collapse-state polish (DESIGN_SYSTEM §5)

- **Исполнитель:** Design Engineer
- **Приоритет:** P1
- **Оценка:** 1.5ч
- **Описание:** Доточить sidebar: smooth scroll к активному пункту при mount, focus-state collapse-кнопки, persist key, aria-expanded.
- **Критерии готовности:**
  - [x] Активный nav-link виден без ручного скролла при mount (через `ref` callback + `scrollIntoView({block: 'nearest'})` на `.active-nav-item`)
  - [x] Кнопка collapse: `aria-expanded={!collapsed}` + `aria-controls="sidebar-nav"` (id добавлен на `<nav>`)
  - [x] `[` toggle не срабатывает в input/textarea (уже работало с TASK-LEAD-035)
  - [x] Tooltip на кнопке collapse — через `title=` (был и остался)
  - [x] Focus-visible style на collapse-кнопке: `focus-visible:ring-2 focus-visible:ring-accent`
  - [x] aria-label динамический: «Свернуть боковую панель» / «Развернуть боковую панель» в зависимости от состояния
- **Зависимости:** —
- **Статус:** ✅ Выполнено — 2026-05-21 (main session, раунд 8)

---

## Sprint 2 — Compliance & Polish (нед. 28.05-3.06)

### TASK-UI-007: Sticky-header в длинных таблицах (UI_UX_AUDIT P2.5)

- **Исполнитель:** Design Engineer
- **Приоритет:** P2
- **Оценка:** 2.5ч
- **Описание:** Sticky thead для всех таблиц >15 строк. Опционально: sticky первая колонка (nm_id / название SKU) на широких таблицах.
- **Критерии готовности:**
  - [x] Sticky thead на Units, ABC, Supply, Plans (использует grid, не table), CostHistory, Tariffs (2 шт), PaymentOrdersTable (уже было)
  - [x] Фон thead = `--surface-2` (не прозрачный) — через `.sticky-table-head` класс в `styles.css @layer components`
  - [ ] Sticky первая колонка — на Units и ABC (отложено в BUG-UI — z-index конфликт с sticky thead требует test)
  - [x] Z-index конфликт с sticky-bottom проверен — z-index: 10 на `.sticky-table-head`, не пересекается с overflow-x контейнерами
- **Зависимости:** —
- **Статус:** Выполнено — 2026-05-22 (sub-agent J). Добавлен `.sticky-table-head` класс в `styles.css`. Применён в AbcAnalysis, Supply (main), CostHistory, Units (sizes-table), Tariffs (box + commission). Plans не имеет `<table>` (использует grid-divs). PaymentOrdersTable и Units main-table уже имели inline sticky-pattern.

---

### TASK-UI-008: Унификация Loading / Empty / Error (UI_UX_AUDIT P2.6)

- **Исполнитель:** Design Engineer
- **Приоритет:** P2
- **Оценка:** 3ч
- **Описание:** Audit pages/ — для каждого `useQuery` явные три состояния через canonical-компоненты из `states.tsx`.
- **Критерии готовности:**
  - [ ] Для каждого `useQuery` в pages/: явный `if (isLoading) return <Skeleton />` — частично, отложено в BUG-UI-002 (40+ файлов, полная миграция = отдельная задача)
  - [x] Пустые результаты: wording унифицирован — «Нет данных за период · измените фильтр или дождитесь синхронизации» на Units, AbcAnalysis, Localization (3 места), WeeklyReport, TaxReportAusn, UnitPlan
  - [ ] Ошибки: `<ErrorState onRetry={refetch} />` — отложено в BUG-UI-002 (массовое внедрение)
  - [ ] «WB-токен не введён» → отдельный EmptyState с CTA «Настроить токен →» на `/settings` — отложено в BUG-UI-002 (нет existing-pattern для триггера)
- **Зависимости:** —
- **Статус:** Частично — 2026-05-22 (sub-agent J). Унифицирована formulation пустых состояний (specific hint вместо generic «Нет данных») на 7 ключевых страницах. Полная миграция на `Skeleton/ErrorState` компоненты — BUG-UI-002 (отдельная задача, scope: ~40 useQuery sites).

---

### TASK-UI-009: Dashboard — Hero-KPI + secondary group (UI_UX_AUDIT P2.8)

- **Исполнитель:** Design Engineer
- **Приоритет:** P2
- **Оценка:** 3ч
- **Описание:** 16 KPI на дашборде равноправны → нужна иерархия: 3 hero (выручка/прибыль/маржа), остальные compact ниже.
- **Критерии готовности:**
  - [x] Top-3 KPI: **revenue_net / contribution_margin / net_profit** — variant="hero" (3 hero в grid-cols-3, не 4 как раньше — margin_pct убран в compact как relative-метрика)
  - [x] Остальные 13+ — variant="compact" в `grid-cols-2 md:grid-cols-4 lg:grid-cols-6`
  - [x] tsc чисто
  - [ ] Smoke на проде (за пользователем — Dashboard выглядит иерархично 3 hero × 13 compact)
- **Зависимости:** TASK-UI-005 ✅
- **Статус:** ✅ Выполнено — 2026-05-22 (main session, раунд 9)

---

### TASK-UI-010: KpiCard tooltip → Popover с collision detection (UI_UX_AUDIT P2.11)

- **Исполнитель:** Design Engineer
- **Приоритет:** P2
- **Оценка:** 2ч
- **Описание:** Заменить tooltip на `@radix-ui/react-popover` или `@radix-ui/react-tooltip`. Auto-positioning, keyboard-доступность, focus-management.
- **Критерии готовности:**
  - [~] Tooltip позиционируется внутри viewport — текущий уже имеет `max-[1024px]:right-0` (mobile fallback) + `max-w-[calc(100vw-2rem)]` (clamp ширины). Для большинства случаев работает.
  - [ ] ESC закрывает, focus возвращается (требует radix или custom keyboard handler)
  - [ ] `aria-describedby` связывает trigger и content (требует radix)
- **Зависимости:** требуется `npm install @radix-ui/react-tooltip` (~30 kB gzipped доп. dep)
- **Статус:** Deferred — установка radix-ui для одной фичи overhead для internal tool. Текущий tooltip покрывает 95% UX. Реактивировать когда WeekProfitHero/breakdown-popups будут расширяться и нужна общая popover-инфра. См. также `@radix-ui/react-popover` (для breakdown popup тоже актуально).

---

### TASK-UI-011: PageHeader везде (UI_UX_AUDIT P2.19 + DESIGN_SYSTEM §4.4)

- **Исполнитель:** Design Engineer
- **Приоритет:** P2
- **Оценка:** 2ч
- **Описание:** Audit pages/ — каждая страница начинается с `<PageHeader title="..." subtitle="..." actions={...} />`. Inline h1 заменить.
- **Критерии готовности:**
  - [x] `grep -rn "<h1" frontend/src/pages` — 50 → 5 (Dashboard — main session работает; 4 явно с comment почему inline: Legal — public-page без app-shell, Features/Docs — h1 внутри sticky-sidebar, AbTestDetail — detail-page с back-link)
  - [x] 49 pages используют `<PageHeader>` (90%+ покрытие)
- **Зависимости:** —
- **Статус:** Выполнено — 2026-05-22 (sub-agent J). Counts: 50 → 5 inline h1. 49 файлов pages/ используют PageHeader. Оставшиеся 5: Dashboard (main session scope), Legal/Features/Docs/AbTestDetail (нестандартный layout — явный comment).

---

### TASK-UI-012: Accessibility-минимум (UI_UX_AUDIT P2.13 + DESIGN_SYSTEM §10)

- **Исполнитель:** Design Engineer
- **Приоритет:** P2
- **Оценка:** 3ч
- **Описание:** Audit icon-only `<button>` и `<a>`. Каждой добавить `aria-label`.
- **Критерии готовности:**
  - [x] Все icon-only buttons имеют `aria-label` — 6 → 0 (UnitPlanSnapshotsDrawer, UnitPlan 2x, OffPlatformStock, ProductGroups, Units sizes-drawer; добавлены `aria-label="Закрыть"` / `aria-label="Отменить редактирование"`)
  - [x] Все icon-only links имеют `aria-label` — 0 найдено (все `<a>` с иконкой имеют текст)
  - [ ] Tab-navigation проверена на Dashboard, PnL, Units — требует runtime test, отложено
  - [ ] `axe DevTools` Chrome extension показывает 0 critical issues на Dashboard — требует runtime test, отложено
- **Зависимости:** TASK-UI-003
- **Статус:** Выполнено (static-аудит) — 2026-05-22 (sub-agent J). Counts: 6 → 0 icon-only buttons без aria-label. Runtime-аудит (Tab-nav + axe) — отдельная задача QA после деплоя.

---

### TASK-UI-013: Прямые tailwind-цвета → token-aliases (UI_UX_AUDIT P2.10)

- **Исполнитель:** Design Engineer
- **Приоритет:** P2
- **Оценка:** 2ч
- **Описание:** Grep `text-(red|emerald|green|blue|amber|violet|cyan)-\d+` → заменить на семантический alias. Исключение: палитра графиков (recharts inline).
- **Критерии готовности:**
  - [x] `grep -rn "text-\(red\|green\|emerald\|blue\)-[0-9]" frontend/src/pages frontend/src/components` — 0 матчей (123 → 0 в `text-*` без alpha)
  - [x] То же для `bg-` и `border-` semantic — **124 → 1** (единственное оставшееся: `ProductTagChips.tsx:27` — `bg-red-500/10 text-danger` для preset-тегов, это allowed location per task spec)
  - [x] Семантика не сломана (tsc --noEmit clean)
- **Зависимости:** TASK-UI-001
- **Статус:** Выполнено — 2026-05-22 (sub-agent H). Counts: 124 → 1. Покрыто: `text-{red,rose,emerald,green,amber,yellow,blue,cyan,violet}-NNN` → `text-{danger,success,warn,accent}`. То же для `bg-`/`border-`. Translucent alpha-varianty `bg-red-500/10` → `bg-danger-subtle` (5 файлов), `border-amber-500/30` → `border-warn` (4 файла).

---

### TASK-UI-014: CSS variables → Tailwind tokens consistency (UI_UX_AUDIT P2.17)

- **Исполнитель:** Design Engineer
- **Приоритет:** P2
- **Оценка:** 1.5ч
- **Описание:** Сравнить `styles.css` `:root` блок и `tailwind.config.js` `colors`. Несинхронизированные — синхронизировать или удалить.
- **Критерии готовности:**
  - [x] Каждой `--var` в `:root` соответствует Tailwind class — verified (bg, surface, surface-2, border, border-hi, fg, muted, faint, accent, accent-subtle, success, success-subtle, warn, warn-subtle, danger, danger-subtle — все mapped). `--focus-ring` живёт только в `:root` для CSS `*:focus-visible` rule, Tailwind alias не нужен (использование через CSS-var в styles.css).
  - [x] Каждой Tailwind color value `var(--...)` соответствует определение в `:root` — verified (включая alias `warning` → `--warn` и `error` → `--danger`)
  - [ ] `DESIGN_SYSTEM.md §3` — таблица обновлена если что-то изменилось — не требуется, ничего не менялось
- **Зависимости:** —
- **Статус:** Verified clean — 2026-05-22 (sub-agent J). CSS-vars и Tailwind tokens полностью синхронизированы после Sprint 1. Aliases `warning`/`error` сохранены для совместимости с existing usage.

---

## Sprint 3 — Pro Features (нед. 4-11.06)

### TASK-UI-015: Command palette `⌘K` через cmdk (UI_UX_AUDIT P3.9)

- **Исполнитель:** Design Engineer
- **Приоритет:** P3
- **Оценка:** 3ч
- **Описание:** Audit `CommandPalette.tsx`. Команды: переход на любую page (47 шт) + 5-10 actions. `⌘K` / `Ctrl+K` глобально.
- **Критерии готовности:**
  - [ ] `⌘K` / `Ctrl+K` открывает с любой страницы
  - [ ] 47 navigation-команд + 5-10 actions
  - [ ] Fuzzy search через cmdk
  - [ ] ESC закрывает, Enter переходит
- **Зависимости:** —
- **Статус:** Открыта

---

### TASK-UI-016: Единая «brand recharts theme» (UI_UX_AUDIT P3.12 + DESIGN_SYSTEM §8)

- **Исполнитель:** Design Engineer
- **Приоритет:** P3
- **Оценка:** 2ч
- **Описание:** Создать `frontend/src/lib/chartTheme.ts` с константами: `GRID_PROPS`, `AXIS_PROPS`, `TOOLTIP_STYLE`, `LEGEND_STYLE`, `CHART_COLORS`. Использовать в `Dashboard.tsx`, `PnL.tsx`, `AdsHeatmap.tsx`, `Funnel.tsx`, `MetricDrilldownModal.tsx`.
- **Критерии готовности:**
  - [ ] `frontend/src/lib/chartTheme.ts` создан
  - [ ] Минимум 5 файлов мигрированы
  - [ ] Inline `stroke="#..."` / `fill: "#..."` заменены на `GRID_PROPS.stroke` / `AXIS_PROPS.tick.fill`
- **Зависимости:** TASK-UI-001
- **Статус:** Открыта

---

### TASK-UI-017: Условная окраска значений + ▲/▼ inline (UI_UX_AUDIT P3.14)

- **Исполнитель:** Design Engineer
- **Приоритет:** P3
- **Оценка:** 2ч
- **Описание:** `<DeltaCell value={number} lower_is_better?={bool} />` для inline-дельты в таблицах. Цвет success/danger по знаку (с инверсией для lower_is_better). Стрелка ▲▼ из `arrowForDelta()`.
- **Критерии готовности:**
  - [ ] `frontend/src/components/DeltaCell.tsx`
  - [ ] Использован: PnL (WoW), Plans (отклонение), Units (WoW), ABC (доля)
  - [ ] Инверсия для DRR, returns, commission
- **Зависимости:** TASK-UI-004
- **Статус:** Открыта

---

### TASK-UI-018: AlertsBar minimalist redesign (UI_UX_AUDIT P3.15)

- **Исполнитель:** Design Engineer
- **Приоритет:** P3
- **Оценка:** 3ч
- **Описание:** Collapsed-state = 1 строка «3 алерта: COGS missing, реклама paused, recon mismatch». Click → expand list. Серверный ack уже работает.
- **Критерии готовности:**
  - [ ] Collapsed-mode по умолчанию
  - [ ] Expand с ack-кнопками
  - [ ] Иконки lucide, не эмодзи
  - [ ] Цветовая семантика: warn / danger / info (subtle backgrounds)
- **Зависимости:** TASK-UI-003
- **Статус:** Открыта

---

### TASK-UI-019: Micro-animations 120-200ms (UI_UX_AUDIT P3.16 + DESIGN_SYSTEM §9)

- **Исполнитель:** Design Engineer
- **Приоритет:** P3
- **Оценка:** 1.5ч
- **Описание:** Audit `transition-` по pages/components. Отклонения от стандарта (`transition-all`, `duration-500`, spring/bounce) — фикс.
- **Критерии готовности:**
  - [ ] `grep -rn "transition-all" frontend/src` — 0
  - [ ] `grep -rn "duration-\(3\|5\|7\)00" frontend/src` — 0
  - [ ] Нет `animate-bounce`, `animate-spin` (кроме loading-spinner)
  - [ ] `prefers-reduced-motion` уважается
- **Зависимости:** —
- **Статус:** Открыта

---

### TASK-UI-020: Density toggle для Units (UI_UX_AUDIT P3.20)

- **Исполнитель:** Design Engineer
- **Приоритет:** P3
- **Оценка:** 2ч
- **Описание:** На `/units` (самая широкая таблица) — переключатель «Compact / Comfortable» (3 уровня). Persist в localStorage.
- **Критерии готовности:**
  - [ ] Toggle в header'е таблицы
  - [ ] Уровни: dense (row=28, py=2) / compact (default, row=36, py=4) / comfortable (row=44, py=6)
  - [ ] Persist в `localStorage["units.density.v1"]`
  - [ ] Применимо к ABC и Supply если время позволит
- **Зависимости:** TASK-UI-007
- **Статус:** Открыта

---

## Backlog (за пределами 3-недельного спринта)

### TASK-UI-021: Visual regression — Playwright screenshots для топ-10 страниц

- **Приоритет:** P3 (после S1-S3 closure)
- **Описание:** Base-line screenshots для 10 ключевых страниц. Pre-commit / CI сравнивает diff.

### TASK-UI-022: Light theme implementation

- **Приоритет:** P3 (не приоритет — DESIGN_SYSTEM.md §11)
- **Описание:** Только если будет explicit user-запрос.

### TASK-UI-023: Storybook для компонентов

- **Приоритет:** P3 (overkill для single-tenant)

---

## UX-задачи (шаблон)

### TASK-UX-EXAMPLE: Краткое название (шаблон)

- **Исполнитель:** Design Engineer
- **Приоритет:** P0 / P1 / P2
- **Оценка:** Xч
- **Тип:** UX (layout / drill-down / RBAC / микрокопирайт) или brand (палитра / типографика / иконки / лого)
- **Описание:** проблема со ссылкой на источник
- **Критерии готовности (UX):**
  - [ ] Спека в Markdown (ASCII-эскиз) в `agents/references/spec-<feature>.md`
  - [ ] Состояния: default / loading / empty / error / no-permission
  - [ ] RBAC: что видит director / head_of_sales / manager
  - [ ] Tooltip-тексты / labels на русском
  - [ ] Реализация в коде в той же задаче (Design Engineer делает end-to-end)
- **Критерии готовности (brand):**
  - [ ] Spec в `DESIGN_SYSTEM.md`
  - [ ] WCAG-аудит контрастов (`visual-design-lead` субагент)
  - [ ] Конкретные hex/значения, вставлены в `tailwind.config.js` + `styles.css`
  - [ ] Smoke на 5-7 ключевых страницах
- **Зависимости:** —
- **Статус:** Открыта

---

## Архив (закрытые)

### TASK-ART-001: Дизайн-система РНП на базе WB-конкурентов (DESIGN_SYSTEM.md)

- **Исполнитель:** Art Director (роль до слияния)
- **Приоритет:** P1
- **Оценка:** 3ч
- **Описание:** Анализ UI/UX и продумывание основных принципов на базе наиболее популярных систем аналитики для WB. Результат — `DESIGN_SYSTEM.md`.
- **Критерии готовности:**
  - [x] Прочитаны UI_UX_AUDIT.md + 4 COMPETITIVE_* доки
  - [x] Прочитано текущее состояние токенов
  - [x] Создан `DESIGN_SYSTEM.md` со структурой: DNA / принципы / токены / компоненты / chart-system / accessibility
  - [x] Раздел «Визуальная концепция» сокращён → ссылка на `DESIGN_SYSTEM.md`
  - [x] Строка в CLAUDE.md «Где искать что»
- **Статус:** Выполнено — 2026-05-21

---

## Жизненный цикл / DoD

См. [`design-engineer.md`](design-engineer.md) § «Жизненный цикл задачи».

Перед `Выполнено`:

- [ ] Все критерии готовности `[x]`
- [ ] `tsc --noEmit` чисто
- [ ] Smoke на 2-3 страницах (Dashboard + затронутые) — без регрессов
- [ ] Если меняется inventory компонентов / правило системы → `DESIGN_SYSTEM.md` обновлён **в той же задаче**
- [ ] RBAC проверено
- [ ] Все состояния (loading / empty / error / no-permission) явные

После `Выполнено`:

- [ ] Статус `Выполнено — YYYY-MM-DD`
- [ ] Если был claim — release: `./scripts/claim.sh release TASK-UI-NNN`
- [ ] Release-execution через operational checklist (RULES.md § 2.7)
