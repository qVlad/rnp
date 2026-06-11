"""Redis-backed global cooldown for WB API categories.

When WB returns 429 we set a TTL key like `wb:cooldown:statistics` and refuse
to send any request to that category until the key expires. This is shared
across all worker processes (and the FastAPI process), so per-process
rate-limiters can no longer over-spend.
"""
from __future__ import annotations

import asyncio

import redis.asyncio as redis_async

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

_KEY = "wb:cooldown:{category}"
_SLOT_KEY = "wb:slot:{category}:{token_key}"
_DEFAULT_COOLDOWN_SECONDS = 600  # 10 minutes — typical WB penalty window


def _client() -> redis_async.Redis:
    # Fresh client per call. Celery tasks run each in their own asyncio loop;
    # a cached pool would bind to the first loop and break in subsequent ones.
    return redis_async.from_url(settings.redis_url, decode_responses=True)


async def get_remaining(category: str) -> int:
    """Return remaining cooldown in seconds (0 if not under cooldown).

    On Redis failure: log and return a synthetic non-zero cooldown so the
    caller skips the request — better to skip a sync tick than to flood WB
    blindly when our shared throttle is unreachable.
    """
    r = _client()
    try:
        ttl = await r.ttl(_KEY.format(category=category))
    except Exception as e:
        log.error("redis unreachable in get_remaining(%s): %s — assuming cooldown active", category, e)
        return _DEFAULT_COOLDOWN_SECONDS
    finally:
        try:
            await r.aclose()
        except Exception:
            pass
    return max(0, int(ttl))


async def set_cooldown(category: str, seconds: int = _DEFAULT_COOLDOWN_SECONDS) -> None:
    r = _client()
    try:
        key = _KEY.format(category=category)
        await r.set(key, "1", ex=seconds)
    except Exception as e:
        log.error("redis unreachable in set_cooldown(%s, %ds): %s", category, seconds, e)
        return
    finally:
        try:
            await r.aclose()
        except Exception:
            pass
    log.warning("WB %s: global cooldown for %ds", category, seconds)


async def reserve_interval_slot(
    category: str,
    token_key: str,
    min_interval_s: float,
    max_wait_s: float = 90.0,
) -> None:
    """Cross-process минимальный интервал между вызовами категории (TASK-DEV-076).

    In-process `TokenBucketLimiter` пересоздаётся в каждом Celery-таске (новый
    `WbApiClient`), поэтому его `min_interval_s` НЕ держится между тасками/
    процессами — fanout + ручной `/sync/trigger` + abtest на одном seller-токене
    бёрстят advert-API → `429 per seller`. Этот Redis-гейт держит интервал
    глобально: `SET key NX PX <interval>` — если слот занят, ждём его TTL и
    повторяем. Ключ — (category, token), чтобы разные кабинеты не блокировали
    друг друга.

    Fail-open: при недоступности Redis или превышении `max_wait_s` — просто
    продолжаем (in-process лимитер всё ещё защищает в рамках процесса); лучше
    отправить запрос, чем зависнуть.
    """
    r = _client()
    key = _SLOT_KEY.format(category=category, token_key=token_key)
    px = max(1, int(min_interval_s * 1000))
    waited = 0.0
    try:
        while True:
            ok = await r.set(key, "1", nx=True, px=px)
            if ok:
                return
            ttl_ms = await r.pttl(key)
            sleep_s = max(0.05, (ttl_ms if ttl_ms and ttl_ms > 0 else px) / 1000.0)
            if waited + sleep_s > max_wait_s:
                log.warning(
                    "WB %s slot wait > %.0fs (token %s) — proceeding fail-open",
                    category, max_wait_s, token_key,
                )
                return
            await asyncio.sleep(sleep_s)
            waited += sleep_s
    except Exception as e:
        log.error("redis unreachable in reserve_interval_slot(%s): %s — fail-open", category, e)
        return
    finally:
        try:
            await r.aclose()
        except Exception:
            pass


async def clear(category: str) -> None:
    r = _client()
    try:
        await r.delete(_KEY.format(category=category))
    except Exception as e:
        log.error("redis unreachable in clear(%s): %s", category, e)
    finally:
        try:
            await r.aclose()
        except Exception:
            pass
