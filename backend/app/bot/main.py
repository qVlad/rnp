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
from app.db.models import AppSetting, User
from app.db.session import task_session_scope
from app.integrations.telegram import get_me, get_updates, send_message
from app.services.tenant_context import set_tenant

log = get_logger(__name__)


HELP = (
    "Доступные команды:\n"
    "/now — KPI сегодня / неделя / месяц\n"
    "/alerts — текущие пороговые алерты\n"
    "/pnl — короткий P&L за неделю и месяц\n"
    "/bind <username> — привязать свой логин РНП (для multi-recipient уведомлений)\n"
    "/unbind — отвязать свой логин\n"
    "/help — это сообщение"
)


async def _resolve_tenant_from_chat(chat_id: int) -> int | None:
    """Multi-tenant: chat_id → User.tg_chat_id → tenant_id.

    Если юзер не привязал — возвращает None (упадёт fallback'ом в
    `settings.bot_tenant_id` для legacy single-tenant поведения).
    Если несколько User'ов с одним chat_id (multi-tenant collision —
    юзер активен в двух тенантах сразу) — берём первый по id, чтобы
    хоть что-то отвечать; разруливание через /unbind + /bind.
    """
    async with task_session_scope() as session:
        # set_tenant не нужен — глобальный SELECT, нет RLS для bot-сервиса
        row = (
            await session.execute(
                select(User.tenant_id).where(
                    User.tg_chat_id == str(chat_id),
                    User.is_active.is_(True),
                ).order_by(User.id).limit(1)
            )
        ).scalar_one_or_none()
        return int(row) if row else None


async def _bind_user(chat_id: int, ident: str) -> str:
    """Привязать chat_id к User.tg_chat_id (TASK-DEV-014/017 follow-up).

    Multi-tenant поиск:
      - Сначала пробуем как 6-значный bind-код из Redis (`tg_bind:{code}`)
        — клик «Сгенерировать код» в Settings → user_id. Чистый UX без
        ambiguity.
      - Иначе fallback: ищем `User.username == ident` среди ВСЕХ тенантов.
        Если найдено > 1 → подсказка указать `<slug>/<username>` для
        дизамбигуации.
      - Поддержка `<slug>/<username>`: парсим slug, ищем tenant.id,
        ищем user в этом тенанте.
    """
    import redis.asyncio as redis_async  # noqa: WPS433
    from app.db.models import Tenant  # noqa: WPS433

    ident = ident.strip()
    code_is_short = ident.isalnum() and 4 <= len(ident) <= 12

    # 1. Redis bind-code (short alnum)
    if code_is_short:
        try:
            r = redis_async.from_url(settings.redis_url, decode_responses=True)
            user_id_raw = await r.get(f"tg_bind:{ident.upper()}")
            await r.aclose()
        except Exception as e:  # noqa: BLE001
            log.warning("bind code Redis lookup failed: %s", e)
            user_id_raw = None
        if user_id_raw:
            try:
                user_id = int(user_id_raw)
            except (TypeError, ValueError):
                user_id = None
            if user_id:
                async with task_session_scope() as session:
                    user = await session.get(User, user_id)
                    if user and user.is_active:
                        user.tg_chat_id = str(chat_id)
                        await session.commit()
                        # Чистим использованный код
                        try:
                            r = redis_async.from_url(settings.redis_url, decode_responses=True)
                            await r.delete(f"tg_bind:{ident.upper()}")
                            await r.aclose()
                        except Exception:  # noqa: BLE001
                            pass
                        return (
                            f"✅ Привязано: <b>{user.full_name or user.username}</b> "
                            f"({user.role}, тенант #{user.tenant_id}).\n\n"
                            f"Теперь вы получаете broadcast-уведомления."
                        )

    # 2. `<slug>/<username>` форма
    if "/" in ident:
        slug, _, uname = ident.partition("/")
        slug, uname = slug.strip(), uname.strip()
        async with task_session_scope() as session:
            tenant = (
                await session.execute(
                    select(Tenant).where(Tenant.slug == slug)
                )
            ).scalar_one_or_none()
            if not tenant:
                return f"🚫 Тенант <b>{slug}</b> не найден."
            user = (
                await session.execute(
                    select(User).where(
                        User.tenant_id == tenant.id,
                        User.username == uname,
                        User.is_active.is_(True),
                    )
                )
            ).scalar_one_or_none()
            if not user:
                return f"🚫 Пользователь <b>{uname}</b> в тенанте <b>{slug}</b> не найден."
            user.tg_chat_id = str(chat_id)
            await session.commit()
            return (
                f"✅ Привязано: <b>{user.full_name or user.username}</b> "
                f"({user.role}, {slug})."
            )

    # 3. Plain username — search across ALL tenants
    async with task_session_scope() as session:
        users = (
            await session.execute(
                select(User, Tenant.slug)
                .join(Tenant, Tenant.id == User.tenant_id)
                .where(
                    User.username == ident,
                    User.is_active.is_(True),
                )
                .limit(5)
            )
        ).all()
        if not users:
            return (
                f"🚫 Пользователь <b>{ident}</b> не найден ни в одном тенанте.\n\n"
                f"Если у вас есть код привязки из /settings — используйте его:\n"
                f"<code>/bind &lt;6-значный-код&gt;</code>"
            )
        if len(users) > 1:
            slug_list = ", ".join(slug for _, slug in users)
            return (
                f"⚠ Найдено несколько аккаунтов с username <b>{ident}</b> "
                f"(в тенантах: {slug_list}).\n\n"
                f"Используйте форму <code>/bind &lt;slug&gt;/{ident}</code>, "
                f"либо сгенерируйте уникальный код в /settings."
            )
        user, slug = users[0]
        user.tg_chat_id = str(chat_id)
        await session.commit()
        return (
            f"✅ Привязано: <b>{user.full_name or user.username}</b> "
            f"({user.role}, {slug}).\n\n"
            f"Теперь вы получаете broadcast-уведомления."
        )


