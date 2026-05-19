# Spec: Чарджбэки / штрафы / списания WB — LEAD-005

> Source: `agents/references/market/top-features-2026-05-17.md` Product #2 + `STRATEGY_COCKPIT.md` §5.3.  
> ICP: 20-200М/год, FBO, 50-500 SKU. Pricing add-on +3-5k₽/мес.  
> Author: Lead Agent — 2026-05-18.

## TL;DR

Лента непрозрачных списаний WB с workflow оспаривания. Парсим существующие `wb_report_detail` по словарю «проблемных» `supplier_oper_name`, создаём записи в `chargebacks` с initial-статусом `new`. UI: фильтры + statemachine workflow + PDF-реестр для отправки в WB-поддержку.

Без новых WB-интеграций — только парсинг существующих данных + надстройка UI/workflow.

## Persona validation (top-features-2026-05-17.md §A #2)

| Persona | Нужна? | Почему | Частота |
|---|:-:|---|---|
| **Selller** | ✅✅✅ MUST | «Где мои деньги?» — главная боль | еженедельно |
| **Manager WB** | ✅✅✅ MUST | Ежедневная реакция, узнаёт через 1-2 недели сейчас | ежедневно |
| **Accountant** | ✅✅ | База УПД + корректировки УСН | ежемесячно |
| **ROP** | ✅✅ | Контроль убытков по менеджерам | еженедельно |

## Канонический словарь оспоримых операций

Реальные `supplier_oper_name` с прода (на 2026-05-18, top по частоте):

| supplier_oper_name | Категория | Стандартное действие | Знак суммы |
|---|---|---|---|
| **Штраф** | `penalty` | Always disputable | — (расход) |
| **Удержание** | `deduction` | Always disputable | — |
| **Коррекция эквайринга** | `acquiring_correction` | Often disputable | — / + |
| **Коррекция логистики** | `delivery_correction` | Often disputable | — / + |
| **Коррекция продаж** | `sale_correction` | Often disputable | — / + |
| **Хранение товара с низким индексом остатка** | `low_il_storage_fee` | Disputable (если ИЛ невиновен) | — |
| **Платная приемка** | `paid_acceptance` | Sometimes disputable | — |
| **Коррекция компенсации скидки по программе лояльности** | `loyalty_correction` | Sometimes | — / + |
| **Компенсация ущерба** | `damage_compensation` | Informative (наша польза) | + |
| **Добровольная компенсация при возврате** | `voluntary_compensation` | Informative | — |

Не относятся к чарджбэкам (это нормальные операции, не оспариваются):
- Продажа / Возврат / Логистика / Хранение / Возмещение издержек по перевозке / Возмещение за выдачу

## Statemachine workflow

```
                  ┌──── new ─────┐
                  │              │
              сотрудник        автозакрытие
                  │            (мелкие суммы
                  │              < 100₽,
                  │              опц.)
                  ▼              │
              ┌─disputing─┐      │
              │           │      │
        ответ WB     отозвано    │
              │           │      │
              ▼           ▼      ▼
        ┌─resolved─┐  cancelled  auto_closed
        │          │
   recovered    rejected
   (вернули)    (WB отказал)
```

**Статусы:**

| code | label | Описание |
|---|---|---|
| `new` | Новое | Только что обнаружено в wb_report_detail, не работали |
| `disputing` | Оспаривается | Подана претензия в WB-поддержку |
| `resolved_recovered` | Вернули | WB одобрил, деньги вернулись |
| `resolved_rejected` | Отказали | WB отказал в оспаривании |
| `cancelled` | Отозвано | Решили не оспаривать |
| `auto_closed` | Авто-закрыто | Мелкая сумма, не стоит времени |

**Переходы:** только вперёд по графу выше + от `disputing` обратно в `new` (если ошиблись).

## Модель данных

