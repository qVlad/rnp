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

from sqlalchemy import select

from app.db.models import AppSetting
from app.integrations.telegram import send_message
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


async def _get_tg_chat_id(tenant_id: int) -> str | None:
    """Достаёт привязанный Telegram chat_id для tenant'а из AppSetting.

    Каждый tenant имеет свой chat_id (или None если бот ещё не подключён).
    Возвращается строкой — Telegram API принимает и int, и string.
    """
    from app.db.session import task_session_scope
    from app.services.tenant_context import set_tenant

    async with task_session_scope() as session:
        set_tenant(session, tenant_id)
        row = (
            await session.execute(
                select(AppSetting).where(
                    AppSetting.tenant_id == tenant_id,
                    AppSetting.key == "tg_chat_id",
                )
            )
        ).scalar_one_or_none()
        return row.value if row else None


# ─── Handlers ──────────────────────────────────────────────────────────


async def _handle_chargeback_telegram(event: dict[str, Any]) -> None:
    """Уведомить через Telegram о крупном списании WB.

    Берёт `tg_chat_id` из `app_settings` per-tenant (привязывается через
    `/start` в bot/main.py). Если для tenant'а нет chat_id — silent skip.
    """
    tenant_id = int(event.get("tenant_id", 0))
    chat_id = await _get_tg_chat_id(tenant_id)
    if not chat_id:
        log.debug(
            "chargeback event tenant=%d skipped — no tg_chat_id bound",
            tenant_id,
        )
        return

    data = event.get("data") or {}
    amount = data.get("amount_rub", 0)
    cat_name = data.get("supplier_oper_name", data.get("category", "?"))
    nm = data.get("nm_id")
    rrd_id = data.get("rrd_id")
    op_dt = data.get("operation_dt", "")[:10] if data.get("operation_dt") else ""

    sku_line = f"\nSKU: <code>{nm}</code>" if nm else ""
    date_line = f"\nДата операции: {op_dt}" if op_dt else ""

    text = (
        f"⚠ <b>WB списал {amount:,.0f}₽</b>\n"
        f"{cat_name}{sku_line}{date_line}\n"
        f"rrd_id: <code>{rrd_id}</code>\n\n"
        f"Подробнее → /chargebacks"
    )
    try:
        await send_message(int(chat_id), text)
        log.info(
            "chargeback notify sent tenant=%d chat=%s amount=%.0f",
            tenant_id,
            chat_id,
            amount,
        )
    except Exception:
        log.exception(
            "chargeback notify failed tenant=%d chat=%s — will retry via XPENDING",
            tenant_id,
            chat_id,
        )
        raise  # триггерит retry watchdog (не ACK'ается)


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
