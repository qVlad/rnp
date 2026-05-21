# TS-анализ + РОП-приоритеты — план (раунд 5)

**Автор:** Product Strategist (+ Explore-agent review `TRUESTATS_REFERENCE.md`)
**Дата:** 2026-05-21 (вечер, 4-й раунд параллельной разработки только что закрыт)
**Цель:** превратить новый детальный TS-анализ + 5 фич РОПа в приоритизированный backlog.

## Источники

- `TRUESTATS_REFERENCE.md` (1385 строк) — детальный UI-walkthrough пользователя по TS
- `ts_snap.txt` / `ts_snap2.txt` / `ts_snap3.txt` — accessibility-snapshots TS-интерфейса
- `COMPETITIVE_TRUESTATS.md` (437 строк) — предыдущий итеративный анализ
- РОП-list 5 фич (2026-05-21)
- `FEATURES.md` + `agents/tasks-lead.md` (текущее состояние РНП)

## TL;DR

3 из 5 фич РОПа у нас **уже полнее чем у TS**, но в **тяжёлой форме** (UnitPlan / NewProducts / ManagersKpi). РОПу нужны **lightweight варианты** для daily workflow.

2 фичи — **gap у обоих** (калькулятор акций WB + локализация заказов) → это **дифференциаторы** если сделаем.

Из обновлённого TS-анализа — 3 новых gap'а: **режимы отчётности** (Управленческая/Финансовая, архитектурно интересно), **breakdown-попапы на KPI** (UX quick-win), **per-store налоги** (полезно для multi-cabinet).

## 5 фич РОПа — статус

### 1. Unit-экономика с inline-редактором цены/скидки

- **У TS:** есть KPI юнит-экономики, но **без калькулятора новой цены**
- **У нас:** ✅ есть в UnitPlan (60 колонок Excel-методика), но **тяжёлый workflow** через override'ы
- **Что РОПу:** lightweight inline-input «Новая цена / Новая скидка» прямо в `/units` → видит новую маржу за секунду
- → **TASK-LEAD-049** P0, M эффорт. Quick win.

### 2. Калькулятор рентабельности WB-акций

- **У TS:** ❌ нет
- **У нас:** ❌ нет
- **Что РОПу:** «WB предложил акцию -20% на месяц — выгодно ли вступать?» Симулятор: baseline velocity × discount × velocity_boost → impact на маржу/выручку
- → **TASK-LEAD-050** P1, M. Дифференциатор vs TS (у них нет). Pre-flight: проверить WB Promo API.

### 3. Weekly digest менеджера

- **У TS:** есть Telegram-бот с custom-метриками + `/week` сводный отчёт
- **У нас:** ✅ есть `ManagersKpi.tsx` + `ManagerPlanProgressCard.tsx` + TG-бот, но **нет готовой страницы для weekly RO** (что-то для отправки/печати РОПу)
- **Что РОПу:** одна страница `/weekly-report` — KPI + top-5 SKU + алерты + комментарий, PDF-export
- → **TASK-LEAD-051** P1, M. Улучшение существующего workflow.

### 4. Отчёт по локализации заказов

- **У TS:** ❌ нет
- **У нас:** ❌ нет
- **Что РОПу:** % локализации = доля заказов которые отгружены **из ближайшего региону покупателя склада**. Низкая локализация → высокие logistics costs.
- → **TASK-LEAD-052** P1, L. Требует WB API research + миграция + sync. Дифференциатор.

### 5. Калькулятор стоимости транзитных поставок

- **У TS:** ❌ нет
- **У нас:** ✅ частично — `/new-products` CIF (Китай). РОП хочет ещё транзит между WB-складами по тарифам.
- → **TASK-LEAD-053** P2, S. Extension существующего CIF. Quick win.

## Новые gap из TS-анализа (помимо РОПа)

