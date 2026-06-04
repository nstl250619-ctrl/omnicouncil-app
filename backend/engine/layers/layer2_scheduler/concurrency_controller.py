"""ConcurrencyController — global concurrency window + per-AI interval."""

from __future__ import annotations

import asyncio
import time
import logging

logger = logging.getLogger(__name__)


class ConcurrencyController:
    """Controls concurrent task execution.

    - Global max concurrent tasks (default 2) via asyncio.Semaphore
    - Per-AI minimum interval (default 2000ms)
    """

    def __init__(
        self,
        max_concurrent: int = 2,
        ai_min_interval_ms: int = 2000,
    ) -> None:
        self._max_concurrent = max_concurrent
        self._ai_min_interval_ms = ai_min_interval_ms
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._last_dispatch: dict[str, float] = {}
        self._lock = asyncio.Lock()

    @property
    def active_count(self) -> int:
        return self._max_concurrent - self._semaphore._value

    @property
    def available_slots(self) -> int:
        return max(0, self._semaphore._value)

    async def acquire(self, ai_id: str) -> None:
        """Wait until we can dispatch to this AI (concurrency + interval)."""
        # Wait for a concurrency slot
        await self._semaphore.acquire()

        # Wait for per-AI interval
        async with self._lock:
            last = self._last_dispatch.get(ai_id, 0)
            elapsed_ms = (time.time() - last) * 1000
            if elapsed_ms < self._ai_min_interval_ms:
                wait_s = (self._ai_min_interval_ms - elapsed_ms) / 1000
                # Release semaphore during wait, re-acquire after
                self._semaphore.release()
                await asyncio.sleep(wait_s)
                await self._semaphore.acquire()

            self._last_dispatch[ai_id] = time.time()

    def release(self, ai_id: str | None = None) -> None:
        """Release a concurrency slot."""
        try:
            self._semaphore.release()
        except ValueError:
            logger.warning("Attempted to release more slots than acquired")

    def reset(self) -> None:
        """Reset all state."""
        self._last_dispatch.clear()
