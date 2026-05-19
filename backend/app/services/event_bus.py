"""Internal event bus на Redis Streams.

См. spec: `agents/references/spec-event-bus.md` (LEAD-004).

Архитектурный фундамент для модульной разработки. Без шины каждый новый
product-модуль (chargebacks / redistribution / bidder / reviews) поллил бы
БД для реакции на «новая продажа», «остаток упал», «штраф пришёл» —
N² сложности. С шиной модули подписываются на типизированные события.

## Использование

```python
# Publisher (в Celery task после успешного INSERT):
from app.services.event_bus import publish, EventType
await publish(
    EventType.CHARGEBACK_DETECTED,
    tenant_id=1,
    data={"chargeback_id": 42, "amount_rub": 1500, "category": "penalty"},
)

# Consumer (в отдельном Celery beat task, raises BaseException = retry):
from app.services.event_bus import consume_batch
async def handle(event):
    chargeback_id = event["data"]["chargeback_id"]
    # ... send telegram alert ...
await consume_batch(
    stream=EventType.CHARGEBACK_DETECTED,
    group="cg:telegram-bot",
    consumer="telegram-1",
    handler=handle,
    max_messages=50,
    block_ms=10_000,
)
```

## Идемпотентность

Event ID = UUIDv7-like (time-ordered) хранится в `data.event_id` поля payload.
Handler'ы проверяют что событие не обработано через Redis SET
`rnp:event_seen:<group>:<event_id>` с TTL 24h. Дубликат → skip + ACK.

## Retry / DLQ

При исключении в handler — НЕ ACK'аем. Watchdog beat-task раз в 5 мин делает
XPENDING + XCLAIM для застрявших > 10 мин. После 5 повторов — переезд в
DLQ stream `rnp:dlq:<original-stream>` + alert админу через telegram.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Awaitable, Callable, Final

import redis.asyncio as aioredis

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)


# ── Singleton Redis client ────────────────────────────────────────────
_REDIS: aioredis.Redis | None = None


def _redis() -> aioredis.Redis:
    """Lazy singleton — один pool на процесс. Тот же подход что в rate_limit."""
    global _REDIS
    if _REDIS is None:
        _REDIS = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _REDIS


# ── Canonical event types ─────────────────────────────────────────────
class EventType(str, Enum):
    """Канонические типы событий. Расширять по мере добавления модулей.

    См. `agents/references/spec-event-bus.md` для payload schema каждого.
    """

    SALE_NEW = "sale.new"
    STOCK_LOW = "stock.low"
    CHARGEBACK_DETECTED = "chargeback.detected"
    REDISTRIBUTION_WINDOW_OPEN = "redistribution.window.open"
    REDISTRIBUTION_TASK_COMPLETED = "redistribution.task.completed"
    TAX_DEADLINE_UPCOMING = "tax.deadline.upcoming"
    BIDDER_RULE_FIRED = "bidder.rule.fired"
    FEEDBACK_NEGATIVE = "feedback.negative"


# Максимальная длина stream'а (XADD MAXLEN ~). Защита от роста БД Redis.
STREAM_MAXLEN: Final = 10_000

# TTL для idempotency-маркеров: 24h. После этого event может «реплицироваться»
# при reclaim'е, но обычно сообщение либо ACK'нуто, либо в DLQ задолго до.
DEDUP_TTL_SECONDS: Final = 86400

# Префикс ключей. Меняем — старые streams удалятся, обработка с нуля.
STREAM_PREFIX: Final = "rnp:events:"
DLQ_PREFIX: Final = "rnp:dlq:"
DEDUP_PREFIX: Final = "rnp:event_seen:"


def stream_name(event_type: str | EventType) -> str:
    """Канонический stream-key для типа события."""
    code = event_type.value if isinstance(event_type, EventType) else event_type
    return f"{STREAM_PREFIX}{code}"


def dlq_name(event_type: str | EventType) -> str:
    code = event_type.value if isinstance(event_type, EventType) else event_type
    return f"{DLQ_PREFIX}{code}"


def _uuid7() -> str:
    """Простая time-ordered UUID (UUIDv7-подобная).

    Python stdlib до 3.13 не имеет uuid7(). Делаем сами: 48 бит мс-таймстамп +
    74 бита случайности. Свойство «лексикографически сортируется по времени»
    помогает Redis Streams и облегчает отладку.
    """
    ts_ms = int(time.time() * 1000)
    rand = uuid.uuid4().int & ((1 << 74) - 1)
    val = (ts_ms << 80) | (0x7 << 76) | rand
    hex_str = f"{val:032x}"
    return (
        f"{hex_str[:8]}-{hex_str[8:12]}-{hex_str[12:16]}-"
        f"{hex_str[16:20]}-{hex_str[20:32]}"
    )


# ── Publisher ─────────────────────────────────────────────────────────
async def publish(
    event_type: str | EventType,
    *,
    tenant_id: int,
    data: dict[str, Any],
    version: int = 1,
) -> str:
    """Опубликовать событие. Возвращает event_id (UUIDv7).

    Payload в Redis Stream: все поля как hash. Сериализация — JSON для `data`,
    плоские строки для остального.

    NOT raises на сетевых ошибках Redis — log.warning + возврат пустой строки.
    Event bus НЕ должен ломать основную транзакцию.
    """
    event_id = _uuid7()
    code = event_type.value if isinstance(event_type, EventType) else event_type
    payload = {
        "id": event_id,
        "type": code,
        "tenant_id": str(tenant_id),
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "data": json.dumps(data, ensure_ascii=False, default=str),
        "version": str(version),
    }
    try:
        await _redis().xadd(
            stream_name(code),
            payload,
            maxlen=STREAM_MAXLEN,
            approximate=True,
        )
        log.debug("event_bus published %s %s tenant=%d", code, event_id, tenant_id)
    except Exception as e:
        # Не валим основной flow — шина это лучший-effort механизм
        log.warning(
            "event_bus publish %s failed (%s): %s — event lost",
            code,
            type(e).__name__,
            e,
        )
        return ""
    return event_id


def parse_event(fields: dict[str, str]) -> dict[str, Any]:
    """Десериализует XREADGROUP entry в python dict."""
    data_str = fields.get("data") or "{}"
    try:
        data = json.loads(data_str)
    except json.JSONDecodeError:
        data = {}
    return {
        "id": fields.get("id", ""),
        "type": fields.get("type", ""),
        "tenant_id": int(fields.get("tenant_id") or 0),
        "occurred_at": fields.get("occurred_at"),
        "data": data,
        "version": int(fields.get("version") or 1),
    }


# ── Consumer helpers ──────────────────────────────────────────────────


async def _ensure_group(stream: str, group: str) -> None:
    """Idempotent создание consumer group. mkstream=True если stream пустой."""
    try:
        await _redis().xgroup_create(stream, group, id="$", mkstream=True)
        log.info("event_bus created consumer group %s on %s", group, stream)
    except aioredis.ResponseError as e:
        if "BUSYGROUP" not in str(e):
            raise


async def _is_duplicate(group: str, event_id: str) -> bool:
    """Idempotency check. SET NX с TTL: первый вызов возвращает True (set'нул),
    повторный — False (ключ уже есть). Логика инвертирована: если SETNX вернул
    False → событие уже обработано → True (duplicate).
    """
    key = f"{DEDUP_PREFIX}{group}:{event_id}"
    was_set = await _redis().set(key, "1", nx=True, ex=DEDUP_TTL_SECONDS)
    return was_set is None or was_set is False


EventHandler = Callable[[dict[str, Any]], Awaitable[None]]


async def consume_batch(
    *,
    stream: str | EventType,
    group: str,
    consumer: str,
    handler: EventHandler,
    max_messages: int = 50,
    block_ms: int = 5_000,
) -> dict[str, int]:
    """Одна итерация чтения batch'а сообщений + обработка.

    Возвращает stats: {processed, duplicates, errors}. Используется в Celery
    beat task — каждые N секунд тик: читает доступные сообщения, обрабатывает,
    выходит. NOT infinite loop (Celery worker'у проще).
    """
    s = stream.value if isinstance(stream, EventType) else stream
    s = stream_name(s) if not s.startswith(STREAM_PREFIX) else s
    await _ensure_group(s, group)
    processed = 0
    duplicates = 0
    errors = 0
    r = _redis()
    try:
        result = await r.xreadgroup(
            group,
            consumer,
            {s: ">"},
            count=max_messages,
            block=block_ms,
        )
    except aioredis.ResponseError as e:
        log.warning("event_bus xreadgroup %s/%s: %s", s, group, e)
        return {"processed": 0, "duplicates": 0, "errors": 1}
    if not result:
        return {"processed": 0, "duplicates": 0, "errors": 0}
    for _stream_name, entries in result:
        for msg_id, fields in entries:
            event = parse_event(fields)
            if not event["id"]:
                # malformed payload — ACK чтобы не циклить, и считаем ошибкой
                await r.xack(s, group, msg_id)
                errors += 1
                continue
            if await _is_duplicate(group, event["id"]):
                await r.xack(s, group, msg_id)
                duplicates += 1
                continue
            try:
                await handler(event)
                await r.xack(s, group, msg_id)
                processed += 1
            except Exception:
                # НЕ ACK'аем — message висит в pending list, watchdog поднимет
                log.exception(
                    "event_bus handler failed event_id=%s stream=%s group=%s",
                    event["id"],
                    s,
                    group,
                )
                errors += 1
    return {"processed": processed, "duplicates": duplicates, "errors": errors}


async def reclaim_pending(
    *,
    stream: str | EventType,
    group: str,
    consumer: str,
    min_idle_ms: int = 10 * 60_000,  # 10 минут
    max_messages: int = 50,
    max_deliveries: int = 5,
) -> dict[str, int]:
    """Watchdog: проверяет XPENDING для group, делает XCLAIM для застрявших
    сообщений (idle > min_idle_ms), перевыдаёт текущему consumer'у.

    Если сообщение доставлялось > max_deliveries раз — переезжает в DLQ
    stream и ACK'ается в исходном (чтобы перестало висеть в pending).

    Запускается из beat-task каждые 5 мин.
    """
    s = stream.value if isinstance(stream, EventType) else stream
    s = stream_name(s) if not s.startswith(STREAM_PREFIX) else s
    r = _redis()
    reclaimed = 0
    dlqd = 0
    try:
        pending = await r.xpending_range(
            s, group, min="-", max="+", count=max_messages
        )
    except aioredis.ResponseError as e:
        log.warning("event_bus xpending %s/%s: %s", s, group, e)
        return {"reclaimed": 0, "dlqd": 0}

    for entry in pending:
        msg_id = entry["message_id"]
        deliveries = int(entry["times_delivered"])
        idle_ms = int(entry["time_since_delivered"])
        if idle_ms < min_idle_ms:
            continue

        # Достаём содержимое
        try:
            data = await r.xrange(s, min=msg_id, max=msg_id, count=1)
        except Exception:
            data = []
        if not data:
            # Message пропал из stream (вне maxlen) — ACK и забываем
            await r.xack(s, group, msg_id)
            continue

        if deliveries >= max_deliveries:
            # Переезд в DLQ
            _, fields = data[0]
            await r.xadd(dlq_name(s.removeprefix(STREAM_PREFIX)), fields)
            await r.xack(s, group, msg_id)
            dlqd += 1
            log.error(
                "event_bus DLQ event_id=%s stream=%s group=%s deliveries=%d",
                fields.get("id"),
                s,
                group,
                deliveries,
            )
            continue

        # XCLAIM — перевыдать текущему consumer'у (он на след. consume_batch
        # увидит сообщение и попытается обработать)
        try:
            await r.xclaim(s, group, consumer, min_idle_ms, [msg_id])
            reclaimed += 1
        except Exception:
            log.exception("event_bus xclaim failed for %s", msg_id)
    return {"reclaimed": reclaimed, "dlqd": dlqd}


# ── Утилиты для тестов / админа ───────────────────────────────────────


async def stream_info(event_type: str | EventType) -> dict[str, Any]:
    """Статистика по stream'у для диагностики."""
    s = stream_name(event_type)
    try:
        info = await _redis().xinfo_stream(s)
        return {
            "length": info.get("length", 0),
            "first_entry_id": (info.get("first-entry") or [None])[0],
            "last_entry_id": (info.get("last-entry") or [None])[0],
            "groups": info.get("groups", 0),
        }
    except aioredis.ResponseError:
        return {"length": 0, "first_entry_id": None, "last_entry_id": None, "groups": 0}


# Synchronous helper для тестов с asyncio.run
def publish_sync(event_type: str | EventType, *, tenant_id: int, data: dict) -> str:
    """Удобный sync wrapper для тестов / интерактивной отладки."""
    return asyncio.run(publish(event_type, tenant_id=tenant_id, data=data))
