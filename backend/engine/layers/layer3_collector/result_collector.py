"""ResultCollector — unified entry point for Layer 3."""

from __future__ import annotations

import logging
import time

from shared.event_bus import EventBus
from shared.types import (
    AiResult,
    NormalizedResponse,
    ResultStatus,
    RoundContext,
    RoundContextSummary,
    TaskMode,
)

from ..layer1_ai_access.response_normalizer import ResponseNormalizer

logger = logging.getLogger(__name__)


class ResultCollector:
    """Result Collection Center — data bus for the system.

    Listens for ai:task:completed/failed events, normalizes responses,
    assembles RoundContext when all results are collected.
    """

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self._event_bus = event_bus or EventBus()
        self._normalizer = ResponseNormalizer()
        self._pending: dict[str, dict[str, AiResult]] = {}  # task_id -> {ai_id: AiResult}
        self._expected: dict[str, int] = {}  # task_id -> expected count
        self._contexts: dict[str, RoundContext] = {}  # task_id -> RoundContext
        self._queries: dict[str, str] = {}  # task_id -> original query
        self._modes: dict[str, TaskMode] = {}  # task_id -> execution mode
        self._completed_at: dict[str, float] = {}  # task_id -> completion timestamp
        self._release_ttl_seconds: int = 60  # TTL before context release

        # Register event handlers
        self._event_bus.on("ai:task:completed", self._on_task_completed)
        self._event_bus.on("ai:task:failed", self._on_task_failed)
        self._event_bus.on("scheduler:task:dispatched", self._on_task_dispatched)

    def _on_task_dispatched(self, task_id: str, selected_ai_ids: list[str], query: str = "", mode: str = "parallel", **kwargs) -> None:
        """Handle task dispatched event — prepare collection."""
        self._pending[task_id] = {}
        self._expected[task_id] = len(selected_ai_ids)
        self._queries[task_id] = query
        self._modes[task_id] = TaskMode(mode) if mode in ("parallel", "sequential") else TaskMode.PARALLEL
        logger.info("Collector ready for task %s, expecting %d results", task_id, len(selected_ai_ids))

    async def _on_task_completed(self, task_id: str, ai_id: str, response, **kwargs) -> None:
        """Handle a successful AI response."""
        normalized = self._normalizer.normalize(response.content)

        result = AiResult(
            ai_id=ai_id,
            task_id=task_id,
            round_number=1,
            status=ResultStatus.SUCCESS,
            raw_text=response.content,
            normalized=normalized,
            start_time=response.timestamp - response.duration,
            end_time=response.timestamp,
            duration=response.duration,
            prompt_used="",
            model=response.model,
        )

        if task_id not in self._pending:
            self._pending[task_id] = {}
        self._pending[task_id][ai_id] = result

        await self._check_completion(task_id)

    async def _on_task_failed(self, task_id: str, ai_id: str, error: str, **kwargs) -> None:
        """Handle a failed AI response."""
        result = AiResult(
            ai_id=ai_id,
            task_id=task_id,
            round_number=1,
            status=ResultStatus.ERROR,
            raw_text="",
            normalized=NormalizedResponse(main_text=""),
            error=error,
        )

        if task_id not in self._pending:
            self._pending[task_id] = {}
        self._pending[task_id][ai_id] = result

        await self._check_completion(task_id)

    async def _check_completion(self, task_id: str) -> None:
        """Check if all expected results have been collected."""
        pending = self._pending.get(task_id, {})
        expected = self._expected.get(task_id, 0)

        if len(pending) >= expected:
            await self._assemble_context(task_id)

    async def _assemble_context(self, task_id: str) -> None:
        """Assemble RoundContext and emit event."""
        pending = self._pending.get(task_id, {})
        results = list(pending.values())

        success_count = sum(1 for r in results if r.status == ResultStatus.SUCCESS)
        failure_count = sum(1 for r in results if r.status == ResultStatus.ERROR)
        timeout_count = sum(1 for r in results if r.status == ResultStatus.TIMEOUT)

        summary = RoundContextSummary(
            total_ais=len(results),
            success_count=success_count,
            failure_count=failure_count,
            timeout_count=timeout_count,
            completed_at=time.time(),
        )

        ctx = RoundContext(
            task_id=task_id,
            round_number=1,
            query=self._queries.get(task_id, ""),
            execution_mode=self._modes.get(task_id, TaskMode.PARALLEL),
            results=results,
            summary=summary,
            created_at=time.time(),
        )

        self._contexts[task_id] = ctx
        self._completed_at[task_id] = time.time()

        # Clean up temporary state
        self._pending.pop(task_id, None)
        self._expected.pop(task_id, None)

        await self._event_bus.emit("collector:context:ready", context=ctx)
        logger.info("RoundContext assembled for task %s: %d results", task_id, len(results))

        # Release completed contexts past TTL
        self._cleanup_completed_contexts()

    def set_query(self, task_id: str, query: str, mode: TaskMode = TaskMode.PARALLEL) -> None:
        """Store the original query for a task (called by scheduler)."""
        self._queries[task_id] = query
        self._modes[task_id] = mode

    def get_round_context(self, task_id: str, round_number: int = 1) -> RoundContext | None:
        """Get RoundContext for a task."""
        return self._contexts.get(task_id)

    def get_latest_round_context(self, task_id: str) -> RoundContext | None:
        """Get the latest RoundContext for a task."""
        return self._contexts.get(task_id)

    def get_partial_results(self, task_id: str) -> list[AiResult]:
        """Get partial results for a task (before all AIs complete)."""
        pending = self._pending.get(task_id, {})
        return list(pending.values())

    def _cleanup_completed_contexts(self) -> None:
        """Release contexts only after TTL has passed since completion."""
        now = time.time()
        to_delete = [
            task_id
            for task_id, completed_time in self._completed_at.items()
            if now - completed_time > self._release_ttl_seconds
        ]
        for task_id in to_delete:
            self._contexts.pop(task_id, None)
            self._completed_at.pop(task_id, None)
            self._queries.pop(task_id, None)
            self._modes.pop(task_id, None)
        if to_delete:
            logger.info("Released %d completed contexts after TTL", len(to_delete))

    def on_context_ready(self, callback) -> None:
        """Register a callback for when RoundContext is ready."""
        self._event_bus.on("collector:context:ready", callback)
