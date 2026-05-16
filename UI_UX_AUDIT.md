# UI/UX Аудит сервиса РНП

> Полный отчёт art-director агента от 2026-05-15. Reference DNA: **Linear × Stripe Dashboard × Bloomberg Terminal**.

## 1. Сводка

### Хорошо (5 пунктов)
1. Тёмная тема выбрана адекватно для финансового инструмента
2. Семантическая цветовая система задана корректно
3. Сильная функциональная база компонентов (`DateRangePicker`, `ColumnVisibility`, `ViewPresetsBar`)
4. Толковая работа с tooltip'ами и глоссарием
5. TanStack Table в `Units.tsx`

### Критично плохо (5 пунктов)
1. **Навигация деградировала в свалку** — 32 пункта меню в horizontal flex-wrap
2. **Дизайн-токены сломаны** — `bg-card`, `bg-bg-hover` используются но не определены в Tailwind
3. **`.input` класс — фантом** — определён только inline в Login.tsx, используется на 149 местах
4. **Иконки как emoji** — 16 разных эмодзи, выглядят как hackathon-MVP
5. **Accessibility = 0** — focus-visible не используется, aria-labels единичны

**Общая оценка premium-ness: 4/10.**

## 2. Visual Identity Vision

**Linear × Stripe Dashboard × Bloomberg Terminal:**
- От Linear: 8px-grid, монотипограф для табличных чисел, hairline divider'ы, keyboard-first
- От Stripe: «финансовый sober» — цифры главные, sticky breadcrumb-нав, subtle gradient charts
- От Bloomberg: density-mode для Units (30 SKU × 25 cols)

**Принципы:**
1. **Density without claustrophobia** — мелкий шрифт (13px base), 24px между блоками
2. **Numbers are first-class citizens** — tabular-nums везде, JetBrains Mono для цифр
3. **One accent, three semantics** — purple accent + success/warn/danger
4. **Premium = restraint** — убрать emoji, убрать декор
5. **Tables are the product** — не «UI-элемент», а **рабочая поверхность**

## 3. Палитра / Tokens

**Изменения:**
- `bg #0b0d12 → #0a0c10` (чуть темнее канва)
- `surface #13161d → #11141b`
- Новый `surface2 #171b24` (thead, hover-row, sticky-bg)
- `muted #7d8492 → #8b93a3` (повысить контраст до AA 5.1:1)
- `accent #7c5cff → #8b6eff` (выше насыщенность)
- `success #3ddc97 → #34d399` (финансово-зелёный, не мятный)

**Шкала шрифтов:** 11 / 12 / 13 (base) / 15 / 18 / 24 / 32

## 4. Задачи (20 шт, приоритезированы)

### P1 (5 задач) — Неделя 1
| # | Задача | Estimate |
|---|---|---|
| 1 | Починить дизайн-токены и `.input` класс | S1 |
| 2 | Сайдбар вместо горизонтальной шапки | S2 |
| 3 | Заменить emoji на SVG (Lucide / Phosphor) | S1 |
| 4 | Числовая типографика (mono для всех цифр) | S1 |
| 7 | Глобальный period context | S2 |

### P2 (8 задач) — Неделя 2
| # | Задача | Estimate |
|---|---|---|
| 5 | Sticky-header в длинных таблицах | S1 |
| 6 | Loading / Empty / Error states унифицировать | S2 |
| 8 | Дашборд: Hero-KPI + secondary | S2 |
| 10 | Чистка прямых tailwind-цветов | S1 |
| 11 | KpiCard tooltip — Popover with collision detection | S1 |
| 13 | Accessibility-минимум (focus-visible, aria-label) | S2 |
| 17 | CSS variables → Tailwind tokens | S1 |
| 19 | `<PageHeader>` стандартизация | S1 |

### P3 (7 задач) — Неделя 3
| # | Задача | Estimate |
|---|---|---|
| 9 | Command palette `⌘K` (cmdk lib) | S2 |
| 12 | Единая «brand recharts theme» | S1 |
| 14 | Условная окраска значений (inline-color, ▲/▼) | S1 |
| 15 | AlertsBar minimalist redesign | S1 |
| 16 | Микроанимации (120-200ms) | S1 |
| 18 | Единый `<HelpIcon>` стандарт | S1 |
| 20 | Density toggle на Units | S2 |

## 5. Что НЕ делать

1. **Не делать light theme** — dark выигрывает на 5+ часах работы
2. **Не добавлять spring-анимации** — убивают доверие к финпродукту
3. **Не делать drag-and-drop дашборда** — путь в RUR-Grafana (заметка: пользователь попросил всё-таки сделать, см. ниже)
4. **Не пытаться «как Bitrix» / «как 1С»**
5. **Не вкладываться в брендинг** (single-tenant, ≤5 юзеров)
6. **Не делать mobile-first** — workstation 1280px
7. **Не делать i18n / RTL** пока single-tenant
8. **Не переписывать TanStack Table / recharts**
9. **Не плодить компонентные библиотеки** — Radix/cmdk/lucide точечно
10. **Не делать AI-чат в UI**

## Roadmap → 3 недели работы дизайнера-в-коде = премиум-восприятие

- **Неделя 1 (P1):** tokens, sidebar, icons, mono-numbers, global-period → +3 балла к premium (4→7)
- **Неделя 2 (P2):** sticky-tables, states, hero-KPI, color cleanup, popover, a11y, css-vars, page-header
- **Неделя 3 (P3):** command-palette, chart-theme, micro-animations, density

**Не «редизайн» — финиш-инжиниринг существующего видения.**

---

## Отметка автора

> «Уже сейчас в коде есть базовая палитра, базовый компонент-лэйер (`.card`, `.btn`, `.btn-primary`, `.nav-link`) — нужно его расширить, починить (`.input`, `bg-card`) и применить дисциплину типографики.»

Полный отчёт: запущенный agent run 2026-05-15.