```sql
-- Миграция 0036_chargebacks
CREATE TABLE chargebacks (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT REFERENCES tenants(id) ON DELETE CASCADE,
    -- Идентификация в wb_report_detail (для дедупликации)
    rrd_id BIGINT NOT NULL,                  -- FK на wb_report_detail.rrd_id (не enforced для cross-tenant)
    realizationreport_id BIGINT,             -- для группировки по отчёту
    -- Классификация
    category VARCHAR(32) NOT NULL,           -- penalty/deduction/.../damage_compensation
    supplier_oper_name VARCHAR(128) NOT NULL,
    -- Финансы
    amount_rub NUMERIC(14,2) NOT NULL,       -- сумма списания (положительная для расходов, отрицательная для возмещений)
    nm_id BIGINT,                            -- к какому SKU (если применимо)
    -- Workflow
    status VARCHAR(32) NOT NULL DEFAULT 'new',
    -- Даты
    operation_dt DATE,                        -- supplier_oper_dt из wb_report_detail
    rr_dt DATE,                               -- когда WB записал
    -- Free fields
    comment TEXT,
    claim_text TEXT,                          -- текст подаваемой претензии
    claim_filed_at TIMESTAMP WITH TIME ZONE,
    wb_response TEXT,
    wb_responded_at TIMESTAMP WITH TIME ZONE,
    recovered_amount NUMERIC(14,2),           -- сколько реально вернули (для resolved_recovered)
    -- Audit
    created_by VARCHAR(64) NOT NULL DEFAULT 'system',
    updated_by VARCHAR(64),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    UNIQUE (tenant_id, rrd_id, category)     -- дедуп: один rrd_id × одна категория = одна запись
);
CREATE INDEX idx_chargebacks_period ON chargebacks(tenant_id, operation_dt);
CREATE INDEX idx_chargebacks_status ON chargebacks(tenant_id, status);

-- История переходов статуса (для прозрачности — кто когда что менял)
CREATE TABLE chargeback_history (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT REFERENCES tenants(id) ON DELETE CASCADE,
    chargeback_id BIGINT REFERENCES chargebacks(id) ON DELETE CASCADE,
    from_status VARCHAR(32),
    to_status VARCHAR(32) NOT NULL,
    comment TEXT,
    actor VARCHAR(64) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL
);
```

## Парсер

```python
# services/chargebacks.py

async def sync_chargebacks(session: AsyncSession, *, tenant_id: int, lookback_days: int = 60) -> int:
    """Сканирует wb_report_detail за последние N дней, создаёт chargebacks
    для проблемных supplier_oper_name (если ещё нет). Идемпотентен по
    UNIQUE(tenant_id, rrd_id, category).
    """
    cutoff = date.today() - timedelta(days=lookback_days)
    rows = (await session.execute(
        select(WbReportDetail.rrd_id, WbReportDetail.supplier_oper_name,
               WbReportDetail.ppvz_for_pay, WbReportDetail.penalty,
               WbReportDetail.deduction, WbReportDetail.supplier_oper_dt,
               WbReportDetail.rr_dt, WbReportDetail.nm_id,
               WbReportDetail.realizationreport_id)
        .where(WbReportDetail.supplier_oper_name.in_(DISPUTABLE_OPER_NAMES))
        .where(WbReportDetail.sale_dt >= cutoff)
    )).all()
    created = 0
    for r in rows:
        category = OPER_NAME_TO_CATEGORY[r.supplier_oper_name]
        amount = _extract_amount(r, category)
        if abs(amount) < Decimal("0.01"):
            continue
        stmt = pg_insert(Chargeback).values(
            tenant_id=tenant_id,
            rrd_id=r.rrd_id,
            realizationreport_id=r.realizationreport_id,
            category=category,
            supplier_oper_name=r.supplier_oper_name,
            amount_rub=abs(amount),
            nm_id=r.nm_id,
            operation_dt=r.supplier_oper_dt,
            rr_dt=r.rr_dt,
            status="new",
            created_by="system",
        ).on_conflict_do_nothing(index_elements=["tenant_id", "rrd_id", "category"])
        result = await session.execute(stmt)
        if result.rowcount > 0:
            created += 1
    await session.commit()
    return created
```

Запуск:
- Celery beat task `sync_chargebacks` раз в час (после `sync_report_detail`)
- Или event-bus подписка на `sale.new` (после LEAD-004 реализации)

В v1 — простой beat-task.

## API

```
GET /api/chargebacks?status=...&category=...&date_from=...&date_to=...&limit=...
POST /api/chargebacks/sync                     # ручной запуск парсера
GET /api/chargebacks/{id}
PUT /api/chargebacks/{id}                       # обновить comment / claim_text
POST /api/chargebacks/{id}/transition           # body: {to_status, comment}
GET /api/chargebacks/stats?date_from=...&date_to=...  # сводка по категориям/статусам
GET /api/chargebacks/export.pdf?period=...      # PDF-реестр (v1.5)
```

