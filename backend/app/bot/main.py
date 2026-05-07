"""Telegram bot — long-polling worker process.

Loops on getUpdates and dispatches to handlers. Stores chat_id in the
`settings` table on /start so daily digests know where to deliver.

Run: `python -m app.bot.main`  (Docker service `bot` does this).
"""
from __future__ import annotations

import asyncio
import contextlib
import signal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.bot.digest import build_alerts, build_now, build_pnl_short
from app.core.config import settings
from app.core.logging import get_logger
from app.db.models import AppSetting
from app.db.session import task_session_scope
from app.integrations.telegram import get_me, get_updates, send_message

log = get_logger(__name__)


HELP = (
    "Доступные команды:\n"
    "/now — KPI сегодня / неделя / месяц\n"
    "/alerts — текущие пороговые алерты\n"
    "/pnl — короткий P&L за неделю и месяц\n"
    "/help — это сообщение"
)


async def _save_setting(key: str, value: str) -> None:
    async with task_session_scope() as session:
        stmt = pg_insert(AppSetting).values(key=key, value=value)
        stmt = stmt.on_conflict_do_update(index_elements=["key"], set_={"value": value})
        await session.execute(stmt)


async def _read_setting(key: str) -> str | None:
    async with task_session_scope() as session:
        row = (
            await session.execute(select(AppSetting).where(AppSetting.key == key))
        ).scalar_one_or_none()
        return row.value if row else None


async def _is_authorized(chat_id: int) -> bool:
    """Personal-mode auth: any chat that has called /start at least once is allowed.

    The first user to /start the bot becomes the owner. Subsequent /start from
    other chat_ids are rejected to prevent strangers from snooping on KPIs if the
    bot username leaks. Owner can switch by calling /resetowner from the saved chat.
    """
    saved = await _read_setting("tg_chat_id")
    if not saved:
        return True  # not yet linked — first /start wins
    return saved == str(chat_id)


async def _handle_command(chat_id: int, text: str) -> None:
    cmd = text.split()[0].lower()
    args = text.split()[1:]

    if cmd in ("/start", "/help"):
        saved = await _read_setting("tg_chat_id")
        if not saved:
            await _save_setting("tg_chat_id", str(chat_id))
            await send_message(
                chat_id,
                "✅ <b>Готово!</b> Этот чат привязан к РНП.\n\n"
                "Теперь вы будете получать ежедневные сводки в 09:00 МСК.\n\n"
                + HELP,
            )
        elif saved == str(chat_id):
            await send_message(chat_id, "Этот чат уже привязан.\n\n" + HELP)
        else:
            await send_message(
                chat_id,
                "🚫 Бот уже привязан к другому чату. "
                "Если это ваш бот — отправьте /resetowner с привязанного чата.",
            )
        return

    if cmd == "/resetowner":
        if await _is_authorized(chat_id):
            await _save_setting("tg_chat_id", str(chat_id))
            await send_message(chat_id, "✅ Владелец сменён на этот чат.")
        else:
            await send_message(chat_id, "🚫 Только текущий владелец может сменить привязку.")
        return

    # All other commands require auth
    if not await _is_authorized(chat_id):
        await send_message(chat_id, "🚫 Этот бот не привязан к вашему чату.")
        return

    try:
        if cmd == "/now":
            await send_message(chat_id, await build_now())
        elif cmd == "/alerts":
            await send_message(chat_id, await build_alerts())
        elif cmd == "/pnl":
            await send_message(chat_id, await build_pnl_short())
        else:
            await send_message(chat_id, HELP)
    except Exception as e:  # noqa: BLE001
        log.exception("bot: command %s failed: %s", cmd, e)
        await send_message(chat_id, f"⚠ Ошибка обработки команды: {type(e).__name__}")


async def _poll_loop(stop_event: asyncio.Event) -> None:
    if not settings.tg_bot_token:
        log.warning("TG bot token not set — bot service idle")
        await stop_event.wait()
        return

    me = await get_me()
    if not me:
        log.error("TG getMe failed — token invalid? Sleeping 60s and retry.")
        await asyncio.sleep(60)
    else:
        log.info("TG bot started: @%s", me.get("username"))

    offset = 0
    while not stop_event.is_set():
        try:
            updates = await get_updates(offset=offset, timeout=30)
            for upd in updates:
                offset = upd["update_id"] + 1
                msg = upd.get("message")
                if not msg:
                    continue
                text = (msg.get("text") or "").strip()
                chat = msg.get("chat") or {}
                chat_id = chat.get("id")
                if not chat_id:
                    continue
                if text.startswith("/"):
                    await _handle_command(chat_id, text)
        except Exception as e:  # noqa: BLE001
            log.exception("bot poll error: %s", e)
            await asyncio.sleep(5)


async def main() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)
    await _poll_loop(stop)


if __name__ == "__main__":
    asyncio.run(main())
