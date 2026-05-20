# UNIT-план — методика и спецификация

**Статус:** черновик S1 · **Версия:** v0.1 (2026-05-19) · **Эталон:** `LeymanKids UNIT_план WB Обновление.xlsx` (2026-05-13, 1506×59)

Документ описывает плановую (forward-looking) юнит-экономику для каждого SKU.
Это **не** замена `services/unit_economics.py` (факт-аналитика из `wb_report_detail`)
и не замена `/unit-calculator` (single-SKU ad-hoc). UNIT-план отвечает на вопрос
«сколько мы заработаем на этом SKU при текущих ценах, тарифах и настройках».

См. также: `CLAUDE.md` (стек, RBAC, конвенции), `agents/tasks-lead.md`
(backlog UNIT-PLAN-001…023), `WB_API_REFERENCE.md` (Tariffs API).

---

## 1. Семантика: план vs факт

| Раздел | Семантика | Источник | Когда смотреть |
|---|---|---|---|
| `/units` | **Факт.** Что произошло за период (выручка, прибыль, маржа) | `wb_report_detail` | Постфактум, сверка |
| `/unit-calculator` | **Калькулятор.** «Что если» для одной карточки | inline-ввод | Ad-hoc проверка идеи |
| `/unit-plan` ⭐ | **План.** Что должно случиться при текущих ценах/тарифах | `products` + `wb_tariff_*` + overrides | Перед изменением цен, ассортимента |

Ключевое различие: в `/unit-plan` **нет конкретного периода** — это снимок
«сейчас». Историчность достигается через snapshots (см. §10).

---

## 2. Глобальные константы

Хранятся в `unit_plan_global_config` (tenant-scoped, версионирование по
`effective_date`, директор/head). Соответствие Excel R1:

| Excel cell | Поле БД | Default | Назначение |
|---|---|---|---|
| J1 = 30 | `velocity_days` | 30 | Окно «закончится через дн» |
| P1 = 0% | `wb_club_pct` | 0 | Скидка WB Клуб |
| R1 = 20% | `spp_default_pct` | 20 | СПП default (override per-subject ниже) |
| T1 = 2% | `wb_wallet_pct` | 2 | WB Кошелёк |
| V1 = 2% | `acquiring_pct` | 2 | Эквайринг |
| AA1 = 1.16 | `il_coef` | 1.16 | ИЛ-коэф (локальный, не WB) |
| AC1 = 0.017 | `irp_coef` | 0.017 | ИРП-коэф (локальный, % от цены) |
| AN1 = 3% | `marketing_pct` | 3 | Реклама |
| AP1 = 8% | `tax_pct` | 8 | Налог |
| AQ1 = "не включаем" | `vat_mode` | `'exclude'` | НДС режим: `'include' \| 'exclude' \| 'none'` |
| AR1 = 10% | `vat_pct` | 10 | НДС ставка |
| AS1 = 1.7 | `acceptance_rub_per_liter` | 1.7 | Платная приёмка ₽/л |
| — | `acceptance_multiplier` | 1.0 | Множитель приёмки |
| — | `buyout_fallback_pct` | 50 | Fallback % выкупа если в Воронке = 0 |

**СПП per-категория** — добавочное поле `spp_by_subject JSONB` в `unit_plan_global_config`,
формат `{"Пижамы": 28, "Платья": 22}`. Приоритет: per-row override → per-subject → global default.

---

## 3. Domain model (миграции 0040-0042)

### 0040 — Reference (без `tenant_id`, синхронизируется с WB Tariffs API)

