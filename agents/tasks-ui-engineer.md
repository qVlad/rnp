# Задачи UI Engineer — РНП

**Дата открытия файла:** 2026-05-21

> Перед каждой задачей: [`agents/RULES.md`](RULES.md),
> [`agents/ui-engineer.md`](ui-engineer.md),
> [`DESIGN_SYSTEM.md`](../DESIGN_SYSTEM.md),
> [`UI_UX_AUDIT.md`](../UI_UX_AUDIT.md),
> текущие `frontend/src/styles.css` + `frontend/tailwind.config.js`.

> **Нумерация:** `TASK-UI-NNN`. Багги — в [`bugs-ui-engineer.md`](bugs-ui-engineer.md)
> формата `BUG-UI-NNN`.

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

- **Исполнитель:** UI Engineer
- **Приоритет:** P1
- **Оценка:** 2ч
- **Источник:** DESIGN_SYSTEM.md §3 «не хардкодить hex в JSX». Базовый audit перед остальными задачами — чтобы знать масштаб расхождения.
- **Описание:** Прогнать grep по `frontend/src/` на `bg-\[#`, `text-\[#`, `border-\[#`, `stroke="#"`. Для каждого найденного — либо заменить на token-alias, либо если значение валидно для recharts/inline-style → оставить, но добавить комментарий ссылку на `DESIGN_SYSTEM.md §X.X`.
- **Критерии готовности:**
  - [ ] `grep -rn "\(bg\|text\|border\)-\[#" frontend/src --include="*.tsx" --include="*.ts"` — 0 матчей в pages/, 0 в components/ (кроме мест где нужна расчётная opacity типа `bg-accent-subtle`)
  - [ ] Для каждого оставшегося inline-стиля в recharts (axis tick, tooltip-style) — комментарий `// see DESIGN_SYSTEM.md §8`
  - [ ] BUG-UI-NNN на каждое нарушение которое не уместилось в эту задачу (>15 файлов = откладываем в следующий sprint)
- **Зависимости:** —
- **Статус:** Открыта

---

### TASK-UI-002: `.btn` / `.input` compliance audit (UI_UX_AUDIT P1.1 + DESIGN_SYSTEM §6.4)

- **Исполнитель:** UI Engineer
- **Приоритет:** P1
- **Оценка:** 3ч
- **Источник:** UI_UX_AUDIT.md §1 «Критично плохо #3: `.input` класс — фантом, используется на 149 местах». Сейчас классы определены в `styles.css` `@layer components`, но проверять не проверяли.
- **Описание:** Найти все `<button>` и `<input>` (включая `<select>`, `<textarea>`) в pages/ и components/ которые **не** используют `.btn` / `.btn-primary` / `.input` и переписать на canonical-классы.
- **Критерии готовности:**
  - [ ] `grep -rn "<button\b" frontend/src --include="*.tsx"` — для каждого `className` либо содержит `btn` / `btn-primary`, либо это специальный случай (sortable header в таблице, hidden trigger) с комментом
  - [ ] То же для `<input type="text|number|email|password|search">` → `.input`
  - [ ] То же для `<select>` → `.input`
  - [ ] Если 30+ нарушений — разбить на TASK-UI-002a (pages) и TASK-UI-002b (components)
  - [ ] Visual diff в Chrome на Login / Settings / Brands / Plans (страницы с самой высокой долей форм) — без регрессов
- **Зависимости:** TASK-UI-001 (чтобы не накладывать одни правки на другие)
- **Статус:** Открыта

---

### TASK-UI-003: Эмодзи-аудит — оставить только в `ProductTagChips` (DESIGN_SYSTEM §2.3 / §6.5)

- **Исполнитель:** UI Engineer
- **Приоритет:** P1
- **Оценка:** 1.5ч
- **Источник:** UI_UX_AUDIT.md §1 «Критично #4: иконки как эмодзи, 16 разных, выглядят как hackathon-MVP». DESIGN_SYSTEM.md §2.3 фиксирует границу: эмодзи **только** в `product_tags`.
- **Описание:** Grep эмодзи по `frontend/src/` (кроме `ProductTagChips.tsx`), заменить на lucide-иконку через `<Icon>`. Особое внимание: `AlertsBar` (если есть эмодзи на типах алертов), `Layout.tsx` (логотип-точка — это `<span class="bg-accent">`, не эмодзи, OK), Toast'ы.
- **Критерии готовности:**
  - [ ] `grep -rnP "[\x{1F300}-\x{1FAFF}\x{2600}-\x{27BF}]" frontend/src --include="*.tsx"` — матчи только в `ProductTagChips.tsx` (и в `TagFilterDropdown.tsx` если он показывает эмодзи-чипы)
  - [ ] Для каждой заменённой эмодзи — выбрать lucide-эквивалент из существующего `Icon.tsx` или добавить новый в map
  - [ ] Visual проверка: AlertsBar, ToastHost, любые message-баннеры