Guard: `require_module("chargebacks")` + `require_director_or_head` для всех.

## Frontend

Страница `/chargebacks`:

```
┌──────────────────────────────────────────────────────────────────┐
│ Чарджбэки / штрафы WB              [Период: ▾] [Sync ↻]          │
├──────────────────────────────────────────────────────────────────┤
│ ┌─Сводка──┬─Штрафы──┬─Удержания──┬─Коррекции──┬─Возмещения──┐    │
│ │  new    │   12    │     5      │     8      │     2       │    │
│ │ Сумма   │ 45 678₽ │  12 345₽   │  3 456₽    │  +5 678₽    │    │
│ │         │ 5  P0   │  2  P0     │            │             │    │
│ └─────────┴─────────┴────────────┴────────────┴─────────────┘    │
├──────────────────────────────────────────────────────────────────┤
│ Фильтры: [Статус: все ▾] [Категория ▾] [Сумма от]                │
│                                                                  │
│ Дата       │ Категория  │ SKU    │ Сумма    │ Статус    │ ⋯     │
│────────────┼────────────┼────────┼──────────┼───────────┼───────│
│ 2026-04-15 │ Штраф      │ 12345  │ -1 200₽  │ Новое     │ [⚙]   │
│ 2026-04-14 │ Удержание  │ —      │ -3 500₽  │ Оспаривается │[⚙] │
│ 2026-04-12 │ Корр.лог.  │ 67890  │ +234₽    │ Авто-закрыто│      │
└──────────────────────────────────────────────────────────────────┘
```

Клик по строке → раскрывается панель с:
- Описанием (raw supplier_oper_name + дата + сумма + ссылка на rrd_id)
- Свободный комментарий (textarea)
- Текст претензии (claim_text textarea)
- Workflow-кнопки переходов («Подать претензию», «Получил отказ», «Деньги вернулись», «Отозвать»)
- История изменений (chargeback_history)

## Что НЕ делаем в v1

- ❌ Авто-подача претензий в WB-поддержку через API (WB не даёт public API для этого)
- ❌ AI-генерация текста претензии (Фаза 2)
- ❌ Telegram-алерт при списании > N₽ (после реализации event-bus, LEAD-004)
- ❌ Авто-эскалация при отсутствии реакции от WB > 14 дней (опц. в v1.5)

## Реализация по этапам

### Этап 1 (S, ~2 дня) — Backend skeleton
- [ ] Миграция `0036_chargebacks` (chargebacks + chargeback_history)
- [ ] Модели `Chargeback`, `ChargebackHistory` в `db/models.py`
- [ ] `services/chargebacks.py`: словарь категорий, парсер `sync_chargebacks()`, statemachine `transition()`
- [ ] Beat-task `sync_chargebacks` в `sync/celery_app.py`

### Этап 2 (S, ~2 дня) — API
- [ ] `api/chargebacks.py`: list / get / put / transition / stats / sync endpoints
- [ ] Guard: `require_module("chargebacks")` + `require_director_or_head`

### Этап 3 (M, ~3 дня) — Frontend
- [ ] `pages/Chargebacks.tsx` — лента с фильтрами + расширяющиеся строки + workflow-кнопки
- [ ] Типизированный API client
- [ ] Маршрут + меню (за `directorOrHead`)

### Этап 4 (опц.) — PDF-реестр (v1.5)
- [ ] `services/chargebacks_pdf.py` — генерация через `reportlab` или `weasyprint`
- [ ] Кнопка «Скачать реестр претензий» на странице

### Этап 5 (после LEAD-004) — Telegram-алерт
- [ ] Подписка на `chargeback.detected` event → push в bot

## Зависимости

- LEAD-007 (feature_flags) ✅ — `require_module("chargebacks")` уже доступен
- LEAD-004 (event-bus) — ⏸ только для Этапа 5 (Telegram-алерт); v1 работает без

## После релиза
- Включить модуль `chargebacks` через `PUT /api/tenant-modules/chargebacks {enabled:true}`
- Запустить ручной `POST /api/chargebacks/sync` для backfill за 60 дней
- TASK-PA-NNN (persona-accountant): валидация категоризации
- TASK-PS-NNN (persona-seller): валидация UX «один клик чтобы начать претензию»