```sql
CREATE TABLE wb_tariff_box (
    id              BIGSERIAL PRIMARY KEY,
    effective_from  DATE NOT NULL,
    warehouse_name  VARCHAR(255) NOT NULL,
    delivery_base   NUMERIC(10,4),   -- ₽ за 1 л
    delivery_liter  NUMERIC(10,4),   -- ₽ за каждый доп. л
    delivery_expr   NUMERIC(8,4),    -- % коэф
    storage_base    NUMERIC(10,6),   -- ₽/день за 1 л
    storage_liter   NUMERIC(10,6),
    dt_next         DATE,            -- WB-hint когда изменится
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (warehouse_name, effective_from)
);

CREATE TABLE wb_tariff_pallet (
    id              BIGSERIAL PRIMARY KEY,
    effective_from  DATE NOT NULL,
    warehouse_name  VARCHAR(255) NOT NULL,
    delivery_base   NUMERIC(10,4),
    delivery_liter  NUMERIC(10,4),
    delivery_expr   NUMERIC(8,4),
    storage_base    NUMERIC(10,6),
    storage_liter   NUMERIC(10,6),
    storage_expr    NUMERIC(8,4),
    dt_next         DATE,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (warehouse_name, effective_from)
);

CREATE TABLE wb_tariff_commission (
    id                 BIGSERIAL PRIMARY KEY,
    effective_from     DATE NOT NULL,
    subject_name       VARCHAR(255) NOT NULL,
    subject_id         INTEGER,
    commission_fbo     NUMERIC(6,2),   -- kgvpMarketplace
    commission_fbs     NUMERIC(6,2),   -- kgvpSupplier
    commission_express NUMERIC(6,2),
    paid_storage_kgvp  NUMERIC(6,2),   -- % платной приёмки (если в этом ответе)
    return_cost        NUMERIC(10,2),
    fetched_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (subject_name, effective_from)
);
```

**Почему без `tenant_id`:** тарифы WB одинаковы для всех селлеров. Тенант-специфика
выносится в `unit_plan_override`. Это экономит место (тарифы для 200 складов ×
лет истории = десятки тысяч строк × N тенантов было бы бессмысленным
дублированием).

**SCD Type 2:** при ежедневном sync — если данные изменились, закрываем
старую запись (`effective_to = today`) и вставляем новую (`effective_from = today`).
Если не изменились — обновляем только `fetched_at`. Расчёт на дату D берёт
`SELECT … WHERE effective_from <= D ORDER BY effective_from DESC LIMIT 1`.

### 0041 — Расширение `products`

```sql
ALTER TABLE products
  ADD COLUMN volume_l NUMERIC(8,3),
  ADD COLUMN warehouse_default VARCHAR(255),
  ADD COLUMN is_monopallet BOOLEAN NOT NULL DEFAULT false,
  ADD COLUMN items_per_monopallet INTEGER;
```

### 0042 — Tenant-scoped план-таблицы

```sql
CREATE TABLE unit_plan_global_config (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    effective_date DATE NOT NULL,
    -- Pricing ladder
    wb_club_pct NUMERIC(5,2) DEFAULT 0,
    spp_default_pct NUMERIC(5,2) DEFAULT 20,
    spp_by_subject JSONB DEFAULT '{}'::jsonb,
    wb_wallet_pct NUMERIC(5,2) DEFAULT 2,
    acquiring_pct NUMERIC(5,2) DEFAULT 2,
    -- Coefs
    il_coef NUMERIC(6,4) DEFAULT 1.16,
    irp_coef NUMERIC(6,4) DEFAULT 0.017,
    -- Cost percentages
    marketing_pct NUMERIC(5,2) DEFAULT 3,
    tax_pct NUMERIC(5,2) DEFAULT 8,
    vat_mode VARCHAR(16) DEFAULT 'exclude',  -- 'include' | 'exclude' | 'none'
    vat_pct NUMERIC(5,2) DEFAULT 10,
    -- Acceptance
    acceptance_rub_per_liter NUMERIC(6,2) DEFAULT 1.7,
    acceptance_multiplier NUMERIC(6,2) DEFAULT 1.0,
    -- Velocity / fallback
    velocity_days INTEGER DEFAULT 30,
    buyout_fallback_pct NUMERIC(5,2) DEFAULT 50,
    storage_days INTEGER DEFAULT 60,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by INTEGER REFERENCES users(id),
    UNIQUE (tenant_id, effective_date)
);

CREATE TABLE unit_plan_override (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL,
    nm_id BIGINT NOT NULL,
    -- Per-row overrides поверх products / global_config
    warehouse_name VARCHAR(255),
    is_fbs BOOLEAN,
    is_monopallet BOOLEAN,
    items_per_monopallet INTEGER,
    spp_pct NUMERIC(5,2),
    -- Labels
    abc_label CHAR(1),
    season_label VARCHAR(32),
    gender_label VARCHAR(8),
    comment TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, nm_id)
);

CREATE TABLE unit_plan_snapshot (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL,
    snapshot_date DATE NOT NULL,
    label VARCHAR(64),
    period_from DATE,
    period_to DATE,
    nm_id BIGINT NOT NULL,
    -- Denormalized: ровно то что считалось в день снапшота
    orders_qty INTEGER,
    sold_qty INTEGER,
    revenue NUMERIC(14,2),
    profit_rub NUMERIC(14,2),
    margin_pct NUMERIC(6,2),
    buyout_pct NUMERIC(5,2),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_unit_plan_snapshot ON unit_plan_snapshot (tenant_id, snapshot_date, nm_id);
```

