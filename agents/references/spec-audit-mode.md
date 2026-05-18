# Spec: Аудит-режим v1 (XLSX-import) — LEAD-006

> Source: `agents/references/market/top-features-2026-05-17.md` Product #3.  
> Решение собственника от 2026-05-17: гибрид XLSX-import в v1 → API в v2.  
> Author: Lead Agent — 2026-05-18.

## TL;DR

Новая страница `/audit` с 3-column side-by-side сравнением финансовых данных:

| Колонка | Источник | Откуда берётся |
|---|---|---|
| **Левая** | Наш P&L (final-логика) | `services/pnl_builder.py` за период |
| **Средняя** | WB-кабинет (XLSX «Реализация») | Manual upload XLSX от пользователя |
| **Правая** | Бухгалтер (XLSX 1С / Контур / Моё дело) | Manual upload XLSX с настраиваемым mapping колонок |

Δ > 0.01₽ подсвечивается красным с возможностью «принять одну из 3 версий» (запись в `audit_log`). Это превращает наш существующий USP (Reconciliation Δ 0₽ с WB + Δ 0₽ с методикой Стаса) в **видимый экран**.

## Уникальность

- **TrueStats** честно говорит «не бух-сервис» — нет 3-source сравнения
- **Eggheads** — для маркетологов, не финдиректоров
- **MPStats** — про разведку ниш
- **МойСклад / 1С** — учётная система, не сверочная
- **Никто** не даёт связку «собственник + WB + бухгалтер сходятся копейка-в-копейку»

## Persona-validation

Из top-features-2026-05-17.md §A #3:
- **Accountant** ✅✅✅ MUST: главная ежемесячная задача — свести три источника
- **Selller** ✅✅: «спать спокойно перед налоговой»
- **ROP** ✅: показать собственнику чистоту цифр
- **Manager** ⚠️: не его зона

## Архитектура

### Модель данных

```sql
-- Миграция 0035_audit_imports.py
CREATE TABLE audit_imports (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT REFERENCES tenants(id) ON DELETE CASCADE,
    source VARCHAR(32) NOT NULL,          -- 'wb_cabinet' | 'bookkeeper'
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    file_name VARCHAR(255),                -- оригинальное имя загруженного файла
    rows_count INTEGER NOT NULL DEFAULT 0,
    data_json JSONB NOT NULL,              -- нормализованные строки (см. формат ниже)
    mapping_json JSONB,                    -- для bookkeeper: маппинг колонок (см. ниже)
    imported_by VARCHAR(64) NOT NULL,      -- username
    imported_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT uq_audit_import UNIQUE (tenant_id, source, period_start, period_end)
);
CREATE INDEX idx_audit_imports_period ON audit_imports(tenant_id, period_start, period_end);

-- Лог принятых решений по расхождениям (используется как самостоятельная
-- история; audit_log тоже пишется, но там общий лог по всем мутациям)
CREATE TABLE audit_decisions (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT REFERENCES tenants(id) ON DELETE CASCADE,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    line_code VARCHAR(64) NOT NULL,        -- 'revenue_gross', 'commission_wb', etc.
    chosen_source VARCHAR(32) NOT NULL,    -- 'ours' | 'wb_cabinet' | 'bookkeeper'
    delta_ours_wb NUMERIC(14,2),
    delta_ours_bk NUMERIC(14,2),
    comment TEXT,
    decided_by VARCHAR(64) NOT NULL,
    decided_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL
);
CREATE INDEX idx_audit_decisions_period ON audit_decisions(tenant_id, period_start, period_end);
```

### Нормализованный формат `data_json`

Чтобы compare-логика не зависела от формата конкретного XLSX, при импорте парсер укладывает строки в каноническую структуру:

```json
{
  "lines": [
    {"code": "revenue_gross", "label": "Выручка (до СПП)", "amount": 1234567.89},
    {"code": "revenue_returns", "label": "Возвраты", "amount": 89012.34},
    {"code": "commission_wb", "label": "Комиссия WB", "amount": 234567.12},
    {"code": "delivery_wb", "label": "Логистика WB", "amount": 45678.90},
    {"code": "storage_wb", "label": "Хранение WB", "amount": 12345.67},
    {"code": "acquiring", "label": "Эквайринг", "amount": 6789.01},
    {"code": "penalty", "label": "Штрафы", "amount": 1234.56},
    {"code": "deduction", "label": "Удержания", "amount": 567.89},
    {"code": "ppvz_for_pay", "label": "К перечислению", "amount": 901234.56},
    {"code": "vat_paid", "label": "НДС к уплате", "amount": 0},
    {"code": "tax_paid", "label": "Налог", "amount": 0}
  ],
  "raw_meta": {
    "file_name": "wb-realizacia-2026-04.xlsx",
    "sheet_name": "Реализация",
    "original_columns": ["Артикул", "Розничная цена", "..."]
  }
}
```

