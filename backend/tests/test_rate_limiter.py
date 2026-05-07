import asyncio
import time

import pytest

from app.integrations.wb.rate_limiter import TokenBucketLimiter


@pytest.mark.asyncio
async def test_limiter_allows_burst_under_limit():
    lim = TokenBucketLimiter(requests_per_minute=10)
    start = time.monotonic()
    for _ in range(5):
        await lim.acquire()
    assert time.monotonic() - start < 0.5


@pytest.mark.asyncio
async def test_limiter_blocks_over_limit(monkeypatch):
    lim = TokenBucketLimiter(requests_per_minute=2)

    sleep_calls: list[float] = []
    real_sleep = asyncio.sleep

    async def fake_sleep(seconds: float):
        sleep_calls.append(seconds)
        await real_sleep(0)

    monkeypatch.setattr("app.integrations.wb.rate_limiter.asyncio.sleep", fake_sleep)
    await lim.acquire()
    await lim.acquire()
    await lim.acquire()
    assert sleep_calls, "third request should have to wait"