---

## 4. 60 колонок Excel → поля DTO

Mapping `Excel column letter` → `Excel header` → `UnitPlanRowDTO` field.

### Identification (A-F, 6 frozen)

| Excel | Header | DTO field | Источник |
|---|---|---|---|
| A | Склад | `warehouse` | `override.warehouse_name` ?? `products.warehouse_default` |
| B | Литры | `volume_l` | `products.volume_l` |
| C | Бренд | `brand` | `products.brand` |
| D | Предмет | `subject` | `products.subject` |
| E | Артикул продавца | `vendor_code` | `products.vendor_code` |
| F | Артикул WB | `nm_id` | `products.nm_id` |

### Stocks (G-J, 4)

| Excel | Header | DTO field | Формула |
|---|---|---|---|
| G | Остаток WB | `stock_wb` | `wb_stock_snapshot.quantity` (latest) |
| H | Остаток FBS | `stock_fbs` | (если есть FBS-feed) |
| I | Остаток с учётом % выкупа | `stock_effective` | `G + G × (1 − buyout_pct)` |
| J | Закончится через дн | `days_to_stockout` | `I / (orders_30d / velocity_days)`, если `orders_30d=0` → `null` |

### Price ladder (K-T, 10)

| Excel | Header | DTO | Формула |
|---|---|---|---|
| K | Базовая цена | `base_price` | `wb_prices.price` |
| L | Скидка | `discount_pct` | `wb_prices.discount / 100` |
| M | Скидка с сайта ВБ | `discount_wb_pct` | same (sanity-check N) |
| N | Проверка | `discount_match` | `L == M` |
| O | **Цена продажи (без СПП)** | `price_after_discount` | `K × (1 − L)` |
| P | ВБ Клуб % | `wb_club_pct` | глобал |
| Q | **Цена с ВБ клуб** | `price_after_wb_club` | `O × (1 − P)` |
| R | Размер СПП | `spp_pct` | override.spp_pct ?? `spp_by_subject[subject]` ?? `spp_default_pct` |
| S | **Цена с СПП** | `price_after_spp` | `Q × (1 − R)` |
| T | **Цена с WB Wallet** | `price_final` | `S × (1 − wb_wallet_pct)` |

`O`, `Q`, `S`, `T` — четыре ключевые точки price ladder.

### Commission (U-Y, 5)

| Excel | Header | DTO | Формула |
|---|---|---|---|
| U | Комиссия % | `commission_pct` | `wb_tariff_commission.commission_fbo` или `commission_fbs` если `Y='Да'` |
| V | Эквайринг | `acquiring_pct` | глобал |
| W | Общая комиссия | `commission_total_pct` | `U + V` |
| X | **Комиссия ₽** | `commission_rub` | `O × W` |
| Y | FBS Да/Нет | `is_fbs` | `override.is_fbs ?? false` |

### Logistics (Z-AH, 9)

| Excel | Header | DTO | Формула |
|---|---|---|---|
| Z | Логистика тариф (короб) | `logistics_box_rub` | См. формулу A ниже |
| AA | Монопаллет Да/Нет | `is_monopallet` | `override ?? products.is_monopallet` |
| AB | Items per pallet | `items_per_monopallet` | `override ?? products.items_per_monopallet` |
| AC | Логистика тариф (монопаллет) | `logistics_pallet_rub` | См. формулу B ниже |
| AD | % выкупа | `buyout_pct` | `wb_funnel.buyout_pct / 100` ?? `buyout_fallback_pct / 100` |
| AE | Коэф склада % | `warehouse_coef_pct` | `wb_tariff_box.delivery_expr` (для отображения) |
| AF | **Логистика ₽** | `logistics_rub` | `IF(is_monopallet, (AD×AC + (1−AD)×AC×2)/AD, (AD×Z + (1−AD)×(Z+AG))/AD)` |
| AG | Обратная логистика ₽ | `reverse_logistics_rub` | Ступени: `23/26/29/32/35/38/41/44/47/50` ₽ по литрам |
| AH | Логистика % от продажи | `logistics_share` | `AF / O` |