- **Зависимости:** —
- **Статус:** Открыта

---

### TASK-UI-004: Моно-числа везде — audit и fix (UI_UX_AUDIT P1.4)

- **Исполнитель:** UI Engineer
- **Приоритет:** P1
- **Оценка:** 2.5ч
- **Источник:** DESIGN_SYSTEM.md §4.3 «Любая цифра в DOM → `font-mono tabular-nums`». UI_UX_AUDIT.md P1.4 «Числовая типографика».
- **Описание:** Прогнать pages/ и компоненты которые показывают числа. Если число не в `font-mono` — добавить класс. Параллельно: если число формируется через `.toFixed()` / `+ " ₽"` / inline-конкатенацию → переписать на `formatValue` / `fmtRub` / `fmtPct` / `fmtNum` из `frontend/src/lib/format.ts` (теряется ru-RU разделитель тысяч, см. memory).
- **Критерии готовности:**
  - [ ] `grep -rn "\.toFixed(" frontend/src --include="*.tsx"` — для каждого либо обёрнуто в `fmt*`, либо это math-вычисление до рендера (с комментом)
  - [ ] Числа в таблицах (PnL, Units, ABC, Supply, Tariffs) — все `font-mono tabular-nums`
  - [ ] Числа в KPI-карточках — уже OK (KpiCard.tsx применяет), проверить только custom-секции типа `CustomMetricsCard`
  - [ ] Smoke: дашборд + 3 таблицы → числовые колонки выровнены по правому краю
- **Зависимости:** TASK-UI-001
- **Статус:** Открыта

---

### TASK-UI-005: PeriodContext — глобальный период (UI_UX_AUDIT P1.7)

- **Исполнитель:** UI Engineer
- **Приоритет:** P1
- **Оценка:** 4ч
- **Источник:** UI_UX_AUDIT.md P1 №7. Каждая страница сейчас имеет свой `DateRangePicker` со своим state — при переходе между Dashboard / P&L / Units пользователь каждый раз заново выбирает период.
- **Описание:** Создать `contexts/PeriodContext.tsx` (default = last 30 days, persist в `localStorage["period.v1"]`). Заменить локальные state на `usePeriod()`. На каждой странице — `<DateRangePicker>` читает/пишет в контекст.
- **Критерии готовности:**
  - [ ] `frontend/src/contexts/PeriodContext.tsx` — provider + hook
  - [ ] Provider добавлен в `App.tsx` сразу под `AuthContext`
  - [ ] Pages мигрированы: Dashboard, PnL, Units, ABC, Supply, AdsHeatmap, CashFlow, PnLReconciliation, Funnel, NewProducts (10 страниц с периодом)
  - [ ] Период persist'ится в localStorage, восстанавливается при reload
  - [ ] Smoke: выбрать период на Dashboard → перейти на PnL → период такой же
- **Зависимости:** —
- **Статус:** Открыта

---

### TASK-UI-006: Sidebar — sticky scroll + collapse-state polish (DESIGN_SYSTEM §5)

- **Исполнитель:** UI Engineer
- **Приоритет:** P1
- **Оценка:** 1.5ч
- **Источник:** Layout.tsx уже работает (sidebar + groups + `[` toggle), но мелкие шероховатости: scroll-behavior при много пунктов, focus-state collapse-кнопки, persist key.
- **Описание:** Доточить sidebar: smooth scroll к активному пункту при mount (если он скрыт), визуальный feedback на `[` toggle (микро-анимация ширины уже есть, проверить), focus-ring на кнопке collapse, aria-expanded.
- **Критерии готовности:**
  - [ ] Активный nav-link виден без ручного скролла при mount
  - [ ] Кнопка collapse: `aria-expanded={!collapsed}` + `aria-controls` на `<aside>`
  - [ ] `[` toggle не срабатывает когда фокус в `<input>` / `<textarea>` (уже работает, проверить)
  - [ ] Tooltip на кнопке collapse — через `title=` (есть)
- **Зависимости:** —
- **Статус:** Открыта

---

