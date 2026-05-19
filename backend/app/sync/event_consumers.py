"""Event-bus consumers — Celery beat tasks которые периодически читают
очереди событий и обрабатывают их.

Дизайн: pull-based, не infinite loop. Каждый beat-тик worker делает
`consume_batch(block_ms=10_000)` — блокируется на 10 сек ожидая сообщений,
читает что есть (или таймаут), обрабатывает, выходит. Celery worker'у проще
управлять такими задачами, чем долгоживущими subscriber'ами.

Каждый consumer group = отдельная Celery task. Если задача упала, beat
запустит её снова через 30 сек — XPENDING сохранит unack'нутые сообщения.

См. spec: `agents/references/spec-event-bus.md` (LEAD-004).
"""
from __future__ import annotations

import asyncio
import logging
import socket
from typing import Any

from app.services.event_bus import (
    EventType,
    consume_batch,
    reclaim_pending,
    publish,
)
from app.sync.celery_app import celery_app

log = logging.getLogger(__name__)


# Имя consumer'а внутри group: hostname + pid → уникально на worker. Если
# worker крашится — другой consumer reclaim'нёт его pending через watchdog.
def _consumer_name(suffix: str = "") -> str:
    host = socket.gethostname() or "worker"
    return f"{host}-{suffix}" if suffix else host


# ─── Handlers ──────────────────────────────────────────────────────────


async def _handle_chargeback_telegram(event: dict[str, Any]) -> None:
    """Уведомить через Telegram о крупном списании WB.

    В v1 просто log.info с emoji — реальный bot-handler подключим когда
    разрулим contracts с bot/main.py (там tenant-aware Telegram chat lookup).
    """
    data = event.get("data") or {}
    amount = data.get("amount_rub", 0)
    cat = data.get("supplier_oper_name", data.get("category", "?"))
    nm = data.get("nm_id")
    sku_part = f" · nm {nm}" if nm else ""
    log.info(
        "📨 [chargeback_detected] tenant=%d %s%s · %.0f₽ · rrd %s",
        event.get("tenant_id", 0),
        cat,
        sku_part,
        amount,
        data.get("rrd_id"),
    )
    # TODO: интегрировать с bot/main.py — найти tg_chat_id для tenant и
    # послать sendMessage. Сейчас telegram bot долгопул в отдельном сервисе
    # и не имеет публичного "send arbitrary message" API. Делаем отдельной
    # задачей.


# ─── Celery beat tasks ─────────────────────────────────────────────────


@celery_app.task(name="app.sync.event_consumers.consume_chargeback_telegram")
def consume_chargeback_telegram() -> dict[str, int]:
    """Consumer group `cg:telegram-chargeback` для CHARGEBACK_DETECTED.

    Запускается из beat каждые 30 сек. Читает batch до 50 событий, ACK'ает,
    публикует Telegram-уведомления для крупных списаний (>500₽ настроено
    в publisher chargebacks.py).
    """
    return asyncio.run(
        consume_batch(
            stream=EventType.CHARGEBACK_DETECTED,
            group="cg:telegram-chargeback",
            consumer=_consumer_name("tg-cb"),
            handler=_handle_chargeback_telegram,
            max_messages=50,
            block_ms=5_000,
        )
    )


@celery_app.task(name="app.sync.event_consumers.reclaim_all_pending")
def reclaim_all_pending() -> dict[str, dict[str, int]]:
    """Watchdog: для каждого активного stream'а проверяет pending list,
    перевыдаёт зависшие сообщения. После 5 retries → DLQ.

    Запускается из beat раз в 5 мин.
    """
    async def _run() -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for event_type, group in (
            (EventType.CHARGEBACK_DETECTED, "cg:telegram-chargeback"),
        ):
            out[f"{event_type.value}:{group}"] = await reclaim_pending(
                stream=event_type,
                group=group,
                consumer=_consumer_name("reclaim"),
            )
        return out

    return asyncio.run(_run())


# ─── Test publisher (только для smoke-теста) ──────────────────────────


@celery_app.task(name="app.sync.event_consumers.smoke_publish_chargeback")
def smoke_publish_chargeback(tenant_id: int = 1, amount: float = 1500.0) -> str:
    """Тестовая публикация события — для проверки шины в проде.

    Вызывается вручную: `celery -A app.sync.celery_app call \\
        app.sync.event_consumers.smoke_publish_chargeback`.
    """
    return asyncio.run(
        publish(
            EventType.CHARGEBACK_DETECTED,
            tenant_id=tenant_id,
            data={
                "rrd_id": 0,
                "category": "penalty",
                "supplier_oper_name": "Штраф (тест шины)",
                "amount_rub": amount,
                "nm_id": None,
                "operation_dt": None,
                "_smoke": True,
            },
        )
    )
