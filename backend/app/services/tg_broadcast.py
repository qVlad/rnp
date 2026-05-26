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
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import AppSetting, User
from app.integrations.telegram import send_message


log = get_logger(__name__)


async def notify_user(
    session: AsyncSession,
    user_id: int,
    text: str,
    *,
    parse_mode: str = "HTML",
) -> bool:
    """Шлём конкретному юзеру через его `users.tg_chat_id`.

    Fail-open: если юзер не привязал TG — просто `return False`, не raises.
    Используется для back-loop'а нотификаций (например, manager узнаёт что
    его plan_edit_request приняли/отклонили).
    """
    try:
        chat_id = (
            await session.execute(
                select(User.tg_chat_id).where(
                    User.id == user_id, User.tg_chat_id.isnot(None)
                )
            )
        ).scalar_one_or_none()
        if not chat_id:
            return False
        return await send_message(str(chat_id), text, parse_mode=parse_mode)
    except Exception as e:  # noqa: BLE001
        log.warning("notify_user failed (user_id=%s): %s", user_id, e)
        return False


async def notify_user_or_boss(
    session: AsyncSession,
    user_id: int,
    text: str,
    *,
    parse_mode: str = "HTML",
) -> dict[str, Any]:
    """Шлём приоритетно boss'у (если у user'а есть `boss_id`), fallback на self.

    HYP-007 (TASK-DEV-XXX): manager жмёт «📨 в Telegram» в /weekly-report →
    отчёт должен попадать его РОПу (boss), а не в личку. Если boss не
    назначен или у boss'а нет tg_chat_id → fallback на свой tg_chat_id.

    Returns `{sent: bool, recipient: "boss" | "self" | "none",
              boss_id: int | None, boss_name: str | None, redirected: bool}`.
    `redirected=True` означает «отправили не туда где ожидал отправитель»
    (т.е. boss'у). `boss_name` (TASK-LEAD-128) — full_name boss'а либо
    username, для UI feedback'а («Отправлено руководителю Иванов И.»).
    Used для audit-логирования вызывающей стороной.
    """
    result: dict[str, Any] = {
        "sent": False,
        "recipient": "none",
        "boss_id": None,
        "boss_name": None,
        "redirected": False,
    }
    try:
        row = (
            await session.execute(
                select(User.boss_id, User.tg_chat_id).where(User.id == user_id)
            )
        ).first()
        if not row:
            return result
        boss_id, self_chat = row[0], row[1]

        # 1. Try boss first
        if boss_id is not None:
            boss_row = (
                await session.execute(
                    select(User.tg_chat_id, User.full_name, User.username).where(
                        User.id == boss_id,
                        User.is_active.is_(True),
                        User.tg_chat_id.isnot(None),
                    )
                )
            ).first()
            if boss_row:
                boss_chat, boss_full_name, boss_username = boss_row
                ok = await send_message(str(boss_chat), text, parse_mode=parse_mode)
                if ok:
                    result.update(
                        sent=True,
                        recipient="boss",
                        boss_id=boss_id,
                        boss_name=boss_full_name or boss_username,
                        redirected=True,
                    )
                    return result
                # boss send failed — fallthrough to self

        # 2. Fallback на свой chat
        if self_chat:
            ok = await send_message(str(self_chat), text, parse_mode=parse_mode)
            if ok:
                result.update(sent=True, recipient="self", boss_id=boss_id)
                return result
        return result
    except Exception as e:  # noqa: BLE001
        log.warning("notify_user_or_boss failed (user_id=%s): %s", user_id, e)
        return result


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
