from __future__ import annotations

import asyncio
from typing import Any, Literal

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.integrations.wb import cooldown
from app.integrations.wb.rate_limiter import TokenBucketLimiter

log = get_logger(__name__)

Category = Literal["statistics", "advert", "common", "analytics", "finance"]


class WbApiError(Exception):
    """Picklable WB API error (Celery serializes exceptions on the result backend).

    Carries optional `headers` (a slim subset — only x-ratelimit* + retry-after)
    so callers like the token validator can show the user how long to wait
    without re-parsing the WB body.
    """

    def __init__(
        self,
        status: int,
        message: str,
        body: str | None = None,
        headers: dict[str, str] | None = None,
    ):
        self.status = status
        self.body = body
        self.message = message
        self.headers = headers or {}
        super().__init__(self._format())

    def _format(self) -> str:
        body = f" — {self.body[:300]}" if self.body else ""
        return f"WB API error {self.status}: {self.message}{body}"

    def __reduce__(self):
        return (self.__class__, (self.status, self.message, self.body, self.headers))


class WbCooldownActive(WbApiError):
    """Raised when a category is in a global cooldown window — no request is sent."""

    def __init__(self, category: str, remaining: int):
        super().__init__(
            429,
            f"category {category!r} is in cooldown for {remaining}s, request skipped",
            None,
        )
        self.category = category
        self.remaining = remaining

    def __reduce__(self):
        return (self.__class__, (self.category, self.remaining))