**Формула A — короб (Z):**
```
IF(литры ∈ [0.001, 0.2]:
    23 × warehouse_coef_pct × il_coef + O × irp_coef
ELSE:
    (delivery_base + (литры − 1) × delivery_liter) × warehouse_coef_pct × il_coef + O × irp_coef
```

**Формула B — монопаллет (AC):**
```
IF(is_monopallet AND items_per_monopallet > 0:
    pallet_delivery_base + IF(литры > 1, (литры − 1) × pallet_delivery_liter, 0)
ELSE: 0
```

### Storage (AI-AJ, 2)

| Excel | Header | DTO | Формула |
|---|---|---|---|
| AI | **Хранение ₽** | `storage_rub` | `IF(is_fbs, 0, IF(is_monopallet, pallet_storage × storage_days / items_per_pallet, box_storage × литры × storage_days))` |
| AJ | Хранение % | `storage_share` | `AI / O` |

### COGS (AK-AL, 2)

| Excel | Header | DTO | Формула |
|---|---|---|---|
| AK | **Себестоимость ₽** | `cogs_rub` | `cogs.cost_rub` (latest valid_from ≤ today) |
| AL | Себест % | `cogs_share` | `AK / O` |

### Marketing (AM-AN, 2)

| Excel | Header | DTO | Формула |
|---|---|---|---|
| AM | **Реклама ₽** | `marketing_rub` | `AN × O` |
| AN | Реклама % | `marketing_pct` | глобал |

### Taxes + VAT (AO-AR, 4)

| Excel | Header | DTO | Формула |
|---|---|---|---|
| AO | **Налог ₽** | `tax_rub` | `T / (1 + vat_pct) × tax_pct` |
| AP | Налог % | `tax_pct` | глобал |
| AQ | **НДС ₽** | `vat_rub` | См. ниже (3 режима) |
| AR | НДС % | `vat_pct` | глобал |

**НДС режимы:**
```
'include' (включаем):       vat_rub = T / (1 + vat_pct) × vat_pct
'exclude' (не включаем):    vat_rub = T × vat_pct
'none' (не платим):         vat_rub = 0
```

### Acceptance (AS-AT, 2)

| Excel | Header | DTO | Формула |
|---|---|---|---|
| AS | **Платная приёмка ₽** | `acceptance_rub` | `IF(литры < 1, ceil(литры), литры) × acceptance_rub_per_liter × acceptance_multiplier` |
| AT | Приёмка % | `acceptance_share` | `AS / O` |

### Result (AU-AW, 3)

| Excel | Header | DTO | Формула |
|---|---|---|---|
| AU | **Прибыль ₽** | `profit_rub` | `O − X − AF − AI − AK − AM − AO − AS − AQ` |
| AV | Маржинальность % | `margin_pct` | `AU / O` |
| AW | Рентабельность % | `roi_pct` | `AU / AK` |

### Labels (AX-AZ, 3)

| Excel | Header | DTO | Источник |
|---|---|---|---|
| AX | Сезон | `season_label` | `override.season_label` |
| AY | Пол | `gender_label` | `override.gender_label` |
| AZ | ABC | `abc_label` | `override.abc_label` (или auto-compute из факт-revenue если override не задан) |

### Historical snapshots (BA-BF, 6)

| Excel | Header | DTO | Источник |
|---|---|---|---|
| BA | Чистая прибыль 1-я нед. мая | `profit_week_1` | snapshot |
| BB | Заказано 12.04-13.05 | `orders_period_1` | `wb_orders` агрегат |
| BC | Выкуплено 12.04-13.05 | `sold_period_1` | `wb_sales` |
| BD | Заказано 11-12.2025 | `orders_period_2` | snapshot 2025-11 |
| BE | Заказано 06-07.2025 | `orders_period_3` | snapshot 2025-06 |
| BF | Прогноз остатка на 1.08.2026 | `stock_forecast` | `I − BE` |

