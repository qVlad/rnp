"""Простой Redis-based rate limiter для публичных endpoints (signup, login).

Использует INCR + EXPIRE: счётчик `rl:<key>:<bucket>` инкрементируется на
каждом запросе; bucket — текущий час/минута. Если счётчик > лимита → 429.

Защищает от:
- Брут-форса логина (`/api/auth/login` — 20 attempts per 15 min per IP)
- Спама signup (`/api/auth/signup` — 5 attempts per hour per IP)
- DOS перебором email/JWT validation
"""
from __future__ import annotations

import time
from typing import Final

import redis.asyncio as aioredis
from fastapi import HTTPException, Request

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)


_REDIS: aioredis.Redis | None = None


def _redis() -> aioredis.Redis:
    """Lazy singleton — один пул на процесс."""
    global _REDIS
    if _REDIS is None:
        _REDIS = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _REDIS


def _client_ip(request: Request) -> str:
    """IP клиента с учётом X-Forwarded-For (если за reverse-proxy)."""
    xff = request.headers.get("x-forwarded-for", "").strip()
    if xff:
        # Берём первый IP в цепочке.
        return xff.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


async def check_rate_limit(
    request: Request,
    *,
    bucket: str,
    limit: int,
    window_seconds: int,
) -> None:
    """Проверить лимит. Кидает HTTPException(429) если превышен.

    Args:
        bucket: имя бакета (например 'signup', 'login') — отделяет лимиты
            разных endpoint'ов.
        limit: максимум запросов за окно.
        window_seconds: длительность окна.
    """
    ip = _client_ip(request)
    # Текущий "слот" окна — позволяет окну быть rolling (приблизительно).
    slot = int(time.time()) // window_seconds
    key = f"rl:{bucket}:{ip}:{slot}"
    try:
        r = _redis()
        count = await r.incr(key)
        if count == 1:
            # Только при первом инкременте — ставим TTL.
            await r.expire(key, window_seconds + 60)  # +60s margin
    except Exception as e:  # noqa: BLE001 — redis down shouldn't break service
        log.warning("rate_limit redis error (%s) — bypass", e)
        return
    if count > limit:
        log.warning("rate_limit %s exceeded: ip=%s count=%d", bucket, ip, count)
        raise HTTPException(
            429,
            f"Too many requests. Limit: {limit} per {window_seconds // 60} min.",
        )


# Pre-configured limiters as FastAPI dependencies.
async def rate_limit_signup(request: Request) -> None:
    """5 signup attempts per hour per IP — против фермы фейковых компаний."""
    await check_rate_limit(request, bucket="signup", limit=5, window_seconds=3600)


async def rate_limit_login(request: Request) -> None:
    """20 login attempts per 15 minutes per IP — против brute-force."""
    await check_rate_limit(request, bucket="login", limit=20, window_seconds=900)
