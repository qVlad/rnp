# Spec: Internal Event Bus (Redis Streams)

> Source: `agents/references/market/top-features-2026-05-17.md` Tech #2.  
> Author: Lead Agent — 2026-05-18.  
> Status: draft v1 (требует `clean-architect` ревью перед реализацией).

## TL;DR

Внутренняя шина событий на **Redis Streams** + **consumer groups**. Унифицирует
интеграцию product-модулей (chargebacks, redistribution, bidder, reviews) с
core-данными (orders/sales/report_detail). Без шины — каждый модуль будет
poll'ить БД, через 3 модуля код «слипнется».

**Не SaaS-event-grid, не RabbitMQ, не Kafka.** Redis Streams выбран потому что
Redis уже в стеке, надёжность достаточна для нашего объёма (~10k events/день),
запуск + поддержка тривиален.

## Архитектура

```
┌──────────────────┐
│ Publishers       │     Worker Celery tasks (sync_orders, sync_sales,
│ (внутри РНП)     │     sync_report_detail, sync_advert, …) после успешного
└────────┬─────────┘     INSERT в БД публикуют событие.
         │
         ▼
┌──────────────────┐
│ Redis Streams    │     По одному stream'у на event type:
│ rnp:events:*     │       rnp:events:sale.new
└────────┬─────────┘       rnp:events:stock.low
         │                 rnp:events:chargeback.detected
         │                 rnp:events:redistribution.window.open
         │                 rnp:events:tax.deadline.upcoming
         ▼                 rnp:events:bidder.rule.fired
┌──────────────────┐       rnp:events:feedback.negative
│ Consumer Groups  │
│ per-модуль       │     Каждый subscriber = consumer group:
└────────┬─────────┘       cg:telegram-bot — подписан на 4-5 stream'ов
         │                 cg:chargebacks-worker — на 2 stream'а
         │                 cg:redistribution-worker — на 3 stream'а
         ▼                 cg:notification-engine — на все
┌──────────────────┐
│ Worker handlers  │     Каждая consumer group → отдельный Celery worker
└──────────────────┘     (см. Celery segregation spec).
```

## Контракт события

Каждое событие имеет минимальный набор полей:

```python
{
    "id": str,              # UUIDv7 — для идемпотентности handler'ов
    "type": str,            # canonical name — "sale.new"
    "tenant_id": int,       # обязательно — все события tenant-scoped
    "occurred_at": str,     # ISO8601 UTC — когда event произошёл (не когда опубликован)
    "data": dict,           # payload, варьируется по type
    "version": int,         # 1 — для обратной совместимости при schema-evolution
}
```

Payload `data` фиксирован per-type (см. ниже). Любое расширение — bump
`version` и поддержка обоих в handler'ах в течение 1-2 релизов.

## Канонический список событий

| Type | Publisher | Subscribers | Payload (data) |
|---|---|---|---|
| `sale.new` | `sync_report_detail` после insert в `wb_report_detail` | bidder (триггер правил), redistribution (демаунт), notification | `{rrd_id, nm_id, sale_dt, amount_rub, supplier_oper_name}` |
| `stock.low` | `sync_stocks` после расчёта days_to_stockout | telegram-bot, redistribution (планирование) | `{nm_id, warehouse_name, stock, days_to_stockout}` |
| `chargeback.detected` | `sync_report_detail` для проблемных `supplier_oper_name` (Штраф, Удержание, Корректировка) | chargeback-worker (создать запись для оспаривания), telegram-bot | `{rrd_id, nm_id, amount_rub, supplier_oper_name, supplier_oper_dt}` |
| `redistribution.window.open` | Cron: 09:00 и 18:00 МСК (separate Celery beat task) | redistribution-worker | `{window_dt}` |
| `redistribution.task.completed` | redistribution-worker после успешной/неуспешной попытки | telegram-bot, roi-calc | `{task_id, nm_id, target_warehouse, success, latency_ms, error?}` |
| `tax.deadline.upcoming` | Cron daily 09:00 МСК: проверка ближайших налоговых дедлайнов | telegram-bot, dashboard-alerts | `{tax_system, deadline_dt, days_until}` |
| `bidder.rule.fired` | bidder-worker после применения правила к РК | audit, telegram-bot | `{campaign_id, rule_id, action, old_bid, new_bid}` |
| `feedback.negative` | feedback-sync (если будет в Фазе 2) — feedback rating 1-3 | telegram-bot, manager-assignment | `{feedback_id, nm_id, rating, brand, manager_username}` |

## Retry + DLQ

Стандартная Redis Streams семантика:

1. Handler читает через `XREADGROUP cg:<group> COUNT N BLOCK ms`
2. После успешной обработки — `XACK stream cg:<group> message_id`
3. Если handler упал / не ACK'нул — message висит в **pending list** consumer group
4. Watchdog Celery beat (раз в 5 мин) делает `XPENDING` + `XCLAIM` для застрявших
5. После 5 retry → переезд в DLQ stream `rnp:dlq:<original-stream>` + alert админу

