"""TimeoutManager — soft and hard timeout management."""

from __future__ import annotations

import asyncio
import logging
import time

logger = logging.getLogger(__name__)


class TimeoutManager:
    """Manages timeouts for AI requests.

    - Soft timeout: check if partial output exists, ask user to continue
    - Hard timeout: force stop, mark as TIMEOUT
    """

    def __init__(
        self,
        soft_timeout_ms: int = 60000,
        hard_timeout_ms: int = 180000,
    ) -> None:
        self._soft_timeout_ms = soft_timeout_ms
        self._hard_timeout_ms = hard_timeout_ms
        self._start_times: dict[str, float] = {}

    @property
    def soft_timeout_ms(self) -> int:
        return self._soft_timeout_ms

    @property
    def hard_timeout_ms(self) -> int:
        return self._hard_timeout_ms

    def start(self, task_id: str) -> None:
        """Start tracking a task's timeout."""
        self._start_times[task_id] = time.time() * 1000

    def check(self, task_id: str) -> str:
        """Check timeout status. Returns 'ok', 'soft_timeout', or 'hard_timeout'."""
        start = self._start_times.get(task_id)
        if start is None:
            return "ok"

        elapsed = time.time() * 1000 - start
        if elapsed >= self._hard_timeout_ms:
            return "hard_timeout"
        if elapsed >= self._soft_timeout_ms:
            return "soft_timeout"
        return "ok"

    def elapsed_ms(self, task_id: str) -> int:
        """Get elapsed time in ms for a task."""
        start = self._start_times.get(task_id)
        if start is None:
            return 0
        return int(time.time() * 1000 - start)

    def finish(self, task_id: str) -> None:
        """Stop tracking a task."""
        self._start_times.pop(task_id, None)

    def reset(self) -> None:
        """Reset all tracking."""
        self._start_times.clear()