async def _unbind_user(chat_id: int) -> str:
    """Отвязать chat_id от всех User.tg_chat_id (across tenants)."""
    async with task_session_scope() as session:
        users = (
            await session.execute(
                select(User).where(User.tg_chat_id == str(chat_id))
            )
        ).scalars().all()
        if not users:
            return "У этого чата нет привязанных аккаунтов."
        for u in users:
            u.tg_chat_id = None
        await session.commit()
        names = ", ".join(u.username for u in users)
        return f"✅ Отвязано: {names}"


async def _save_setting(key: str, value: str) -> None:
    tid = settings.bot_tenant_id
    async with task_session_scope() as session:
        set_tenant(session, tid)
        stmt = pg_insert(AppSetting).values(tenant_id=tid, key=key, value=value)
        stmt = stmt.on_conflict_do_update(
            index_elements=["tenant_id", "key"], set_={"value": value}
        )
        await session.execute(stmt)


async def _read_setting(key: str) -> str | None:
    tid = settings.bot_tenant_id
    async with task_session_scope() as session:
        set_tenant(session, tid)
        row = (
            await session.execute(
                select(AppSetting).where(
                    AppSetting.tenant_id == tid, AppSetting.key == key
                )
            )
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

    # /bind и /unbind — открытые для всех (любой залогиненный юзер РНП
    # может привязать свой Telegram, не только tenant-owner). Используется
    # для multi-recipient broadcast'а заявок (см. services/tg_broadcast.py).
    if cmd == "/bind":
        if not args:
            await send_message(
                chat_id,
                "Использование: <code>/bind &lt;ваш-username-в-РНП&gt;</code>\n\n"
                "username — тот же что вы используете для входа в РНП.\n"
                "Найти можно в /settings → ваш профиль.",
            )
            return
        msg = await _bind_user(chat_id, args[0].strip())
        await send_message(chat_id, msg)
        return

    if cmd == "/unbind":
        msg = await _unbind_user(chat_id)
        await send_message(chat_id, msg)
        return

    # Для KPI-команд (/now /alerts /pnl) определяем тенант ИЗ привязки юзера.
    # Multi-tenant: chat_id → user → tenant_id. Если юзер не привязан —
    # fallback на legacy `settings.bot_tenant_id` + старая owner-проверка.
    if cmd in ("/now", "/alerts", "/pnl"):
        tenant_id = await _resolve_tenant_from_chat(chat_id)
        if tenant_id is None:
            if not await _is_authorized(chat_id):
                await send_message(
                    chat_id,
                    "🚫 Чат не привязан ни к одному аккаунту РНП.\n\n"
                    "Используйте <code>/bind &lt;username&gt;</code> или "
                    "сгенерируйте код привязки в /settings → «Мой Telegram-чат».",
                )
                return
            # Legacy fallback — единственный owner-чат тенанта
            tenant_id = settings.bot_tenant_id

        try:
            if cmd == "/now":
                await send_message(chat_id, await build_now(tenant_id))
            elif cmd == "/alerts":
                await send_message(chat_id, await build_alerts(tenant_id))
            elif cmd == "/pnl":
                await send_message(chat_id, await build_pnl_short(tenant_id))
        except Exception as e:  # noqa: BLE001
            log.exception("bot: command %s failed: %s", cmd, e)
            await send_message(chat_id, f"⚠ Ошибка обработки команды: {type(e).__name__}")
        return

    # Прочие команды — fallback на /help
    await send_message(chat_id, HELP)


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
