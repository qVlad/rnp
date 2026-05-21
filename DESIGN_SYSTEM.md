# РНП — Дизайн-система

> **Source of truth по визуальной идентичности и UI-паттернам.** Раздел
> «Визуальная концепция» в [`agents/art-director.md`](agents/art-director.md)
> теперь ссылается на этот файл; любая правка токенов/принципов делается
> здесь и синхронизируется с `frontend/src/styles.css` + `frontend/tailwind.config.js`.
>
> Контекст: единый автор (Claude), single-tenant SaaS-аналитика для WB-селлера.
> Не маркетинговый продукт — закрытый рабочий инструмент финдира/РОПа/менеджера.
>
> Связанные доки: [`UI_UX_AUDIT.md`](UI_UX_AUDIT.md) (аудит 2026-05-15),
> [`COMPETITIVE_EGGHEADS.md`](COMPETITIVE_EGGHEADS.md),
> [`COMPETITIVE_MPUMP.md`](COMPETITIVE_MPUMP.md),
> [`COMPETITIVE_TRUESTATS.md`](COMPETITIVE_TRUESTATS.md),
> [`COMPETITIVE_EVIRMA.md`](COMPETITIVE_EVIRMA.md).

---

## 1. Visual DNA

**Linear × Stripe Dashboard × Bloomberg Terminal**, проверенный временем
от UI_UX_AUDIT.md 2026-05-15 и подтверждённый конкурентным анализом
четырёх WB-аналитик.

| От Linear | От Stripe | От Bloomberg |
|---|---|---|
| 8px-grid, hairline borders | финансовый «sober»: цифры главные | density-mode: 30 SKU × 25 колонок без скролла |
| моно-цифры в таблицах | sticky breadcrumb-нав | моно-шрифт + tabular-nums везде |
| keyboard-first (⌘K, `[` сворачивает sidebar) | subtle gradient charts | минимум whitespace, максимум сигнала |

