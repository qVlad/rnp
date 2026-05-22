# Калькулятор рентабельности WB-акций — методика и спецификация

**Статус:** v0.1 (2026-05-22) · **TASK-LEAD-050** (реализация) + **TASK-LEAD-067** (UX-polish) · **Маршрут:** [`/promo-calculator`](https://rnp.sellerfriends.ru/promo-calculator)

Документ описывает, что считает страница «Калькулятор акций» и как
интерпретировать результат. Эталон формул — `backend/app/services/promo_calculator.py`,
эталон источников baseline — `wb_report_detail` через canonical predicate'ы
из `services/period_aggregates.py`.

См. также: [`FEATURES.md`](FEATURES.md) (список фич), [`CLAUDE.md`](CLAUDE.md)
(стек, RBAC), [`WB_API_REFERENCE.md`](WB_API_REFERENCE.md) §11.5 (Promo
Calendar API).

---

## 1. Когда использовать

WB регулярно предлагает селлеру акции вида «−25% на 7 дней, прогноз +80% к
выкупам». Решение «вступать / отказаться» — это сравнение:

| Без акции | С акцией |
|---|---|
| Цена `P`, скорость продаж `V` ед/день | Цена `P × (1 − discount)`, скорость `V × (1 + boost)` |
| Маржа `M_unit = P − cogs − комиссия − логистика` | Маржа `M'_unit = P × (1 − discount) − cogs − комиссия' − логистика` |
| Итог за N дней = `M_unit × V × N` | Итог за N дней = `M'_unit × V' × N` |

Калькулятор считает обе стороны для **выбранных SKU** и подсвечивает «лучше /
хуже / убыток per unit» + breakeven-boost (минимальный прирост продаж, при
котором акция выходит хотя бы в ноль).

## 2. Что калькулятор НЕ делает (важно)

- **Не предсказывает реальный velocity boost** — пользователь сам ставит
  ожидаемый. Калькулятор только симулирует «что будет если». В среднем
  WB-акции дают +50…150% к скорости, но это сильно зависит от категории,
  сезона, цены конкурентов.
- **Не учитывает каннибализацию по схожим SKU** — если у вас 5 размеров
  одной модели, акция на один может перетянуть продажи с других. Считайте
  всю группу разом (multi-select поддерживает до 200 SKU).
- **Не считает влияние на ранжирование после акции.** Часть селлеров видит
  «провал» продаж после окончания акции (алгоритм WB временно понижает
  карточку). Этот эффект здесь не моделируется.
- **Не учитывает «активные» промо WB-акции на момент расчёта.** Baseline
  считается «как есть» — если SKU уже в акции, цена в baseline уже
  пониженная, и расчёт «with promo» применит ещё одну скидку поверх. Для
  чистого расчёта берите baseline-период, когда акции не было.
- **Не делает рассылок / не вступает в акцию автоматически.** Это только
  калькулятор — финальное решение и техническая подача в WB ЛК — на
  пользователе.

## 3. Входные параметры

| Параметр | Диапазон | Default | Описание |
|---|---|---|---|
| SKU (`nm_ids`) | 1..200 | — | Multi-select через `SkuMultiPicker`. Manager видит только свои бренды (RBAC). |
| Скидка акции (%) | 0..99 | 25 | Скидка от текущей цены продажи (как ЛК WB её фиксирует). |
| Длительность (дней) | 1..60 | 7 | Сколько дней действует акция. WB-акции редко длиннее месяца. |
| Прогноз boost'а продаж (%) | 0..500 | 80 | На сколько вырастет скорость выкупов. «Средняя WB-акция» = +50…150%. |
| Baseline-окно (дней) | 1..90 | 14 | Откуда брать «как было». 7д = свежо, но шумно; 30д = устойчиво, но устарело. |

## 4. Формулы (pure-function `simulate_promo`)

Исходник: [`backend/app/services/promo_calculator.py:simulate_promo`](backend/app/services/promo_calculator.py).
Функция намеренно pure — не ходит в БД, всё baseline-данные передаются
аргументом `SkuBaseline`. Это даёт юнит-тесты без БД и возможность пересчёта
на фронте без round-trip (если когда-нибудь захотим ползунки live-update).

### 4.1. Baseline (расчёт «как сейчас»)

За окно `baseline_period_days` агрегируем из `wb_report_detail`:

```
revenue_sale   = SUM(retail_price_withdisc_rub  WHERE supplier_oper_name = 'Продажа')
revenue_return = SUM(retail_price_withdisc_rub  WHERE supplier_oper_name = 'Возврат')
ppvz_sale      = SUM(ppvz_for_pay              WHERE supplier_oper_name = 'Продажа')
units_sale     = COUNT(*)                       WHERE supplier_oper_name = 'Продажа'
units_return   = COUNT(*)                       WHERE supplier_oper_name = 'Возврат'
delivery       = SUM(delivery_rub)
storage        = SUM(storage_fee)
penalty        = SUM(penalty)
```

Дальше:

```
units_net          = max(0, units_sale − units_return)
avg_price          = revenue_sale / units_sale          # цена факта (с текущими скидками)
velocity_per_day   = units_net / baseline_period_days   # net-выкупы в день
commission_rate    = (revenue_sale − ppvz_sale) / revenue_sale   # доля WB + эквайринг
                   = max(0, min(0.95, commission_rate))          # sanity cap
logistics_per_unit = (delivery + storage + penalty) / units_net  # 0 если нет продаж
cogs_per_unit      = last Cogs (cost_rub + packaging_rub + fulfillment_rub)
margin_per_unit    = avg_price − cogs_per_unit − commission_rate × avg_price − logistics_per_unit
```

Все поля canonical (filter `OP_SALE` / `OP_RETURN` + `REVENUE_FIELD` из
[`period_aggregates.py`](backend/app/services/period_aggregates.py)) — те же
предикаты, что использует `/pnl`, `/dashboard`, `/units`.

### 4.2. With-promo (расчёт «что будет, если вступим»)

```
new_price        = avg_price × (1 − discount_pct / 100)
new_velocity     = velocity_per_day × (1 + boost_pct / 100)
new_commission_per_unit = commission_rate × new_price   # WB-комиссия — % от выручки, остаётся той же долей
new_margin_per_unit = new_price − cogs_per_unit − new_commission_per_unit − logistics_per_unit
new_margin_per_day  = new_margin_per_unit × new_velocity
new_margin_total    = new_margin_per_day × duration_days
new_revenue_per_day = new_price × new_velocity
new_revenue_total   = new_revenue_per_day × duration_days
```

### 4.3. Решающие метрики

| Поле | Что означает | Когда «зелёный» |
|---|---|---|
| `is_profitable` | `new_margin_per_unit > 0` | Хотя бы не торгуем в минус на каждой единице |
| `is_better_than_baseline` | `new_margin_total > baseline_margin_total` | Вступать выгоднее, чем сидеть на baseline |
| `breakeven_velocity_boost_pct` | Минимальный boost (%), при котором `new_margin_total ≥ baseline_margin_total` | Сравните с вашим прогнозом — если ваш «честный» прогноз ≥ breakeven, вступайте |

**Формула breakeven** (аналитическая, без поиска):

```
(1 + boost/100) ≥ baseline_margin_per_unit / new_margin_per_unit
⇒ boost_pct ≥ 100 × (baseline_margin_per_unit / new_margin_per_unit − 1)
```

Требование: `new_margin_per_unit > 0` (иначе никакой boost не вытащит — выручка
просто масштабирует убыток). В этом случае `breakeven_velocity_boost_pct = None`
→ UI показывает «недостижим» и подсвечивает строку красным.

Если `baseline_margin_per_unit ≤ 0`, то «любой boost > 0 уже лучше чем
ничего» (раз `new_margin_per_unit > 0`) → `breakeven = 0`.

Cap: `_BREAKEVEN_MAX_BOOST_PCT = 500%` — если выше, считаем недостижимым.

### 4.4. Ограничения и санитарные значения

| Параметр | Cap (внутри функции) |
|---|---|
| `discount_pct` | clip(0, 99) |
| `boost_pct` | clip(0, 1000) (UI cap 500%) |
| `commission_rate` | clip(0, 0.95) |
| `buyout_rate` | clip(0.01, 1.0) |
| `duration_days` | ≥ 1 |

## 5. API

```
POST /api/promo-calculator/simulate
Content-Type: application/json
```

**Request:**

```json
{
  "nm_ids": [12345, 67890],
  "discount_pct": 25,
  "duration_days": 7,
  "expected_velocity_boost_pct": 80,
  "baseline_period_days": 14
}
```

**Response (по schema'е `api/promo_calculator.py`):**

```json
{
  "params": { ... echo + canonical ... },
  "items": [
    {
      "nm_id": 12345,
      "vendor_code": "ABC-001",
      "brand": "ONYX",
      "photo_url": "...",
      "baseline":   { "avg_price": 1200, "velocity_per_day": 3.5, "margin_per_unit": 280, "margin_total": 6860, ... },
      "with_promo": { "avg_price": 900,  "velocity_per_day": 6.3, "margin_per_unit": 110, "margin_total": 4851, ... },
      "delta_pct":  { "revenue_per_day": +35.0, "margin_per_unit": -60.7, ... },
      "delta_abs":  { ... },
      "is_profitable": true,
      "is_better_than_baseline": false,
      "breakeven_velocity_boost_pct": 156.4
    }
  ],
  "totals": {
    "skipped_nm_ids": [...],      // SKU вне brand-scope или без данных
    "items_count": 1,
    "profitable_count": 1,
    "better_than_baseline_count": 0,
    "sum_baseline_revenue_total": ...,
    "sum_with_promo_revenue_total": ...,
    "sum_baseline_margin_total": ...,
    "sum_with_promo_margin_total": ...,
    "sum_delta_revenue_total": ...,
    "sum_delta_margin_total": ...
  }
}
```

### 5.1. RBAC

| Роль | Доступ |
|---|---|
| `director` | все SKU |
| `head_of_sales` | все SKU |
| `manager` | только nm_id из `brand_assignments` (через `current_brands_filter`). SKU вне whitelist'а тихо отфильтровываются (попадают в `skipped_nm_ids` ответа, не 403). |
| `bookkeeper` | **403** (узкий scope — налоги/выкупы/audit, без управленческой аналитики) |

## 6. WB Promo Calendar API (опционально)

`backend/app/integrations/wb/promotions.py:list_active_promotions(token)` —
обёртка для `GET https://dp-calendar-api.wildberries.ru/api/v1/calendar/promotions`.

**Назначение:** preload активных WB-акций, чтобы пользователь не вбивал
discount/duration руками — выбрал акцию из списка → форма заполнилась.

**Graceful fallback** (важно): любая ошибка от WB (404 / 401 / 403 / 5xx /
network / cooldown) → пустой список + warning в лог. UI всё равно работает
в manual-input режиме. Это намеренно: WB Promo API нестабильный и без
гарантированного rate-limit'а, мы не делаем фичу его заложником.

Rate-limit (наблюдаемый): осторожный 6/мин с min_interval=10s (как для
tariffs/documents — точного публичного лимита от WB нет, см. `WB_API_REFERENCE.md` §3).

## 7. UI (`frontend/src/pages/PromoCalculator.tsx`)

- **PageHeader** с inline-ссылкой на эту методику («📘 Методика»)
- **SKU multi-picker** (max 200, поиск по vendor_code/brand)
- **Параметры** — скидка %, длительность, boost %, baseline-окно
- **Result table per-SKU** с цветовой индикацией:
  - **зелёный фон** строки — `is_better_than_baseline = true`
  - **красный фон** — `is_profitable = false` (margin/unit < 0)
  - **жёлтый бейдж** — `breakeven_velocity_boost_pct > expected_boost` (есть прибыль на unit, но не дотянет до baseline)
- **Totals row** — сумма по выбранным SKU
- **Сортировка** — по умолчанию `delta_margin desc` (что выгоднее всего)
- **Skipped list** — SKU без данных в `wb_report_detail` или вне brand-scope

## 8. Тесты

`backend/tests/test_promo_calculator.py` покрывает:
- baseline-нерентабельный + new-нерентабельный → `breakeven = None`
- baseline-нерентабельный + new-рентабельный → `breakeven = 0`
- baseline-рентабельный, требует boost X% → формула `(ratio − 1) × 100`
- discount cap (вход 150% → clip к 99%)
- boost cap (вход 5000% → clip к 1000%)

## 9. Edge cases / частые жалобы

| Симптом | Почему | Как обойти |
|---|---|---|
| Один SKU в `skipped_nm_ids` | За baseline-окно у него 0 строк в `wb_report_detail` (новый товар / не продавался) | Расширить baseline-окно до 30/60/90 дней. Если всё равно пусто — товар не подходит для симуляции (нет истории) |
| Все строки красные / убыток | Текущая цена близка к себестоимости + комиссии. Любая скидка → минус | Снизить discount_pct либо реалистичнее выставить boost. Если breakeven > 200% — акция нерентабельна, не вступать |
| `delta_pct = null` | Baseline 0 (например, `revenue_per_day = 0` если за окно были только возвраты) | Расширить окно или исключить SKU |
| Avg_price отличается от ЛК WB | Берём `revenue_sale / units_sale` за окно — это **факт** (с учётом всех применённых скидок WB, СПП, акций). Не путать с «ценой продавца» в ЛК | Это правильное поведение для симуляции — мы планируем от того, что покупатели реально платят |
| Manager не видит SKU других брендов | RBAC. Тихо отфильтровываются в `skipped_nm_ids` | Свяжись с директором — попросить `brand_assignment` |

## 10. Roadmap

См. [`agents/tasks-lead.md`](agents/tasks-lead.md):
- **TASK-LEAD-067** — PromoCalculator UX-polish (2-col layout + plain naming), P3
- Идеи (не оформлены задачами): preload активных акций из WB-календаря с
  one-click selection, истории симуляций (тег «вступил/нет → факт vs прогноз»
  через 30 дней), сравнение нескольких сценариев в одном view.
