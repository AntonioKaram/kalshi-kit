from __future__ import annotations

import asyncio
import time


class TokenBucketThrottler:
    def __init__(self, rate_per_second: float, capacity: int | None = None) -> None:
        self.rate_per_second = rate_per_second
        self.capacity = capacity or max(1, int(rate_per_second))
        self.tokens = float(self.capacity)
        self.updated_at = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                elapsed = now - self.updated_at
                self.updated_at = now
                self.tokens = min(self.capacity, self.tokens + elapsed * self.rate_per_second)
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return
                await asyncio.sleep(max((1.0 - self.tokens) / self.rate_per_second, 0.01))

    @property
    def remaining_fraction(self) -> float:
        return self.tokens / self.capacity