Периоды снапшотов — настраиваемые через UI (см. UNIT-PLAN-017).

---

## 5. Pure-function `compute_row`

Сигнатура (вход — plain dataclasses, без `session`):

```python
def compute_row(
    product: ProductSnapshot,           # nm_id, vendor_code, brand, subject, volume_l, warehouse_default, base_price, discount_pct
    cogs: CogsSnapshot,                 # cost_rub
    funnel: FunnelSnapshot,             # orders_30d, buyout_pct
    stock: StockSnapshot,               # qty_wb, qty_fbs
    refs: ReferenceBundle,              # tariff_box[warehouse], tariff_pallet[warehouse], commission[subject]
    override: OverrideSnapshot,         # warehouse, is_fbs, is_monopallet, spp_pct, abc, season, gender
    config: GlobalConfig,               # все глобал-константы
) -> UnitPlanRowDTO: ...
```

Без I/O, без сессии — тестируется 1:1 против Excel (50+ строк golden-fixture
с `tolerance=0.01 ₽` на каждое поле).

---

## 6. RBAC

| Действие | director | head_of_sales | manager |
|---|:-:|:-:|:-:|
| `GET /api/unit-plan` | все | все | свои бренды |
| `PUT /api/unit-plan/overrides/{nm}` | ✅ | ✅ | свои бренды |
| `PUT /api/unit-plan/global-config` | ✅ | ❌ | ❌ |
| `POST /api/unit-plan/snapshots` | ✅ | ✅ | ❌ |
| `GET /api/unit-plan/export.xlsx` | full | full | brand-filtered |
| Sidebar visibility | ✅ | ✅ | ✅ |

Manager-фильтр: `services/auth.current_brands_filter()` → `WHERE products.brand IN (...)`.

---

## 7. WB Tariffs API integration

Подробности — `WB_API_REFERENCE.md`. Кратко:

- Host: `common-api.wildberries.ru`, scope bit 512 (есть в наших токенах)
- Endpoints: `GET /api/v1/tariffs/box?date=YYYY-MM-DD`, `/pallet?date=...`, `/commission`
- Rate limit: ~6/мин (категория `"tariffs"` в `WbApiClient`)
- Cron: ежедневно 08:00 MSK (после report_detail в 04:15)
- Fallback: silently keep last snapshot, баннер «Тарифы синхронизированы N дней назад» если age > 7 дней
- Upsert по `(warehouse_name, effective_from)` или `(subject_name, effective_from)` — SCD2

---

## 8. API endpoints

```
GET    /api/unit-plan/rows                # ?warehouse=&fbs=&abc=&brand=&search=
GET    /api/unit-plan/rows.xlsx           # 1:1 экспорт 60 колонок
GET    /api/unit-plan/global-config       # latest
PUT    /api/unit-plan/global-config       # upsert new effective_date version (director only)
GET    /api/unit-plan/overrides
PUT    /api/unit-plan/overrides/{nm_id}
DELETE /api/unit-plan/overrides/{nm_id}
POST   /api/unit-plan/snapshots           # body: {label, period_from, period_to}
GET    /api/unit-plan/snapshots
GET    /api/unit-plan/snapshots/{id}/diff
POST   /api/unit-plan/import-xlsx         # multipart, парсит литры/labels/overrides
GET    /api/unit-plan/reference/status    # last sync даты tariffs
```

Response shape:

```jsonc
{
  "meta": {
    "on_date": "2026-05-19",
    "reference_status": {"tariff_box_age_days": 0, "commission_age_days": 3, "stale": false},
    "config_version": "v3 @ 2026-05-19",
    "total_rows": 1502,
    "filtered_rows": 1247
  },
  "items": [ UnitPlanRowDTO, ... ],
  "labels_available": {"abc": ["A","B","C"], "season": [...], "gender": [...]}
}
```

---

## 9. Кэширование

- Redis-cache на `ReferenceBundle`: `unit_plan:refs:{date}` TTL 1h
- Row-level cache **не делаем** до профиля (1500 SKU × pure compute_row ≈ 100мс)
- Invalidation: при PUT `/global-config` → `DEL unit_plan:refs:*`; при изменении `unit_plan_override` для tenant — invalidate per-tenant rows-cache (если появится)

---

## 10. Snapshots

