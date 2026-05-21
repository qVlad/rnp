"""Broadcast Telegram-сообщений всем директорам тенанта.

До 0054 был один-единственный получатель — `AppSetting.tg_chat_id` тенанта.
Теперь:

1) Сначала шлём всем юзерам с `tg_chat_id IS NOT NULL` подходящей роли
   (по умолчанию director + head_of_sales).
2) Если ни один user-chat не настроен — fallback на AppSetting.tg_chat_id
   (backward-compat).

Используется из:
- `api/supply_send.py` — Manager → директорам заявка на закупку
- `api/plan_edit_requests.py` — Manager → директорам заявка на правку
- Будущие notification-engine'ы

Все шлются параллельно (asyncio.gather) — не блокируем основную операцию.
Возвращаем счёт успешных/failed для аудита.
"""
from __future__ import annotations

import asyncio
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import AppSetting, User
from app.integrations.telegram import send_message


log = get_logger(__name__)


async def broadcast_to_directors(
    session: AsyncSession,
    text: str,
    *,
    parse_mode: str = "HTML",
    roles: Iterable[str] = ("director", "head_of_sales"),
) -> dict[str, int]:
    """Шлём всем юзерам с `tg_chat_id` подходящей роли. Fallback — AppSetting.

    Возвращает `{"sent": N, "failed": M, "recipients": [chat_ids]}`.
    Никогда не raises — fail-open, мы не должны блокировать main-flow
    если у одного из директоров проблемы с ботом.
    """
    chat_ids: list[str] = []
    try:
        rows = (
            await session.execute(
                select(User.tg_chat_id)
                .where(User.role.in_(list(roles)))
                .where(User.is_active.is_(True))
                .where(User.tg_chat_id.isnot(None))
            )
        ).scalars().all()
        chat_ids = [str(cid) for cid in rows if cid]
    except Exception as e:  # noqa: BLE001
        log.warning("broadcast_to_directors users-fetch failed: %s", e)

    # Fallback на legacy AppSetting если ни один user не привязан
    if not chat_ids:
        try:
            row = (
                await session.execute(
                    select(AppSetting.value).where(AppSetting.key == "tg_chat_id")
                )
            ).first()
            if row and row[0]:
                chat_ids = [str(row[0])]
        except Exception as e:  # noqa: BLE001
            log.warning("broadcast_to_directors fallback-fetch failed: %s", e)

    if not chat_ids:
        return {"sent": 0, "failed": 0, "recipients": []}

    results = await asyncio.gather(
        *(send_message(cid, text, parse_mode=parse_mode) for cid in chat_ids),
        return_exceptions=True,
    )
    sent = sum(1 for r in results if r is True)
    failed = len(results) - sent
    return {"sent": sent, "failed": failed, "recipients": chat_ids}
