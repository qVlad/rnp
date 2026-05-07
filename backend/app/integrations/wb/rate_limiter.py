import asyncio
import time
from collections import deque


class TokenBucketLimiter:
    """Per-category async rate limiter.

    Two constraints enforced (in this order):
      1. **min_interval_s** — minimum gap between consecutive requests.
         WB advert spec specifies things like "3/мин, интервал 20с": both
         the per-minute cap AND a hard 20-second floor between two calls.
         Sliding-window alone is not enough — three requests in t=0,1,2
         seconds satisfy "≤3/min" but violate "interval 20s" and trigger 429.
      2. **requests_per_minute** — sliding 60-second window cap.

    Configure with `min_interval_s=0` for endpoints without a per-call gap.
    See WB_API_REFERENCE.md §3 for per-endpoint values.
    """

    def __init__(self, requests_per_minute: int, min_interval_s: float = 0.0):
        self.requests_per_minute = max(1, requests_per_minute)
        self.min_interval_s = max(0.0, min_interval_s)
        self._lock = asyncio.Lock()
        self._timestamps: deque[float] = deque()
        self._last_request: float = 0.0

    async def acquire(self) -> None:
        async with self._lock:
            # Constraint 1: minimum interval since last call
            if self.min_interval_s > 0.0:
                gap = time.monotonic() - self._last_request
                wait = self.min_interval_s - gap
                if wait > 0.0:
                    await asyncio.sleep(wait)

            # Constraint 2: sliding window cap
            now = time.monotonic()
            window_start = now - 60.0
            while self._timestamps and self._timestamps[0] < window_start:
                self._timestamps.popleft()
            if len(self._timestamps) >= self.requests_per_minute:
                wait_for = 60.0 - (now - self._timestamps[0]) + 0.05
                await asyncio.sleep(max(0.0, wait_for))
                now = time.monotonic()
                window_start = now - 60.0
                while self._timestamps and self._timestamps[0] < window_start:
                    self._timestamps.popleft()

            ts = time.monotonic()
            self._timestamps.append(ts)
            self._last_request = ts