Snapshot = иммутабельная фотография расчёта на конкретную дату. Хранится как
денормализованные строки (`unit_plan_snapshot`), не JSON blob — для дешёвого diff.

Триггер: ручной `POST /api/unit-plan/snapshots` или авто (раз в месяц через
Celery beat — настраиваемо). Глобальные константы при создании snapshot
freeze-копируются в `unit_plan_snapshot_config` (TODO).

Diff: `GET /api/unit-plan/snapshots/{id}/diff` сравнивает snapshot с current —
показывает дельты по `revenue`, `profit_rub`, `margin_pct`, `buyout_pct`.

---

## 11. Контракт-тест с Excel-эталоном

`tests/unit_plan/test_compute_row_excel_contract.py`:

1. Загружаем 50 случайных строк из `LeymanKids UNIT_план WB Обновление.xlsx`
2. Для каждой — конструируем `ProductSnapshot/CogsSnapshot/FunnelSnapshot/...` из её значений
3. Запускаем `compute_row` → получаем `UnitPlanRowDTO`
4. Сверяем каждое поле с Excel-значением, tolerance `0.01 ₽` (или `0.0001` для долей)
5. Provider Excel-эталон как fixture в `tests/fixtures/unit_plan_excel/`

Это P0-задача (UNIT-PLAN-019), без неё деплой запрещён.

---

## 12. Frontend `/unit-plan`

Полная UX-спека в выходе агента `visual-design-lead` (см. `agents/tasks-lead.md`
UNIT-PLAN-011). Кратко:

- 3-уровневая sticky-зона (top-panel → toolbar → grouped header)
- Frozen-left 6 колонок (Identification)
- 6 collapsible groups (Identification / Stocks / Price ladder / Costs / Result / Labels / Snapshots)
- Inline edit на 8 ячейках с autosave debounce 500ms
- Paste-from-Excel в литры/СПП (bulk-import)
- Drill-down side-drawer 480px (история цен 90 дн, разбивка COGS, план vs факт)
- Color coding по 4 порогам маржи + 3 порога buyout%
- Mobile — read-only карточки (60 колонок на 375px невозможны)

---

## 13. Документация — куда что обновляется при изменениях

- **Этот документ** (`UNIT_PLAN.md`) — single source of truth по методике
- `CLAUDE.md` — добавить раздел «UNIT-план», обновить таблицу миграций (+0040/0041/0042), API endpoints
- `FEATURES.md` — раздел «UI» добавить страницу `/unit-plan`, раздел «API» добавить 12 endpoints
- `ROADMAP.md` — пометить UNIT-план как in-progress / done
- `MANAGER_GUIDE.md` — UX-нюансы менеджера на `/unit-plan` (brand-фильтр locked)
- `ADMIN_GUIDE.md` — управление global-config timeline
- `WB_API_REFERENCE.md` — Tariffs API endpoints (host, scope, rate limits)
- `OPERATIONS.md` — backup перед миграциями 0040-0042

---

## 14. Открытые вопросы (на разрешение в ходе спринтов)

1. ABC автоматический расчёт — на каких показателях (revenue / profit / units)? По умолчанию факт-revenue 30 дн (как в `unit_economics.py`).
2. Storage formula edge case: при `items_per_monopallet = 0 OR NULL` — fallback на box-формулу или показать `null`?
3. История overrides — нужен ли audit log на каждое изменение `unit_plan_override`? Предлагаю да, через существующий `services/audit.audit_log()`.
4. Снапшот «период от-до» — для исторических периодов считать из `wb_orders` (Preliminary) или `wb_report_detail` (Final)? Предлагаю Final, чтобы совпадало с P&L.
5. **Excel-эталон содержит противоречие в формуле AF (логистика weighted-avg):** row 3 использует `(AD×Z + (1-AD)×(Z+AG))/AD` с volume-зависимым AG, rows 4+ используют фиксированное `(AD×Z + (1-AD)×(Z+50))/AD`. `compute_row` реализует **методически правильную** версию из row 3 (с AG). Это даёт расхождение ~5-10 ₽ на возврате для row 4+. Решение: использовать AG (правильно), документировать. Если бухгалтер настаивает на «+50» — добавить флаг `reverse_logistics_mode: 'tariff' | 'flat_50'` в global_config.