## Sprint 2 — Compliance & Polish (нед. 28.05-3.06)

### TASK-UI-007: Sticky-header в длинных таблицах (UI_UX_AUDIT P2.5)

- **Исполнитель:** UI Engineer
- **Приоритет:** P2
- **Оценка:** 2.5ч
- **Источник:** UI_UX_AUDIT P2. Длинные таблицы (Units 80+ строк, ABC, Supply, Plans, Cost-history) при скролле теряют контекст колонок. TanStack Table поддерживает sticky-header через CSS.
- **Описание:** Добавить sticky thead для всех таблиц >15 строк. CSS:
  ```css
  table thead { position: sticky; top: 0; z-index: 10; background: var(--surface-2); }
  ```
  Опционально: sticky первая колонка (nm_id / название SKU) на самых широких таблицах (Units, ABC).
- **Критерии готовности:**
  - [ ] Sticky thead работает на Units, ABC, Supply, Plans, CostHistory, Tariffs, PaymentOrdersTable
  - [ ] При sticky фон thead = `--surface-2` (не прозрачный)
  - [ ] Sticky первая колонка — на Units и ABC (опционально, если влезает по времени)
  - [ ] Z-index конфликт с sticky-bottom footer (если есть) проверен
- **Зависимости:** —
- **Статус:** Открыта

---

### TASK-UI-008: Унификация состояний Loading / Empty / Error (UI_UX_AUDIT P2.6)

- **Исполнитель:** UI Engineer
- **Приоритет:** P2
- **Оценка:** 3ч
- **Источник:** UI_UX_AUDIT P2. `states.tsx` уже даёт `<Skeleton>`, `<EmptyState>`, `<ErrorState>`, но во многих pages используются inline-fallback'и («Loading...» текст, голый пустой div).
- **Описание:** Audit pages/ — для каждого `useQuery` проверить что есть все три состояния через canonical-компоненты. Особенно важно: страницы со списками (Units, ABC, Supply, Plans, Brands, Notifications, Settings/users).
- **Критерии готовности:**
  - [ ] Для каждого `useQuery` в pages/: явный `if (isLoading) return <Skeleton />` (или table с skeleton-rows)
  - [ ] Для пустых результатов: `<EmptyState />` с конкретным текстом (не «нет данных», а «нет SKU за этот период / измените фильтр»)
  - [ ] Для ошибок: `<ErrorState onRetry={refetch} />`
  - [ ] Особо: «WB-токен не введён» → отдельный EmptyState с CTA «Настроить токен →» (ссылка на `/settings`)
- **Зависимости:** —
- **Статус:** Открыта

---

### TASK-UI-009: Dashboard — Hero-KPI + secondary group (UI_UX_AUDIT P2.8)

- **Исполнитель:** UI Engineer
- **Приоритет:** P2
- **Оценка:** 3ч
- **Источник:** UI_UX_AUDIT P2 №8. Сейчас 16 KPI на дашборде равноправны. Нужна визуальная иерархия: 3 hero (выручка / прибыль / маржа), остальные compact ниже.
- **Описание:** Изменить layout Dashboard.tsx — top-row из 3 `<KpiCard variant="hero">` (32px hero-цифра), ниже grid из 4-6 в ряду `variant="default"` или `variant="compact"`. KpiCard уже поддерживает варианты.
- **Критерии готовности:**
  - [ ] Top-3 KPI: revenue_gross / net_profit / margin_pct (или contribution_margin когда TASK-LEAD-034 закроется) — variant="hero"
  - [ ] Остальные 13 — variant="compact" в grid `grid-cols-4` (>1280px) или `grid-cols-3` (1024-1280)
  - [ ] Hero-карточки занимают `col-span-2` (или 3) — больше визуальный вес
  - [ ] Smoke: Dashboard выглядит «иерархично», не «стенкой одинаковых блоков»
- **Зависимости:** TASK-UI-005 (PeriodContext) — чтобы не рефакторить дважды
- **Статус:** Открыта

---

### TASK-UI-010: KpiCard tooltip → Popover с collision detection (UI_UX_AUDIT P2.11)