class WbApiClient:
    """Async httpx client for Wildberries Seller API.

    Per-category client-side rate limit + Redis-backed global cooldown:
      - the in-memory limiter prevents bursts within a single process
      - the Redis cooldown stops *all* processes after the first 429 for
        a window long enough that the WB auth-stat penalty expires
    """

    def __init__(
        self,
        token: str | None = None,
        timeout: float | None = None,
    ):
        # Multi-tenant: токен **должен** приходить явно (из БД tenant'а).
        # `.env` WB_TOKEN остаётся **только** как fallback для default-tenant
        # (legacy установка). Все sync-задачи теперь fanout per-tenant и
        # передают token явно.
        self.token = token or settings.wb_token
        if not self.token:
            raise RuntimeError(
                "WB token is not configured. Pass `token=` explicitly, "
                "or set WB_TOKEN in .env for default-tenant fallback."
            )
        self.timeout = timeout or settings.wb_request_timeout

        # Per WB_API_REFERENCE.md §3:
        #   statistics  → 1/мин (real-world: penalty after burst, 30+ min gap safest)
        #   advert      → 3/мин **с минимальным интервалом 20 сек** (fullstats spec)
        #   common      → ping is 3/30s per host; 60/min is loose ceiling
        # min_interval_s on advert is critical — sliding window alone lets
        # 3 requests fire at t=0,1,2s which WB rejects with 429.
        self._limiters: dict[Category, TokenBucketLimiter] = {
            "statistics": TokenBucketLimiter(settings.wb_stats_rate_per_min),
            "advert": TokenBucketLimiter(
                settings.wb_advert_rate_per_min, min_interval_s=20.0
            ),
            "common": TokenBucketLimiter(60),
            # seller-analytics-api: stocks-report и paid_storage — 3/мин с 20с между.
            "analytics": TokenBucketLimiter(3, min_interval_s=20.0),
            # finance-api: новый endpoint /api/finance/v1/sales-reports/detailed —
            # 1/мин, burst 1. min_interval_s=60 чтобы не отстреливать два запроса
            # подряд в одну минуту.
            "finance": TokenBucketLimiter(1, min_interval_s=60.0),
        }
        self._bases: dict[Category, str] = {
            "statistics": settings.wb_statistics_base,
            "advert": settings.wb_advert_base,
            "common": settings.wb_common_base,
            "analytics": settings.wb_analytics_base,
            "finance": settings.wb_finance_base,
        }
        self._client: httpx.AsyncClient | None = None

    # WB prefers a recognizable UA string; without it some edge nodes
    # apply stricter rate-limiting to undeclared bots.
    _USER_AGENT = "RNP-Seller-Service/1.0 (httpx; python)"

    async def __aenter__(self) -> WbApiClient:
        self._client = httpx.AsyncClient(
            timeout=self.timeout,
            headers={
                "Authorization": self.token,
                "Accept": "application/json",
                "User-Agent": self._USER_AGENT,
            },
        )
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                headers={
                    "Authorization": self.token,
                    "Accept": "application/json",
                    "User-Agent": self._USER_AGENT,
                },
            )
        return self._client

    async def request(
        self,
        method: str,
        path: str,
        category: Category,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        max_retries: int = 4,
    ) -> Any:
        """Send an authenticated request to WB.

        `max_retries` controls retries on **transport errors and 5xx only**.
        429 is NEVER retried inside the same call (penalty would extend);
        cooldown is set and WbApiError(429) is raised so the caller decides.

        Default `max_retries=4` gives 4 attempts spaced 1/2/4/8s = ~15s total
        which is enough to ride out short WB 5xx outages (we observed
        `WB 503 "no healthy upstream"` flapping every few seconds during
        WB-side incidents).
        """
        # Skip outright if WB has put us under cooldown for this category.
        remaining = await cooldown.get_remaining(category)
        if remaining > 0:
            raise WbCooldownActive(category, remaining)

        client = await self._ensure_client()
        url = f"{self._bases[category]}{path}"
        backoff = 1.0
        last_status: int | None = None
        last_body: str | None = None
        last_exc: Exception | None = None

        for attempt in range(1, max_retries + 1):
            await self._limiters[category].acquire()
            try:
                resp = await client.request(method, url, params=params, json=json)
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError) as e:
                last_exc = e
                log.warning("WB transport error (%s) on %s, attempt %d", e, path, attempt)
                if attempt < max_retries:
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 30.0)
                continue

            if resp.status_code == 429:
                last_status = 429
                last_body = (resp.text or "")[:500]
                # WB exposes the real wait time via two styles of headers:
                #   x-ratelimit-reset: <seconds_relative>  e.g. 8213
                #   x-ratelimit-retry: <seconds_relative>  (same semantics, different name)
                #   Retry-After: <seconds_relative> or <HTTP-date>
                # All values observed in production are RELATIVE (seconds from now),
                # not Unix timestamps — confirmed by values like 8213 (~2.3 hours).
                import time as _time
                now_ts = int(_time.time())
                hints: list[int] = []

                for h in ("x-ratelimit-retry", "x-ratelimit-reset"):
                    v = resp.headers.get(h)
                    if v:
                        try:
                            val = int(float(v))
                            # Sanity check: if value > current unix timestamp it's
                            # an absolute TS; convert to relative seconds.
                            if val > now_ts:
                                val = val - now_ts
                            if 1 <= val <= 24 * 3600:
                                hints.append(val)
                        except ValueError:
                            pass

                retry_after = resp.headers.get("Retry-After")
                if retry_after:
                    try:
                        val = int(float(retry_after))
                        if val > now_ts:
                            val = val - now_ts
                        if 1 <= val <= 24 * 3600:
                            hints.append(val)
                    except ValueError:
                        # Might be an HTTP-date string — skip for now
                        pass

                # Use the max hint (WB sets the longest meaningful penalty).
                # Floor at 600s (10 min) since WB penalty window is at least that.
                # Cap at 6 hours.
                cool_for = min(max([*hints, 600]), 6 * 3600)
                log.warning(
                    "WB 429 on %s body=%r limit=%s reset=%s retry-after=%s "
                    "→ %s cooldown for %ds",
                    path,
                    last_body,
                    resp.headers.get("x-ratelimit-limit"),
                    resp.headers.get("x-ratelimit-reset"),
                    resp.headers.get("Retry-After"),
                    category,
                    cool_for,
                )
                await cooldown.set_cooldown(category, cool_for)
                rl_headers = {
                    k: v for k, v in resp.headers.items()
                    if k.lower().startswith(("x-ratelimit", "retry-after"))
                }
                raise WbApiError(
                    429, "rate limited (WB auth-stat)", last_body, rl_headers
                )

            if 500 <= resp.status_code < 600:
                last_status = resp.status_code
                last_body = (resp.text or "")[:500]
                log.warning(
                    "WB %s on %s body=%r (attempt %d)",
                    resp.status_code, path, last_body, attempt,
                )
                if attempt < max_retries:
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 30.0)
                continue

            if resp.status_code >= 400:
                raise WbApiError(
                    resp.status_code,
                    resp.reason_phrase or "client error",
                    (resp.text or "")[:500],
                )

            if not resp.content:
                return None
            ctype = resp.headers.get("content-type", "")
            if "json" in ctype:
                return resp.json()
            return resp.text

        msg = (
            f"Exhausted {max_retries} retries"
            + (f" (last status {last_status})" if last_status else "")
            + (f" (last transport error: {last_exc})" if last_exc else "")
        )
        raise WbApiError(last_status or 500, msg, last_body)

    async def get(self, path: str, category: Category, **kwargs) -> Any:
        return await self.request("GET", path, category, **kwargs)

    async def post(self, path: str, category: Category, **kwargs) -> Any:
        return await self.request("POST", path, category, **kwargs)
