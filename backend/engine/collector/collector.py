"""Result collector — gathers and normalizes AI responses."""

from __future__ import annotations

import logging
import time
from typing import Any

from .response import AIResponse

logger = logging.getLogger(__name__)


class ResultCollector:
    """Collects AI responses into a unified format.

    Responsibilities:
    - Normalize raw provider responses into AIResponse
    - Track collection progress
    - Assemble final results for downstream analysis
    """

    def __init__(self):
        self._results: dict[str, dict[str, AIResponse]] = {}  # task_id -> {provider_id: AIResponse}

    def collect(
        self,
        task_id: str,
        provider_id: str,
        content: str,
        response_time_ms: int = 0,
        success: bool = True,
        error: str | None = None,
    ) -> AIResponse:
        """Collect a single provider's response."""
        response = AIResponse(
            provider_id=provider_id,
            content=content,
            response_time_ms=response_time_ms,
            success=success,
            error=error,
        )

        if task_id not in self._results:
            self._results[task_id] = {}

        self._results[task_id][provider_id] = response
        logger.info("Collected response from %s for task %s (%d words)",
                    provider_id, task_id, response.word_count)
        return response

    def get_results(self, task_id: str) -> list[AIResponse]:
        """Get all collected results for a task."""
        return list(self._results.get(task_id, {}).values())

    def get_result(self, task_id: str, provider_id: str) -> AIResponse | None:
        """Get a specific provider's result."""
        return self._results.get(task_id, {}).get(provider_id)

    def clear(self, task_id: str) -> None:
        """Clear results for a task."""
        self._results.pop(task_id, None)
