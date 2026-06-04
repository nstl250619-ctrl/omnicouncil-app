"""RetryManager — fixed-delay retry with configurable policy."""

from __future__ import annotations

import asyncio
import logging
import time

logger = logging.getLogger(__name__)


class RetryManager:
    """Manages retry logic for failed AI requests.

    Policy: fixed delay with optional backoff multiplier.
    """

    def __init__(
        self,
        max_retries: int = 2,
        retry_delay_ms: int = 3000,
        backoff_multiplier: float = 1.5,
        retry_on: set[str] | None = None,
        no_retry_on: set[str] | None = None,
    ) -> None:
        self._max_retries = max_retries
        self._retry_delay_ms = retry_delay_ms
        self._backoff_multiplier = backoff_multiplier
        self._retry_on = retry_on or {"AI_TIMEOUT", "AI_CONNECTION_ERROR", "INTERNAL_ERROR"}
        self._no_retry_on = no_retry_on or {"LOGIN_REQUIRED", "CAPTCHA_REQUIRED", "CIRCUIT_OPEN"}
        self._attempt_counts: dict[str, int] = {}

    def should_retry(self, task_id: str, error_code: str) -> bool:
        """Check if a failed task should be retried."""
        if error_code in self._no_retry_on:
            return False
        if error_code not in self._retry_on:
            return False

        attempts = self._attempt_counts.get(task_id, 0)
        return attempts < self._max_retries

    def record_attempt(self, task_id: str) -> int:
        """Record a retry attempt. Returns the current attempt number."""
        self._attempt_counts[task_id] = self._attempt_counts.get(task_id, 0) + 1
        return self._attempt_counts[task_id]

    def get_delay_ms(self, task_id: str) -> int:
        """Get the delay before the next retry attempt."""
        attempts = self._attempt_counts.get(task_id, 0)
        delay = self._retry_delay_ms * (self._backoff_multiplier ** attempts)
        return int(delay)

    def reset(self, task_id: str) -> None:
        """Reset attempt count for a task."""
        self._attempt_counts.pop(task_id, None)

    def reset_all(self) -> None:
        """Reset all attempt counts."""
        self._attempt_counts.clear()