- **Исполнитель:** UI Engineer
- **Приоритет:** P2
- **Оценка:** 2ч
- **Источник:** UI_UX_AUDIT P2 №11. Сейчас tooltip в KpiCard — absolute-позиционированный div через group-hover. На правом краю экрана он обрезается (есть `[&]:max-[1024px]:left-auto right-0`-хак, но это не collision detection).
- **Описание:** Заменить на `@radix-ui/react-popover` или `@radix-ui/react-tooltip` (radix уже в проекте если cmdk подключим). Auto-positioning, keyboard-доступность, focus-management.
- **Критерии готовности:**
  - [ ] Tooltip позиционируется внутри viewport на любой ширине (320px-3840px)
  - [ ] ESC закрывает (если popover), focus возвращается
  - [ ] `aria-describedby` связывает trigger и content
  - [ ] Mobile-tap (если попадает) тоже работает — fallback на click
- **Зависимости:** —
- **Статус:** Открыта

---

### TASK-UI-011: PageHeader везде (UI_UX_AUDIT P2.19 + DESIGN_SYSTEM §4.4)

- **Исполнитель:** UI Engineer
- **Приоритет:** P2
- **Оценка:** 2ч
- **Источник:** DESIGN_SYSTEM §4.4. `<PageHeader>` существует, но используется не на всех страницах — много inline `<h1 class="text-2xl font-semibold">`.
- **Описание:** Audit pages/ — каждая страница начинается с `<PageHeader title="..." subtitle="..." actions={...} />`. Inline h1 заменить.
- **Критерии готовности:**
  - [ ] `grep -rn "<h1" frontend/src/pages` — матчи только внутри `PageHeader.tsx`
  - [ ] 47 pages используют `<PageHeader>` (либо там его нет — например, Login без header'а)
  - [ ] `<PageHeader>` поддерживает slot для actions (кнопки экспорта, фильтры) — проверить что справа от title
- **Зависимости:** —
- **Статус:** Открыта

---

### TASK-UI-012: Accessibility-минимум (UI_UX_AUDIT P2.13 + DESIGN_SYSTEM §10)

- **Исполнитель:** UI Engineer
- **Приоритет:** P2
- **Оценка:** 3ч
- **Источник:** UI_UX_AUDIT P2 №13. DESIGN_SYSTEM §10. focus-visible глобально работает (есть в styles.css), но aria-label на icon-only кнопках точечно, не везде.
- **Описание:** Audit `<button>` без текстового content (только `<Icon>`). Каждой добавить `aria-label`. Параллельно: `<a>` с иконкой-only тоже.
- **Критерии готовности:**
  - [ ] Все icon-only buttons имеют `aria-label`
  - [ ] Все icon-only links имеют `aria-label`
  - [ ] Tab-navigation проверена на Dashboard, PnL, Units — фокус видим, порядок логичный
  - [ ] `axe DevTools` Chrome extension показывает 0 critical issues на Dashboard
- **Зависимости:** TASK-UI-003 (после замены эмодзи на Icon)
- **Статус:** Открыта

---

### TASK-UI-013: Прямые tailwind-цвета → token-aliases (UI_UX_AUDIT P2.10)

- **Исполнитель:** UI Engineer
- **Приоритет:** P2
- **Оценка:** 2ч
- **Источник:** UI_UX_AUDIT P2 №10. Использование `text-red-400`, `text-emerald-400`, `text-blue-500` напрямую вместо `text-danger`, `text-success`, `text-accent`.
- **Описание:** Grep `text-(red|emerald|green|blue|amber|violet|cyan)-\d+` → заменить на семантический alias. Исключение: палитра графиков (recharts inline) — там оставить hex с комментарием.
- **Критерии готовности:**
  - [ ] `grep -rn "text-\(red\|green\|emerald\|blue\)-[0-9]" frontend/src/pages frontend/src/components` — 0 матчей (только в Icon.tsx если иконки имеют свой цвет, и в recharts inline)
  - [ ] То же для `bg-` и `border-` semantic
  - [ ] Семантика не сломана: `text-danger` остаётся красным, `text-success` зелёным
- **Зависимости:** TASK-UI-001
- **Статус:** Открыта

---

### TASK-UI-014: CSS variables → Tailwind tokens consistency (UI_UX_AUDIT P2.17)

- **Исполнитель:** UI Engineer
- **Приоритет:** P2
- **Оценка:** 1.5ч
- **Источник:** UI_UX_AUDIT P2 №17. Большая часть уже сделана (styles.css определяет CSS-vars, tailwind.config.js алиасит). Audit: нет ли расхождений «цвет в css-var, но не в tailwind» или наоборот.
- **Описание:** Сравнить `styles.css` `:root` блок и `tailwind.config.js` `colors` — каждая CSS-var должна иметь Tailwind alias, и наоборот. Несинхронизированные — синхронизировать или удалить.
- **Критерии готовности:**
  - [ ] Каждой `--var` в `:root` соответствует Tailwind class
  - [ ] Каждой Tailwind color value `var(--...)` соответствует определение в `:root`
  - [ ] `DESIGN_SYSTEM.md §3` — таблица обновлена если что-то изменилось
- **Зависимости:** —
- **Статус:** Открыта

---

## Sprint 3 — Pro Features (нед. 4-11.06)

### TASK-UI-015: Command palette `⌘K` через cmdk (UI_UX_AUDIT P3.9)

- **Исполнитель:** UI Engineer
- **Приоритет:** P3
- **Оценка:** 3ч
- **Источник:** UI_UX_AUDIT P3 №9. `CommandPalette.tsx` уже существует (см. inventory) — проверить что подключён cmdk и расширен на все pages.
- **Описание:** Audit `CommandPalette.tsx`. Команды: переход на любую page (47 штук), быстрый action (создать заявку plan-edit, открыть глоссарий, переключить sidebar, открыть docs). `⌘K` / `Ctrl+K` глобально.
- **Критерии готовности:**
  - [ ] `⌘K` / `Ctrl+K` открывает палитру с любой страницы
  - [ ] В палитре: 47 navigation-команд (из GROUPS в Layout.tsx) + 5-10 actions
  - [ ] Fuzzy search через cmdk встроенно
  - [ ] ESC закрывает, Enter переходит
- **Зависимости:** —
- **Статус:** Открыта

---

### TASK-UI-016: Единая «brand recharts theme» (UI_UX_AUDIT P3.12 + DESIGN_SYSTEM §8)

- **Исполнитель:** UI Engineer
- **Приоритет:** P3
- **Оценка:** 2ч
- **Источник:** DESIGN_SYSTEM §8. Сейчас grid/axis/tooltip-style повторяется во многих файлах. Вынести в helper `chartTheme.ts`.
- **Описание:** Создать `frontend/src/lib/chartTheme.ts` с константами: `GRID_PROPS`, `AXIS_PROPS`, `TOOLTIP_STYLE`, `LEGEND_STYLE`, `CHART_COLORS` (8 цветов из DESIGN_SYSTEM §3.4). Использовать в `Dashboard.tsx`, `PnL.tsx`, `AdsHeatmap.tsx`, `Funnel.tsx`, `MetricDrilldownModal.tsx`, и где ещё recharts.
- **Критерии готовности:**
  - [ ] `frontend/src/lib/chartTheme.ts` создан
  - [ ] Минимум 5 файлов мигрированы (где используется recharts)
  - [ ] Inline `stroke="#262a35"` / `fill: "#8b93a3"` заменены на `GRID_PROPS.stroke` / `AXIS_PROPS.tick.fill`
- **Зависимости:** TASK-UI-001
- **Статус:** Открыта

---

### TASK-UI-017: Условная окраска значений + ▲/▼ inline (UI_UX_AUDIT P3.14)

- **Исполнитель:** UI Engineer
- **Приоритет:** P3
- **Оценка:** 2ч
- **Источник:** UI_UX_AUDIT P3 №14. В таблицах значения изменений (WoW / MoM) сейчас часто просто число — без цвета и стрелки. KpiCard уже делает, distribute на таблицы.
- **Описание:** Создать `<DeltaCell value={number} lower_is_better?={bool} />` — компонент для inline-дельты в таблицах. Цвет: success/danger по знаку (+ инверсия для lower_is_better). Стрелка ▲▼ из `arrowForDelta()`.
- **Критерии готовности:**
  - [ ] `frontend/src/components/DeltaCell.tsx` создан
  - [ ] Использован в: PnL (WoW колонка), Plans (отклонение от плана), Units (WoW), ABC (доля)
  - [ ] Семантика инверсии работает для DRR, returns, commission в Units
- **Зависимости:** TASK-UI-004 (после моно-чисел)
- **Статус:** Открыта

---

### TASK-UI-018: AlertsBar minimalist redesign (UI_UX_AUDIT P3.15)

- **Исполнитель:** UI Engineer (с консультацией Designer'а)
- **Приоритет:** P3
- **Оценка:** 3ч
- **Источник:** UI_UX_AUDIT P3 №15. Сейчас AlertsBar — большие цветные блоки. Минималистичная версия: маленькая полоса под header'ом с счётчиком и expand.
- **Описание:** Перерисовать `AlertsBar.tsx`: collapsed-state = 1 строка «3 алерта: COGS missing, реклама paused, recon mismatch» с иконкой и chevron. Click → expand list. Серверный ack уже работает (миграция 0049 + TASK-DEV-020) — кнопка «прочитано» на каждом алерте.
- **Критерии готовности:**
  - [ ] Collapsed-mode по умолчанию (не занимает 200px высоты)
  - [ ] Expand-state с полным списком + ack-кнопки
  - [ ] Иконки lucide (`alert-triangle`, `info`) — не эмодзи
  - [ ] Цветовая семантика: warn / danger / info (subtle backgrounds, не FULL красный fill)
- **Зависимости:** TASK-UI-003 (эмодзи аудит должен быть пройден)
- **Статус:** Открыта

---

### TASK-UI-019: Micro-animations 120-200ms (UI_UX_AUDIT P3.16 + DESIGN_SYSTEM §9)

- **Исполнитель:** UI Engineer
- **Приоритет:** P3
- **Оценка:** 1.5ч
- **Источник:** DESIGN_SYSTEM §9 — только `transition-colors duration-150 ease-out`. Audit что соблюдается: нет лишних `transition-all`, нет `duration-500`, нет spring/bounce.
- **Описание:** Grep `transition-` по pages/components, найти отклонения от стандарта.
- **Критерии готовности:**
  - [ ] `grep -rn "transition-all" frontend/src` — 0 (заменить на `transition-colors` / `transition-opacity`)
  - [ ] `grep -rn "duration-\(3\|5\|7\)00" frontend/src` — 0 (все > 200ms убрать или оправдать комментом)
  - [ ] Нет `animate-bounce`, `animate-spin` (кроме loading-spinner)
  - [ ] `prefers-reduced-motion` уважается (уже глобально в styles.css)
- **Зависимости:** —
- **Статус:** Открыта

---

### TASK-UI-020: Density toggle для Units (UI_UX_AUDIT P3.20)

- **Исполнитель:** UI Engineer
- **Приоритет:** P3
- **Оценка:** 2ч
- **Источник:** UI_UX_AUDIT P3 №20 + DESIGN_SYSTEM §2.4 «Density without claustrophobia».
- **Описание:** На странице `/units` (самая широкая таблица) добавить переключатель «Compact / Comfortable» (3 уровня: dense / compact / comfortable). Меняет row-height и padding. Persist в localStorage.
- **Критерии готовности:**
  - [ ] Toggle в header'е таблицы (3 кнопки или dropdown)
  - [ ] Уровни: `dense` (row=28px, padding-y=2), `compact` (default, row=36px, py=4), `comfortable` (row=44px, py=6)
  - [ ] Persist в `localStorage["units.density.v1"]`
  - [ ] Применимо также к ABC и Supply если время позволит
- **Зависимости:** TASK-UI-007 (sticky-header)
- **Статус:** Открыта

---

## Backlog (за пределами 3-недельного спринта)

### TASK-UI-021: Visual regression — Playwright screenshots для топ-10 страниц

- **Приоритет:** P3 (когда DESIGN_SYSTEM compliance закрыта)
- **Описание:** После того как Sprint 1-3 закроются и UI стабилен — base-line screenshots Playwright'ом для 10 ключевых страниц. Pre-commit / CI сравнивает diff.

### TASK-UI-022: Light theme implementation

- **Приоритет:** P3 (не в текущем фокусе — DESIGN_SYSTEM.md §11 явно «не делаем»)
- **Описание:** Только если будет explicit user-запрос. Не приоритет.

### TASK-UI-023: Storybook для компонентов

- **Приоритет:** P3 (overkill для single-tenant — но если придёт multi-tenant)
- **Описание:** Catalog `components/` с состояниями.

---

## Жизненный цикл / DoD

См. [`ui-engineer.md`](ui-engineer.md) § «Жизненный цикл задачи».

Перед `Выполнено`:

- [ ] Все критерии готовности `[x]`
- [ ] `tsc --noEmit` чисто
- [ ] Smoke на 2-3 страницах (Dashboard + затронутые) — без регрессов и красного в console
- [ ] Если меняется inventory компонентов / число pages / правило → `DESIGN_SYSTEM.md §13` обновлён
- [ ] Если меняется правило дизайн-системы → **остановись**, заведи TASK-ART-NNN

После `Выполнено`:

- [ ] Статус `Выполнено — YYYY-MM-DD` в этом файле
- [ ] Handoff на Release Manager (не бампать самому)
- [ ] Если был claim — release: `./scripts/claim.sh release TASK-UI-NNN`
