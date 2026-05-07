"""Minimal Telegram Bot API wrapper using httpx.

We avoid heavyweight bot frameworks (aiogram/python-telegram-bot) — Telegram Bot
API is plain HTTP and we only need:
  - sendMessage  (called from bot replies + Celery digest tasks)
  - getUpdates   (called by the bot long-polling process)

The bot token is read from settings.tg_bot_token (env: TG_BOT_TOKEN).
"""
from __future__ import annotations

from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)


def _api(method: str) -> str | None:
    if not settings.tg_bot_token:
        return None
    return f"https://api.telegram.org/bot{settings.tg_bot_token}/{method}"


async def send_message(
    chat_id: int | str,
    text: str,
    *,
    parse_mode: str = "HTML",
    disable_web_page_preview: bool = True,
) -> bool:
    """Send a message. Returns True on success."""
    url = _api("sendMessage")
    if not url:
        log.warning("TG: bot token not configured, skip send")
        return False
    body = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": disable_web_page_preview,
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(url, json=body)
        if r.status_code != 200:
            log.warning("TG sendMessage %s: %s", r.status_code, r.text[:200])
            return False
        return True
    except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError) as e:
        log.warning("TG sendMessage transport error: %s", e)
        return False


async def get_updates(offset: int = 0, timeout: int = 30) -> list[dict[str, Any]]:
    """Long-poll updates. Returns list (possibly empty) or [] on error."""
    url = _api("getUpdates")
    if not url:
        return []
    params = {"offset": offset, "timeout": timeout}
    try:
        async with httpx.AsyncClient(timeout=timeout + 10) as client:
            r = await client.get(url, params=params)
        if r.status_code != 200:
            log.warning("TG getUpdates %s: %s", r.status_code, r.text[:200])
            return []
        data = r.json()
        if not data.get("ok"):
            log.warning("TG getUpdates not ok: %s", data)
            return []
        return data.get("result", [])
    except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError) as e:
        log.warning("TG getUpdates transport error: %s", e)
        return []


async def get_me() -> dict[str, Any] | None:
    url = _api("getMe")
    if not url:
        return None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url)
        if r.status_code == 200 and r.json().get("ok"):
            return r.json()["result"]
    except (httpx.ConnectError, httpx.ReadTimeout):
        pass
    return None