| # | Gap | Импакт | Сложность | Задача |
|---|---|:-:|:-:|---|
| 1 | Режимы отчётности «Управленческая / Финансовая» (дата=заказ vs дата=выплата) | high | M | TASK-LEAD-054 |
| 2 | Breakdown-попапы на KPI (click на «Логистика» → 5 строк разбивки) | med | S | TASK-LEAD-055 |
| 3 | Per-store налоговые ставки (разные режимы для разных юрлиц одной компании) | med | M | TASK-LEAD-056 (после реального multi-cabinet usage) |

## Что НЕ копируем из TS (явно)

- ❌ **ЭДО-интеграция (Контур.Diadoc)** — internal tool, не SaaS. На будущее.
- ❌ **Native mobile app** — PWA уже сделана.
- ❌ **«Мультивалютность» WB+Ozon+ЯМ** — Ozon отдельный roadmap, ЯМ нет.
- ❌ **Календарь операций в ДДС** (альтернативный view) — low impact, не приоритет.
- ❌ **Контрагенты как справочник** (отдельные юрлица с реквизитами) — internal tool, поле `contractor` в OPEX достаточно.

## Где мы выигрываем (для маркетинга / самосознания)

- **Налоги** = 100% методика Стаса, АУСН/УСН с НДС 5%/7%, КУДиР, per-regime exclusion. У TS «не бух-сервис».
- **4-way Reconciliation** = наш P&L vs ЛК WB vs raw vs bookkeeper XLSX. У TS только 1:1 с ЛК.
- **UNIT-план 60 колонок Excel-методика 1:1** — уникально для нашего ICP (Excel-driven маленькие селлеры).
- **CIF-калькулятор новинок** (Китай → 4 НДС-сценария) — у TS нет.
- **Multi-cabinet workspace end-to-end** — только что закрыли в v0.23.0. У TS «multimarket» (WB+Ozon+ЯМ), но не «multi-WB-cabinet».

## Рекомендуемый порядок выполнения

| # | TASK | Эффорт | Почему сейчас |
|---|---|:-:|---|
| 1 | **TASK-LEAD-049** Inline edit Units | M | P0 РОП-запрос, M эффорт = быстрая видимая выгода |
| 2 | **TASK-LEAD-051** Weekly digest | M | P1 РОП-запрос, переиспользует ManagersKpi + добавляет PDF |
| 3 | **TASK-LEAD-053** Транзит-калькулятор | **S** | Extension существующего CIF, quick win за 1-2 дня |
| 4 | **TASK-LEAD-050** Калькулятор акций | M | P1 + дифференциатор vs TS. Нужен WB API research для preload акций. |
| 5 | **TASK-LEAD-052** Локализация заказов | L | P1 + дифференциатор, но самая сложная — WB API + sync + UI |
| 6 | **TASK-LEAD-055** Breakdown-попапы | S | UX quick win после core фич РОПа |
| 7 | **TASK-LEAD-054** Режимы отчётности | M | Архитектурно важно, но не критично сейчас |
| 8 | **TASK-LEAD-056** Per-store налоги | M | После реального multi-cabinet usage |

## Параллелизация (для PM-планирования)

**Поток A — main session (sequential):**
- TASK-LEAD-049 (Units inline edit) → TASK-LEAD-051 (Weekly digest) → TASK-LEAD-053 (Транзит)

**Поток B — sub-agent (background, worktree):**
- TASK-LEAD-050 (Акции) — независимый, можно сразу
- TASK-LEAD-052 (Локализация) — изолированный backend + новые pages

**Поток C — sub-agent (background, worktree):**
- TASK-LEAD-055 (Breakdown-попапы) — изолированный, только Dashboard.tsx (но конфликт с потоком A через WeeklyReport — координация)
- TASK-LEAD-054 (Режимы отчётности) — после стабилизации

**Отложить:**
- TASK-LEAD-056 (Per-store налоги) — нужен реальный usage multi-cabinet (1-2 недели)

## Decision Log

- **2026-05-21**: Прочитан `TRUESTATS_REFERENCE.md` + сравнено с current state. 5 фич РОПа заведены как `TASK-LEAD-049..053` (P0/P1/P2). 3 новых gap из TS — `TASK-LEAD-054..056` (P2/P3). Старт рекомендую с 049 (P0 РОП) и 053 (быстрый quick win).