**Idempotency.** Handler'ы должны быть идемпотентны по `event.id` (UUIDv7):
сохранять последний обработанный event_id per (cg, stream) в Redis и игнорить
дубли. Это защищает от двойной обработки при retry.

## Реализация

### Publisher

```python
# app/services/event_bus.py
from app.db.session import Redis  # singleton

async def publish(event_type: str, tenant_id: int, data: dict) -> str:
    event_id = uuid7()
    payload = {
        "id": event_id,
        "type": event_type,
        "tenant_id": tenant_id,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "data": json.dumps(data),
        "version": 1,
    }
    stream_name = f"rnp:events:{event_type}"
    await redis.xadd(stream_name, payload, maxlen=10_000)  # cap stream length
    return event_id
```

### Subscriber (Celery worker)

```python
# app/sync/event_consumers.py
async def consume_loop(stream: str, group: str, handler):
    # Ensure consumer group exists
    try:
        await redis.xgroup_create(stream, group, id="$", mkstream=True)
    except RedisError as e:
        if "BUSYGROUP" not in str(e): raise
    consumer_name = f"{group}-{os.getpid()}"
    while not shutdown_event.is_set():
        msgs = await redis.xreadgroup(
            group, consumer_name, {stream: ">"}, count=10, block=5_000
        )
        for stream_name, entries in msgs:
            for msg_id, fields in entries:
                event = _parse_event(fields)
                if await is_duplicate(group, event["id"]):
                    await redis.xack(stream, group, msg_id)
                    continue
                try:
                    await handler(event)
                    await mark_processed(group, event["id"])
                    await redis.xack(stream, group, msg_id)
                except Exception:
                    log.exception("event %s handler failed", event["id"])
                    # don't ACK — will be retried via XPENDING/XCLAIM watchdog
```

### Worker registration

```python
# app/sync/celery_app.py
celery_app.conf.beat_schedule["watchdog-pending-events"] = {
    "task": "app.sync.event_consumers.reclaim_pending",
    "schedule": 300.0,  # every 5 min
}
```

## Celery segregation (см. отдельную спеку — `spec-celery-segregation.md`)

Каждая consumer group обычно соответствует своему worker'у:

| Worker | Queues | Concurrency | Purpose |
|---|---|---|---|
| worker-stats | stats | 1 | sync_orders / sync_sales / sync_report_detail (existing) |
| worker-advert | advert | 2 | sync_advert / sync_ad_stats (existing) |
| worker-default | default | 4 | misc tasks (existing) |
| **worker-events** (new) | events | 2 | telegram-bot consumer, notification-engine, tax-deadline (lightweight) |
| **worker-redistribution** (new, на Фазе LEAD-008) | redistribution | 1 | сессии-capture отправка, идемпотент критичен |
| **worker-chargebacks** (new, на Фазе LEAD-005) | chargebacks | 2 | парсинг wb_report_detail, создание `chargebacks` rows |
| **worker-bidder** (когда/если Фаза 4+) | bidder | 1 | rate-limit WB критичен |

## Что НЕ делаем сейчас

- ❌ Saga-паттерны / state-machines между событиями — отложить до момента
  когда появится первый use-case (вероятно redistribution)
- ❌ Event sourcing — не наша модель (СУБД остаётся source of truth)
- ❌ CQRS — overkill для текущего объёма
- ❌ External message broker (RabbitMQ / Kafka) — Redis Streams достаточно
  до ~100k events/день

## Реализация в этапах

### Этап 1 (S, ~3 дня): Skeleton

- [ ] `app/services/event_bus.py` — publish, consume helpers
- [ ] `app/sync/event_consumers.py` — base consumer loop с reclaim
- [ ] Тест: round-trip publish → consume на in-memory Redis (fakeredis)
- [ ] Метрика published/consumed per stream (для дашборда ops)

### Этап 2 (S, ~2 дня): Первый publisher

- [ ] `sale.new` из `_sync_report_detail_async` после успешного insert
- [ ] Простой telegram-bot consumer: «новая продажа SKU X на Y₽» (dev-only флаг)
- [ ] Verify backflow: повторный sync не публикует дубли

### Этап 3 (M, ~1 нед): Полное покрытие core-событий

- [ ] `stock.low` из `sync_stocks`
- [ ] `chargeback.detected` (с базовым словарём проблемных операций)
- [ ] `tax.deadline.upcoming` (cron-based publisher)
- [ ] DLQ stream + admin alert через telegram-bot

### Этап 4 (M, ~1 нед): Worker segregation

- [ ] Изменения в `docker-compose.yml`: worker-events service
- [ ] Beat-расписание для cron-based publisher'ов
- [ ] Onboarding doc (`OPERATIONS.md`)

После этапов 1-4 можно стартовать LEAD-005 (чарджбэки используют `chargeback.detected`)
и LEAD-008 (перераспределение — `redistribution.window.open`).
