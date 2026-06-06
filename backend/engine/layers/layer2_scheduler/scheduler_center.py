"""SchedulerCenter — unified entry point for Layer 2."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import TYPE_CHECKING

from shared.errors import NoAvailableAIError, TaskValidationError
from shared.event_bus import EventBus
from shared.types import (
    AIAvailability,
    AIStatus,
    QueryRequest,
    SubmitOptions,
    TaskHandle,
    TaskProgress,
    TaskStatus,
    TaskStatusInfo,
)

from .concurrency_controller import ConcurrencyController
from .retry_manager import RetryManager
from .timeout_manager import TimeoutManager

if TYPE_CHECKING:
    from ..layer1_ai_access.manager import AIAccessManager

logger = logging.getLogger(__name__)


class SchedulerCenter:
    """Scheduler Center — thin orchestration layer.

    Responsibilities:
    - Validate query requests
    - Check AI availability
    - Dispatch to AIAccessManager with concurrency/retry/timeout control
    - Track task lifecycle
    - Never read/store/analyze AI response content
    """

    def __init__(
        self,
        ai_manager: AIAccessManager,
        event_bus: EventBus | None = None,
        max_concurrent: int = 2,
        ai_min_interval_ms: int = 2000,
        max_retries: int = 2,
        soft_timeout_ms: int = 60000,
        hard_timeout_ms: int = 180000,
    ) -> None:
        self._ai_manager = ai_manager
        self._event_bus = event_bus or EventBus()
        self._tasks: dict[str, TaskStatusInfo] = {}
        self._cancel_events: dict[str, asyncio.Event] = {}
        self._max_stored_tasks = 1000  # LRU limit

        self._retry = RetryManager(max_retries=max_retries)
        self._timeout = TimeoutManager(soft_timeout_ms=soft_timeout_ms, hard_timeout_ms=hard_timeout_ms)
        self._concurrency = ConcurrencyController(
            max_concurrent=max_concurrent,
            ai_min_interval_ms=ai_min_interval_ms,
        )

    async def submit_query(self, request: QueryRequest) -> TaskHandle:
        """Submit a query for multi-AI processing.

        Validates → checks availability → dispatches → returns handle.
        """
        # Validate
        if not request.query.strip():
            raise TaskValidationError("Query cannot be empty")
        if not request.selected_ai_ids:
            raise TaskValidationError("At least one AI must be selected")

        # Check availability
        availability = self.get_available_ais()
        available_ids = {ai_id for ai_id, _ in availability.available}

        # Filter to available AIs
        usable_ids = [ai_id for ai_id in request.selected_ai_ids if ai_id in available_ids]
        if not usable_ids:
            raise NoAvailableAIError()

        # Create task
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        now = time.time()

        task_info = TaskStatusInfo(
            task_id=task_id,
            status=TaskStatus.CREATED,
            progress=TaskProgress(total_ais=len(usable_ids)),
            created_at=now,
            updated_at=now,
        )
        self._tasks[task_id] = task_info

        # Publish created event
        await self._event_bus.emit(
            "scheduler:task:created",
            task_id=task_id,
            selected_ai_ids=usable_ids,
            mode=request.mode.value,
            query=request.query,
        )

        # Transition to DISPATCHED
        self._tasks[task_id] = TaskStatusInfo(
            task_id=task_id,
            status=TaskStatus.DISPATCHED,
            progress=task_info.progress,
            created_at=now,
            updated_at=time.time(),
        )

        # Publish dispatched event (triggers Layer 3 collection)
        await self._event_bus.emit(
            "scheduler:task:dispatched",
            task_id=task_id,
            selected_ai_ids=usable_ids,
            query=request.query,
            mode=request.mode.value,
        )

        # Create cancel event and execute in background
        self._cancel_events[task_id] = asyncio.Event()
        asyncio.create_task(self._execute_task_safe(task_id, request.query, usable_ids))

        return TaskHandle(task_id=task_id, status=TaskStatus.DISPATCHED, created_at=now)

    async def _execute_task_safe(self, task_id: str, query: str, ai_ids: list[str]) -> None:
        """Wrapper that catches unhandled exceptions in background tasks."""
        try:
            await self._execute_task(task_id, query, ai_ids)
        except Exception:
            logger.exception("Unhandled error in task %s", task_id)
            if task_id in self._tasks and self._tasks[task_id].status not in (
                TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED
            ):
                self._tasks[task_id] = TaskStatusInfo(
                    task_id=task_id,
                    status=TaskStatus.FAILED,
                    progress=self._tasks[task_id].progress,
                    created_at=self._tasks[task_id].created_at,
                    updated_at=time.time(),
                )
        finally:
            self._cancel_events.pop(task_id, None)

    async def _execute_task(self, task_id: str, query: str, ai_ids: list[str]) -> None:
        """Execute the task with concurrency/retry/timeout control."""
        cancel = self._cancel_events.get(task_id)

        # Transition to RUNNING
        self._tasks[task_id] = TaskStatusInfo(
            task_id=task_id,
            status=TaskStatus.RUNNING,
            progress=self._tasks[task_id].progress,
            created_at=self._tasks[task_id].created_at,
            updated_at=time.time(),
        )

        self._timeout.start(task_id)

        async def _send_one(ai_id: str):
            """Send to a single AI with concurrency control."""
            if cancel and cancel.is_set():
                return ai_id, None
            await self._concurrency.acquire(ai_id)
            try:
                return ai_id, await self._send_with_retry(task_id, ai_id, query)
            finally:
                self._concurrency.release(ai_id)

        # True parallel execution via asyncio.gather
        responses = await asyncio.gather(
            *[_send_one(ai_id) for ai_id in ai_ids],
            return_exceptions=True,
        )

        results = {}
        for item in responses:
            if isinstance(item, Exception):
                logger.error("Task %s: unexpected error in parallel dispatch: %s", task_id, item)
                continue
            ai_id, response = item
            results[ai_id] = response

        self._timeout.finish(task_id)

        # Count successes/failures
        success_count = sum(1 for r in results.values() if r and r.success)
        fail_count = len(ai_ids) - success_count

        if success_count == len(ai_ids):
            final_status = TaskStatus.COMPLETED
        elif success_count > 0:
            final_status = TaskStatus.PARTIAL
        else:
            final_status = TaskStatus.FAILED

        self._tasks[task_id] = TaskStatusInfo(
            task_id=task_id,
            status=final_status,
            progress=TaskProgress(
                total_ais=len(ai_ids),
                completed_ais=success_count,
                failed_ais=fail_count,
            ),
            created_at=self._tasks[task_id].created_at,
            updated_at=time.time(),
        )

        logger.info("Task %s completed: %s (%d/%d success)", task_id, final_status.value, success_count, len(ai_ids))

    async def _send_with_retry(self, task_id: str, ai_id: str, query: str):
        """Send to AI with retry logic."""
        options = SubmitOptions(timeout_ms=self._timeout.hard_timeout_ms)

        while True:
            response = await self._ai_manager.send_to_ai(ai_id, query, options, task_id=task_id)

            if response.success:
                self._retry.reset(task_id)
                return response

            # Check if should retry
            error_code = response.error_code or "UNKNOWN"
            if self._retry.should_retry(task_id, error_code):
                attempt = self._retry.record_attempt(task_id)
                delay_ms = self._retry.get_delay_ms(task_id)
                logger.info("Task %s: retrying %s (attempt %d, delay %dms)", task_id, ai_id, attempt, delay_ms)
                await asyncio.sleep(delay_ms / 1000)
                continue

            # No more retries
            self._retry.reset(task_id)
            return response

    def cancel_task(self, task_id: str) -> None:
        """Cancel a task and signal in-flight work to stop."""
        if task_id in self._tasks:
            old = self._tasks[task_id]
            self._tasks[task_id] = TaskStatusInfo(
                task_id=task_id,
                status=TaskStatus.CANCELLED,
                progress=old.progress,
                created_at=old.created_at,
                updated_at=time.time(),
            )
        # Signal cancellation to the background task
        cancel_event = self._cancel_events.get(task_id)
        if cancel_event:
            cancel_event.set()

    def get_task_status(self, task_id: str) -> TaskStatusInfo | None:
        """Get task status."""
        return self._tasks.get(task_id)

    def get_available_ais(self) -> AIAvailability:
        """Check which AIs are available."""
        all_status = self._ai_manager.get_ready_ais()
        available = []
        unavailable = []

        for status in all_status:
            if status.status == AIStatus.READY:
                available.append((status.ai_id, status.ai_name))
            else:
                unavailable.append((status.ai_id, status.status.value))

        return AIAvailability(available=available, unavailable=unavailable)

    def cleanup_old_tasks(self, max_age_seconds: float = 3600) -> int:
        """Remove completed/failed tasks older than max_age_seconds."""
        now = time.time()
        to_remove = []
        for task_id, task in self._tasks.items():
            if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):  # noqa: SIM102
                if now - task.updated_at > max_age_seconds:
                    to_remove.append(task_id)

        for task_id in to_remove:
            del self._tasks[task_id]
            self._cancel_events.pop(task_id, None)

        # Enforce max size (remove oldest)
        while len(self._tasks) > self._max_stored_tasks:
            oldest = min(self._tasks, key=lambda k: self._tasks[k].updated_at)
            del self._tasks[oldest]
            self._cancel_events.pop(oldest, None)

        if to_remove:
            logger.info("Cleaned up %d old tasks", len(to_remove))
        return len(to_remove)