### Парсер WB-XLSX «Реализация»

WB-кабинет даёт стандартный формат для скачивания. Парсер:

1. Открывает sheet `Реализация` через `openpyxl`
2. Ищет header-row по наличию ключевых столбцов (`Артикул WB`, `Цена розничная`, `Тип документа`)
3. Группирует по `Тип документа` (`Продажа`/`Возврат`/`Корректировка`) и считает aggregates
4. Маппит на canonical `line_code` через `WB_XLSX_MAPPING` константу

⚠ Версия формата WB-XLSX меняется. Если парсер падает на «header not found» — fallback: показать сырые столбцы и просить юзера указать какие являются ключевыми (через UI mapping).

### Парсер бухгалтерского XLSX (настраиваемый mapping)

Бухгалтеры используют разные форматы (1С / Контур / Моё дело / custom Excel). Подход:

1. **При первой загрузке** для пары `(tenant, bookkeeper_template_name)` юзер настраивает маппинг колонок:
   - Открыть XLSX через `openpyxl`, прочитать header-row
   - Юзер выбирает: «Колонка `Доходы от реализации` → `revenue_gross`», «Колонка `Удержания WB` → `commission_wb`», …
   - Сохранить mapping в `audit_imports.mapping_json` + опционально в `bookkeeper_templates` таблицу (для повторного использования)
2. **При повторной загрузке** того же шаблона — маппинг применяется автоматически
3. Парсер использует mapping для извлечения agg-сумм per канонический `line_code`

### Сравнительный сервис

```python
# app/services/audit_compare.py

async def compare_three_sources(
    session: AsyncSession,
    *,
    tenant_id: int,
    period_start: date,
    period_end: date,
    epsilon: Decimal = Decimal("0.01"),
) -> list[ComparisonRow]:
    """Возвращает по строкам ОПиУ — наш P&L, WB-XLSX, bookkeeper-XLSX + дельты."""
    # 1. Берём наш P&L (final-логика, build_pnl с granularity=month)
    ours = await build_pnl(session, ..., granularity="month")

    # 2. Берём WB-import (если есть)
    wb_imp = await session.execute(
        select(AuditImport).where(...source='wb_cabinet'...)
    )

    # 3. Берём bookkeeper-import (если есть)
    bk_imp = ...

    # 4. Mergeя по line_code, считаем дельты
    rows: list[ComparisonRow] = []
    for code, label in CANONICAL_LINES:
        ours_amount = extract_from_pnl(ours, code)
        wb_amount = extract_from_import(wb_imp, code) if wb_imp else None
        bk_amount = extract_from_import(bk_imp, code) if bk_imp else None
        rows.append(ComparisonRow(
            code=code, label=label,
            ours=ours_amount, wb=wb_amount, bk=bk_amount,
            delta_ours_wb=(ours_amount - wb_amount) if wb_amount is not None else None,
            delta_ours_bk=(ours_amount - bk_amount) if bk_amount is not None else None,
            has_discrepancy=any_delta_above(epsilon, ...),
        ))
    return rows
```

### API endpoints

```
POST /api/audit/imports
  body: multipart/form-data with file + period_start + period_end + source
  guard: require_director_or_head
  возвращает: { import_id, rows_count, lines: [...] }

GET /api/audit/imports?period_start=...&period_end=...
  возвращает: { current_imports: { wb_cabinet: {...} | null, bookkeeper: {...} | null } }

POST /api/audit/imports/{id}/mapping (только для bookkeeper)
  body: { column_to_code: { "Колонка X": "revenue_gross", ... } }
  пересчитывает data_json по новому mapping

GET /api/audit/compare?period_start=...&period_end=...
  возвращает: { rows: [ComparisonRow], period: {...}, source_status: {...} }

POST /api/audit/decisions
  body: { period_start, period_end, line_code, chosen_source, comment }
  записывает решение в audit_decisions + audit_log

DELETE /api/audit/imports/{id}
  guard: require_director
```

Все ручки за `Depends(require_module("audit_mode"))` через `feature_flags.py`.

### Frontend

Страница `/audit`:

