"""Scheduler — dispatches tasks to providers."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable

from .task import CouncilTask, TaskStatus

logger = logging.getLogger(__name__)


class Scheduler:
    """Dispatches CouncilTasks to AI providers.

    Supports:
    - Parallel execution (asyncio.gather)
    - Per-task timeout
    - Progress callbacks
    - Cancellation
    """

    def __init__(self, max_concurrent: int = 5):
        self._max_concurrent = max_concurrent
        self._tasks: dict[str, CouncilTask] = {}
        self._cancel_events: dict[str, asyncio.Event] = {}
        self._semaphore = asyncio.Semaphore(max_concurrent)

    def get_task(self, task_id: str) -> CouncilTask | None:
        return self._tasks.get(task_id)

    def get_all_tasks(self) -> list[CouncilTask]:
        return list(self._tasks.values())

    async def submit(
        self,
        query: str,
        provider_ids: list[str],
        send_fn: Callable[[str, str], Any],
        on_progress: Callable[[str, int, int], Any] | None = None,
        timeout_ms: int = 120000,
    ) -> CouncilTask:
        """Submit a query to multiple providers.

        Args:
            query: The user's question
            provider_ids: List of provider IDs to query
            send_fn: async function(provider_id, query) -> response
            on_progress: optional callback(task_id, completed, total)
            timeout_ms: timeout per provider
        """
        task = CouncilTask(
            query=query,
            provider_ids=provider_ids,
            status=TaskStatus.RUNNING,
            timeout_ms=timeout_ms,
        )
        self._tasks[task.task_id] = task
        self._cancel_events[task.task_id] = asyncio.Event()

        logger.info("Task %s: dispatching to %s", task.task_id, provider_ids)

        # Execute in background
        asyncio.create_task(
            self._execute(task, send_fn, on_progress)
        )

        return task

    async def _execute(
        self,
        task: CouncilTask,
        send_fn: Callable,
        on_progress: Callable | None,
    ) -> None:
        """Execute task across all providers in parallel."""
        cancel = self._cancel_events.get(task.task_id)

        async def _send_one(provider_id: str):
            if cancel and cancel.is_set():
                task.mark_failed(provider_id, "Cancelled")
                return

            await self._semaphore.acquire()
            try:
                response = await asyncio.wait_for(
                    send_fn(provider_id, task.query),
                    timeout=task.timeout_ms / 1000,
                )
                task.mark_completed(provider_id, response)
            except asyncio.TimeoutError:
                task.mark_failed(provider_id, "Timeout")
            except Exception as e:
                task.mark_failed(provider_id, str(e))
            finally:
                self._semaphore.release()

            if on_progress:
                on_progress(task.task_id, task.completed_count, task.total_count)

        # Parallel execution
        await asyncio.gather(
            *[_send_one(pid) for pid in task.provider_ids],
            return_exceptions=True,
        )

        logger.info(
            "Task %s: completed (%d/%d success)",
            task.task_id, task.completed_count, task.total_count,
        )

    def cancel_task(self, task_id: str) -> None:
        """Cancel a running task."""
        task = self._tasks.get(task_id)
        if task:
            task.cancel()
        cancel = self._cancel_events.get(task_id)
        if cancel:
            cancel.set()