**Что мы НЕ делаем (с фиксированных referent'ов):**

- **НЕ Notion-эстетика** — у нас нет «уютного контента», есть числа и алерты.
- **НЕ Bitrix / 1С** — UI должен быть лёгким, а не enterprise-overload.
- **НЕ Hamster Kombat / геймификация** — это финансовый инструмент,
  доверие важнее «весёлости».
- **НЕ копируем MPump** — у них sidebar на 16+ пунктов и палитра тегов из
  14 эмодзи; первое отвергаем (см. §2.2), второе уже взяли (см. §6.5).

---

## 2. Принципы (5 наблюдений от WB-конкурентов)

### 2.1. Dark-first с холодным violet-акцентом — отраслевой стандарт

MPump прямо подтверждает `#8B5CF6` violet + `#0B0F19` фон (PWA standalone).
TrueStats / Eggheads не раскрывают палитру, но Tailwind-стек намекает на
похожую. У нас — `--accent #8b6eff` (близко к MPump), `--bg #0a0c10`
(чуть темнее). **Light theme — не делаем** (см. §11).

### 2.2. Sidebar плоский на 20 пунктов — отраслевая норма, но против нашего ICP

MPump (16+) и Eggheads (20+) держат весь функционал в одной плоской
панели — это удобно маркетологу-операционисту, но не финдиректору.
Наш ICP хочет 4-7 крупных доменных групп с глубоким drill.

**Действие:** оставляем sidebar (а не horizontal top-bar — см. UI_UX_AUDIT
P1.2), но **группируем** пункты заголовками-разделителями. Текущее
состояние `Layout.tsx`: 8 групп («Обзор / Налоги и деньги / SKU и продажи
/ Маркетинг / Расходы / Контроль / Справка / Админка»). Сохраняем
группировку, не растим количество групп сверх 9.

### 2.3. Эмодзи-теги — берём как стандарт WB-ниши

MPump единственный кто сделал систему 14 эмодзи-меток на карточку; в их
обучающих видео это пункт #4 онбординга. **Это user-привычка ниши.**

У нас уже есть `product_tags` (миграция 0052) с seed-набором 6 эмодзи
(🏆/⭐/📦/🆕/🚨/🔥). Это правильный объём (не 14) — расширять только
по конкретному запросу.

**Правило:** эмодзи разрешены **только** в product-tags. В навигации,
кнопках, состояниях, заголовках — **только lucide-иконки** (см. §6.4).
Это сознательная граница: tag = «лёгкое визуальное», UI-chrome = «деловое».

### 2.4. Bloomberg-style плотность > Notion-style воздух

TrueStats: 16 KPI + 50 метрик + drill 4 уровня на одном экране. MPump: 13
типов алертов + heatmap + детализация артикула одновременно. Финдиректор
хочет всё на одном экране без скролла.

**Действие:**
- Базовый шрифт **13px** (`text-sm`, не `text-base`).
- KPI grid: 4-6 в ряду на 1440px (а не 3 как в Stripe).
- Таблицы: `density: compact` по умолчанию, opt-in `comfortable`.
- Whitespace: `gap-3` (12px) внутри карточек, `gap-4` (16px) между секциями.
- Минимум декора: **никаких** card-glows, никаких градиентных фонов,
  никаких иллюстраций empty-state.

### 2.5. Heatmap как hero-визуализация — отраслевой консенсус

TrueStats и MPump делают heatmap «дни × метрика» главным паттерном для
рекламы и динамики. У нас есть `/ads-heatmap`. **Расширяем heatmap как
универсальный язык**: план-факт по дням × брендам, аномалии P&L,
выкупаемость по складам × дням. Это даёт мгновенную узнаваемость для
пользователей мигрирующих от конкурентов.

---

## 3. Цветовые токены (актуальное состояние)

> **Source of truth:** `frontend/src/styles.css` (CSS variables) +
> `frontend/tailwind.config.js` (Tailwind aliases). НЕ хардкодить hex
> в JSX — только через `text-fg` / `bg-surface` / `border-border` или
> `var(--fg)` в inline-стилях для recharts.

### 3.1. Поверхности (5 уровней — иерархия глубины)

| Token | Hex | Применение |
|---|---|---|
| `--bg` / `bg-bg` | `#0a0c10` | Канва (`<body>`, основной фон страницы) |
| `--surface` / `bg-surface` | `#11141b` | Карточки (`.card`), инпуты, кнопки `.btn` |
| `--surface-2` / `bg-surface-2` | `#171b24` | thead, hover-row, sticky-bg, tooltip-фон |
| `--border` / `border-border` | `#252a36` | 1px hairline divider'ы |
| `--border-hi` / `border-border-hi` | `#363c4b` | hover-border, focus-визуальные подсветки |

**Правило:** не плодить 6-й уровень. Если нужен «ещё темнее» — используй
прозрачность (`bg-bg/40`), а не новый цвет.

### 3.2. Текст (3 уровня)

| Token | Hex | Контраст vs `--bg` | Применение |
|---|---|---|---|
| `--fg` / `text-fg` | `#e8eaef` | 14.8:1 (AAA) | Body, заголовки, основные значения |
| `--muted` / `text-muted` | `#8b93a3` | 5.1:1 (AA) | Лейблы, подсказки, secondary |
| `--faint` / `text-faint` | `#5b6271` | 3.0:1 (AA Large) | Captions, group-labels uppercase, disabled |

### 3.3. Семантика (4 пары — base + subtle)

| Token | Hex | Subtle (12% alpha) | Применение |
|---|---|---|---|
| `--accent` | `#8b6eff` | `--accent-subtle` | Primary CTA, активный nav-link, ссылки, focus-ring |
| `--success` | `#34d399` | `--success-subtle` | Положительные числа (рост выручки/прибыли) |
| `--warn` | `#fbbf24` | `--warn-subtle` | Предупреждения, аномалии без блокера |
| `--danger` | `#f87171` | `--danger-subtle` | Отрицательные числа, ошибки, deadlocks |

**Семантика инверсии — `LOWER_IS_BETTER`:** для метрик где рост = плохо
(ДРР, реклама, возвраты, комиссии WB, логистика, хранение) — цвет
дельты инвертирован. Источник истины — `frontend/src/components/KpiCard.tsx`
константа `LOWER_IS_BETTER`. При добавлении новой такой метрики обнови
оба места (карточка + любой кастомный рендер вне `KpiCard`).

### 3.4. Палитра графиков (recharts) — 8 цветов в матовом регистре

| Назначение | Hex | Tailwind ref |
|---|---|---|
| Revenue / положительная серия | `#34d399` | emerald-400 |
| Orders / count | `#f59e0b` | amber-500 |
| Ad cost / маркетинг | `#a78bfa` | violet-400 |
| Profit / cyan серия | `#22d3ee` | cyan-400 |
| Commission / WB удержания | `#f87171` | red-400 |
| Logistics | `#fb923c` | orange-400 |
| Storage | `#fbbf24` | amber-400 |
| OPEX / прочее | `#64748b` | slate-500 |
| Sparkline default (нейтральная) | `#60a5fa` | blue-400 |

**Правило:** при новом графике — выбирай из этого списка по
семантической близости (выручка-emerald, расходы-red/orange-семья,
рекламы-violet). НЕ генерировать новые hex'ы — это распыляет язык.

---

## 4. Типографика

### 4.1. Шрифты

- **Body:** `Inter Variable, Inter, system-ui, sans-serif`
  — variable-axis даёт точные веса 400/500/600 без подгрузки 3 файлов.
- **Числа:** `JetBrains Mono Variable, JetBrains Mono, Menlo, monospace`
  — для всех **числовых ячеек** (KPI, таблицы, tooltip'ы) с `tabular-nums`.
- **Feature settings:** `cv02 cv03 cv04 cv11` (Inter character variants
  — открытая `4`, прямая `g`, читаемая `1`).

### 4.2. Шкала размеров

| Token | Px / line-height | Применение |
|---|---|---|
| `text-micro` | 11 / 14 | Captions, индексы, мелкие меты |
| `text-tiny` | 12 / 16 | KPI label (uppercase), нижние подписи, badges |
| `text-sm` (default body) | 14 / 20 | **Основной body** для всего dashboard |
| `text-base` | 16 / 24 | Заголовки секций в формах |
| `text-h3` | 18 / 26 | `<h2>` (заголовок раздела внутри страницы) |
| `text-h2` | 24 / 32 | `<h1>` (заголовок страницы) |
| `text-h1` | 32 / 40 | Hero-KPI value на дашборде |

**Веса:** 400 (body), 500 (medium, числа в KPI), 600 (semibold, headings).
Bold (700+) — не использовать; перебирает плотность.

### 4.3. Числа — обязательно

- Любая цифра в DOM → `font-mono tabular-nums` (моно класс автоматически
  добавляет `font-variant-numeric: tabular-nums` через `@layer components`).
- Форматирование — **только через `frontend/src/lib/format.ts`** (`fmtRub`,
  `fmtNum`, `fmtPct`, `fmtChange`, `formatValue`). Никаких local
  `.toFixed(0) + " ₽"` — теряется ru-RU разделитель тысяч (`1 234 567`).
- Дельта направления — `▲` / `▼` (см. `arrowForDelta()`). Не `↑↓` и не
  unicode-эмодзи.

### 4.4. Заголовки страниц

Любая страница — через `<PageHeader title="..." subtitle="..." actions={...} />`
(`frontend/src/components/PageHeader.tsx`). Не лепить inline `<h1 class="...">`.

---

## 5. Layout, spacing, radii

| Параметр | Значение | Где |
|---|---|---|
| Sidebar width (expanded) | `240px` | `Layout.tsx` |
| Sidebar width (collapsed) | `60px` | `[` — toggle, persist в `localStorage["sidebar.collapsed.v1"]` |
| Main padding | `px-6 py-6` (24px) | `Layout.tsx` `<main>` |
| Card padding | `p-4` (16px) | `.card` |
| Card radius | `rounded-lg` (8px) | `.card` |
| Button padding | `px-3 py-2` (12/8px) | `.btn` / `.btn-primary` |
| Input padding | `px-3 py-2` (12/8px) | `.input` |
| Grid gap (внутри секции) | `gap-3` (12px) | KPI rows, form fields |
| Grid gap (между секциями) | `gap-4` (16px) | Между `<section>` блоками |
| Border width | `1px` everywhere | hairline, не `2px` |
| Focus ring | `2px solid var(--focus-ring)`, `outline-offset: 2px` | global `*:focus-visible` |

**Container width:** не ограничиваем `max-w` — наша целевая ширина
**1280-1920px** (workstation). На < 1024px ломается осознанно — мобильная
адаптация не в скоупе (см. §11).

---

## 6. Inventory компонентов (что есть и как использовать)

Все live в `frontend/src/components/`. Это **canonical-список** —
не дублировать функционал в pages.

### 6.1. Карточки и KPI

| Компонент | Когда |
|---|---|
| `KpiCard` (`KpiCard.tsx`) | Все KPI. Варианты `hero` / `default` / `compact`. Драйв drill-down через `DRILLDOWN_METRIC` мапу — обновляй её при добавлении новой кликабельной метрики. |
| `TodayVsYesterdayStrip` | Полоса «сегодня vs вчера» под header'ом дашборда. |
| `ManagerPlanProgressCard` | Прогресс плана для менеджера — Топ-5/Все toggle (TASK-DEV-015). |
| `CompositionBar` | Стэкнутая полоска внутри KPI (decomposition по сегментам). |
| `CustomMetricsCard` / `CustomMetricsSection` | Custom-метрики формулой (миграция 0050). |

### 6.2. Таблицы и данные

| Компонент | Когда |
|---|---|
| `ColumnVisibility` (`ColumnVisibility.tsx`) | Toggle колонок в длинных таблицах. Обязательно для > 8 колонок. |
| `DraggableHeader` | DnD-перестановка колонок (Units, Plans). |
| `ProductTagChips` | Рендер эмодзи-тегов на nm_id. |
| `TagFilterDropdown` | Фильтр по тегам в таблице/списке. |
| `ViewPresetsBar` | Сохранённые фильтры (миграция 0029) — sharable links. |
| `PaymentOrdersTable` | Спец-таблица плат. документов с per-regime exclude. |
| `PnLByBrandView` / `PnLCardsView` | Альтернативные view P&L. |

### 6.3. Навигация и chrome

| Компонент | Когда |
|---|---|
| `Layout` | Корневой shell — sidebar + outlet. Все pages внутри. |
| `PageHeader` | Заголовок любой страницы (title + subtitle + actions). |
| `CommandPalette` | `⌘K` глобальный поиск/навигация. Регистрируй новые pages здесь. |
| `SyncStatusIndicator` | Точка-индикатор в sidebar (cooldown / running / errors). |
| `ManagerBrandsBanner` | Баннер «вы видите только бренды X, Y» для manager-роли. |
| `ToastHost` | Toast-уведомления глобально. |
| `VersionBadge` | Версия в footer sidebar. |

### 6.4. Формы и контролы

| Компонент / класс | Когда |
|---|---|
| `.btn` / `.btn-primary` | Все кнопки. НЕ создавать inline `<button class="bg-... px-...">`. |
| `.input` | Все text/number/select inputs. |
| `DateRangePicker` | **Любой** выбор периода (CLAUDE.md UI conventions). Не использовать `<input type="date">` для диапазонов. |
| `Icon` (`Icon.tsx`) | Все иконки — обёртка над `lucide-react`. Размер 11px (inline) / 14px (default в navlink) / 16px (default в кнопках) / 20px (заметные). |
| `HelpIcon` | `?` рядом с лейблом → ссылка на `/glossary#<key>`. |

### 6.5. Эмодзи-теги (граница использования)

Эмодзи разрешены **только в `product_tags`** (см. §2.3). Seed-набор
6 штук создаётся при init tenant'а: 🏆 / ⭐ / 📦 / 🆕 / 🚨 / 🔥. Расширение
— только по запросу пользователя, не proactively. В навигации, кнопках,
KPI-лейблах, состояниях — **только lucide-иконки** через `Icon.tsx`.

### 6.6. States (loading / empty / error)

`frontend/src/components/states.tsx` — три компонента:

- `<Skeleton />` — placeholder во время загрузки (shimmer animation —
  см. `.skeleton` класс в `styles.css`).
- `<EmptyState />` — пустые таблицы/списки. Текст + lucide-иконка,
  **без иллюстраций**.
- `<ErrorState />` — ошибки запросов. Текст + retry-кнопка.

**Правило:** в любой странице со списком/таблицей — обязательны все три
состояния. Не оставлять «голую» пустоту или React Suspense fallback'и.

---

## 7. Иконки

- **Источник:** `lucide-react`. **Обёртка:** `frontend/src/components/Icon.tsx`.
  Регистрируй новые иконки в map'е этого файла, не импортируй `lucide-react`
  напрямую в pages.
- **Запрещено:** heroicons, phosphor, react-icons, font-awesome — не подключать.
- **Эмодзи в UI-chrome:** запрещены (см. §2.3 / §6.5).
- **Custom inline SVG:** только для бренд-ассетов (favicon, logo-точка).
- **Размеры:** 11 / 14 / 16 / 20 — см. §6.4. Дробных размеров (13, 18) не
  использовать.

---

## 8. Графики (recharts) — единый стиль

Все графики используют общие settings — выноси в helper если повторяется
3+ раз.

```ts
// Сетка
<CartesianGrid stroke="#252a36" strokeDasharray="3 3" vertical={false} />
// Ось
<XAxis tick={{ fontSize: 11, fill: "#8b93a3" }} axisLine={false} tickLine={false} />
<YAxis tick={{ fontSize: 11, fill: "#8b93a3" }} axisLine={false} tickLine={false} />
// Tooltip
<Tooltip contentStyle={{
  background: "#171b24",
  border: "1px solid #252a36",
  borderRadius: 6,
  fontSize: 12,
}} />
// Легенда
<Legend wrapperStyle={{ fontSize: 12, color: "#8b93a3" }} />
```

**Цвета линий/баров — только из §3.4** (8-цветная палитра). Не генерируй
новые hex'ы.

**Sparkline (inline в карточках/таблицах):** одна линия, без осей, без
сетки, цвет `#60a5fa`. Высота 24-32px.

**Heatmap (см. §2.5 как hero):** ячейка 12×12 / 16×16, scale через
opacity на `--accent` (для нейтральных метрик) или через bicolor
`success → danger` (для метрик с целевым значением). Tooltip-style — тот
же что и у линейных графиков.

---

## 9. Состояния интерактивных элементов

| State | Визуал | Где |
|---|---|---|
| default | base color | `.btn` / `.input` / `.nav-link` |
| hover | `hover:border-accent` (бордюр) ИЛИ `hover:bg-surface-2` (фон) — не оба сразу | `.btn`, `.nav-link`, table rows |
| focus-visible | `2px solid var(--focus-ring)` + `outline-offset: 2px` | глобально (см. `styles.css`) |
| focus (mouse) | без видимого outline (`*:focus:not(:focus-visible)`) | глобально |
| active (nav) | `border-l-2 border-accent` + `bg-accent-subtle` + `text-fg` | `Layout.tsx` NavLink |
| disabled | `opacity-40 cursor-not-allowed`, hover не срабатывает | `.btn`, `.input` |
| loading | `<Skeleton />` (shimmer) либо spinner внутри кнопки | `states.tsx` |
| error | `<ErrorState />` либо красный border + helper-text | `states.tsx` |

**Анимации:** только `transition-colors duration-150 ease-out` для hover'ов.
Никаких spring'ов, bounce'ов, длинных fade'ов (>200ms) — убивают доверие
к финпродукту. `prefers-reduced-motion` уважается глобально (см. media-query
в `styles.css`).

---

## 10. Accessibility (минимум, не максимум)

В скоупе:

- [x] `focus-visible` глобально с видимым outline (есть в `styles.css`)
- [x] `prefers-reduced-motion` (есть)
- [x] Контрасты `--fg` AAA, `--muted` AA — выполнено
- [x] `tabular-nums` на числах для screen reader'ов и выравнивания
- [ ] `aria-label` на icon-only кнопках — на местах есть, **проверять для каждой новой**
- [ ] Keyboard navigation в таблицах — частично (TanStack Table) — нет цели до feedback'а

Не в скоупе сейчас:

- WCAG AAA для всех элементов (только body/hero, по UI_UX_AUDIT)
- Полноценный screen-reader support (single-tenant, известные пользователи)
- High-contrast theme
- Voice-control / dictation

---

## 11. Что НЕ делаем (явные границы)

1. **Light theme** — финдиректор работает 5+ часов, dark выигрывает.
2. **Mobile-first / mobile-responsive** — workstation 1280-1920px, < 1024px
   ломается осознанно.
3. **i18n / RTL** — single-tenant, RU-only.
4. **Иллюстрации, маскоты, персонажи** — мы не геймифицируем финансы.
5. **Custom шрифты сверх Inter+JetBrains Mono** — больше — раздувает bundle.
6. **Иконочные библиотеки сверх lucide-react** — heroicons/phosphor/etc. запрещены.
7. **Spring-анимации, bounce, длинные transitions (>200ms)** — убивают
   доверие к финпродукту.
8. **Drag-and-drop редактор дашборда** — путь в RUR-Grafana (UI_UX_AUDIT отмечает
   что пользователь просил, но art-director рекомендует отказаться).
9. **AI-чат в UI** — отдельный продукт, не дашборд.
10. **Marketing-сайт / landing** — продукт закрытый, лендинг не нужен.
11. **Эмодзи в UI-chrome** — только в `product_tags`. См. §2.3 / §6.5.
12. **Светлая палитра в графиках** (например, белые линии на чёрном) —
    выжигает глаза на тёмной теме, используем матовые из §3.4.

---

## 12. Процесс изменения дизайн-системы

### Малое изменение (одна метрика, одна иконка, один токен subtle)

1. Заводишь TASK-ART-NNN в `agents/tasks-art.md`.
2. Spec в комментарии задачи: что меняется, где, почему.
3. Правишь этот файл (`DESIGN_SYSTEM.md`) — раздел, относящийся к изменению.
4. Если меняется CSS-token — заводишь TASK-DEV-NNN с конкретным
   значением для `styles.css` / `tailwind.config.js`.
5. Передаёшь Developer'у. После имплементации отмечаешь TASK-ART-NNN
   `Выполнено`.

### Бренд-уровень (палитра, типографика, лого, favicon)

1. **Согласование с пользователем — обязательно** (бренд-уровень).
2. WCAG-аудит через `visual-design-lead` субагент: контрасты body
   ≥ AA 4.5:1, hero ≥ AAA 7:1.
3. Превью на 3-5 ключевых страницах (Dashboard, P&L, Units, Tariffs,
   AdsHeatmap) — скриншот до/после.
4. Обновление этого файла + spec для Developer'а.
5. Bump версии — minor (UI breaking-ish даже без API-breakage).

### Что НЕ требует TASK-ART

- Использование уже определённых токенов в новой странице (это работа
  Developer'а — выбрать `.card` / `.btn` / `text-success` правильно).
- Добавление нового lucide-иконки в `Icon.tsx` (Developer добавляет
  при необходимости — это не бренд-уровень).
- Новый recharts-график при условии что цвета берутся из §3.4.

---

## 13. Снимок состояния на 2026-05-21

| Параметр | Значение | Источник |
|---|---|---|
| Версия шрифтов | Inter Variable + JetBrains Mono Variable | `styles.css` |
| Иконки | `lucide-react` через `Icon.tsx` | `Icon.tsx` |
| Цветовых токенов | 5 surfaces + 3 text + 4 semantic-пары + 1 focus | `styles.css` |
| Цветов графиков | 8 (см. §3.4) | this doc |
| Компонентов в `components/` | 33 | `ls components/` |
| Страниц в `pages/` | 47 | `ls pages/` |
| Sidebar группы | 8 («Обзор / Налоги / SKU / Маркетинг / Расходы / Контроль / Справка / Админка») | `Layout.tsx` |
| Эмодзи-тегов seed | 6 (🏆⭐📦🆕🚨🔥) | миграция 0052 |
| Hero/default/compact KPI варианты | 3 | `KpiCard.tsx` |
| Density-default таблиц | compact | UI_UX_AUDIT принцип |

Следующий аудит этой системы — после **20 новых TASK-DEV** или **3 месяцев**
(что наступит раньше). Триггеры внеплановой ревизии: новый ICP, переход
multi-tenant, добавление light-theme в скоуп, переход на другую chart-lib.