```
┌─────────────────────────────────────────────────────────────┐
│  Аудит-режим            Период: [Апрель 2026 ▾]            │
├─────────────────────────────────────────────────────────────┤
│  Источники:                                                 │
│    ✓ Наш P&L (расчёт)                                       │
│    ✓ WB-кабинет [Загружено wb-april.xlsx, 2026-05-18] [⟲]  │
│    ✓ Бухгалтер  [Загружено acc-april.xlsx, 2026-05-18] [⟲]  │
│                                                             │
│  [+ Загрузить WB XLSX]  [+ Загрузить бух. XLSX]            │
├─────────────────────────────────────────────────────────────┤
│  Строка             │ Наш       │ WB        │ Бух.       │ │
│─────────────────────┼───────────┼───────────┼────────────┼─│
│  Выручка (gross)    │ 1 234 567 │ 1 234 567 │ 1 234 567  │✓│
│  Возвраты           │   -89 012 │   -89 012 │   -89 012  │✓│
│  Комиссия WB        │  -234 567 │  -234 567 │  -234 510  │⚠│ [принять →]
│  Логистика WB       │   -45 678 │   -45 678 │   -45 678  │✓│
│  Хранение WB        │   -12 345 │   -12 345 │   -12 345  │✓│
│  ...                                                        │
│  Чистая прибыль     │    XXX    │    XXX    │    XXX     │ │
└─────────────────────────────────────────────────────────────┘
```

При клике на `⚠` — раскрывается inline-меню «принять наш / принять WB / принять бух. + комментарий» → запись в `audit_decisions`.

## Канонический список строк ОПиУ для compare

```python
# app/services/audit_compare.py
CANONICAL_LINES: list[tuple[str, str, str]] = [
    # (code, label, sign_class)
    ("revenue_gross",     "Выручка (gross)",                 "income"),
    ("revenue_returns",   "Возвраты",                        "expense"),
    ("revenue_net",       "Чистая выручка",                  "income"),
    ("commission_wb",     "Комиссия WB",                     "expense"),
    ("delivery_wb",       "Логистика WB",                    "expense"),
    ("storage_wb",        "Хранение WB",                     "expense"),
    ("acquiring",         "Эквайринг",                       "expense"),
    ("penalty",           "Штрафы",                          "expense"),
    ("deduction",         "Удержания",                       "expense"),
    ("ppvz_for_pay",      "К перечислению (ppvz_for_pay)",   "income"),
    ("ad_cost",           "Реклама",                         "expense"),
    ("cogs",              "Себестоимость",                   "expense"),
    ("vat_paid",          "НДС к уплате",                    "expense"),
    ("tax_paid",          "Налог (УСН/АУСН)",                "expense"),
    ("net_profit",        "Чистая прибыль",                  "income"),
]
```

## Что НЕ делаем в v1

- ❌ Auto-parse WB через API (отложено в v2 — решение собственника)
- ❌ Auto-parse бухгалтерского ПО через 1С/Контур API (отдельный roadmap-документ)
- ❌ Builder для произвольных custom-строк (только canonical lines)
- ❌ Multi-period bulk import (загрузка одного месяца за раз)
- ❌ PDF-экспорт сравнительного отчёта (опц. в v1.5)

## Реализация по этапам

### Этап 1 (S, ~2 дня) — Skeleton + WB-XLSX import

- [ ] Миграция `0035_audit_imports` + `audit_decisions`
- [ ] Модели `AuditImport`, `AuditDecision` в `db/models.py`
- [ ] `services/audit_compare.py` с canonical lines + `extract_from_pnl()` 
- [ ] WB-XLSX parser в `services/audit_parsers/wb_realizacia.py`
- [ ] API `POST /api/audit/imports` (только WB source в v1.0)
- [ ] API `GET /api/audit/compare` (показывает naш P&L vs WB)

### Этап 2 (M, ~3 дня) — Bookkeeper mapping

- [ ] Parser в `services/audit_parsers/bookkeeper.py` с user-configurable mapping
- [ ] API `POST /api/audit/imports/{id}/mapping`
- [ ] UI mapping-wizard при первой загрузке bookkeeper XLSX
- [ ] Опц. сохранение шаблона mapping per-tenant для повторного использования

### Этап 3 (S, ~2 дня) — Frontend

- [ ] Страница `/audit` с 3-column таблицей
- [ ] Upload-форма + period-picker (берёт месяц)
- [ ] Подсветка Δ > 0.01₽ + inline-меню «принять источник»
- [ ] Регистрация в `Layout.tsx` (только для director_or_head, require_module("audit_mode"))

### Этап 4 (S, ~1 день) — Persona-validation + tests

- [ ] TASK-PA-NNN: persona-accountant прогоняется по flow → отчёт
- [ ] Unit-test для WB-XLSX parser на эталонном файле
- [ ] Unit-test для compare-логики
- [ ] Smoke-тест end-to-end

## Зависимости

- LEAD-007 (feature_flags) ✅ — `require_module("audit_mode")` уже доступен
- НЕ зависит от LEAD-004 (event bus) — без событий

## После релиза

- Включить модуль `audit_mode` для core-клиентов через `PUT /api/tenant-modules/audit_mode {enabled:true}`
- Документация в `OWNER_GUIDE.md` (новый раздел «Аудит-режим» + screenshot)
- Маркетинг: лендинг «Аудит копейка-в-копейку» (см. STRATEGY_COCKPIT §9.3 — публичный реестр сданных деклараций)
