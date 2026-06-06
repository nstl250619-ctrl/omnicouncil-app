"""Unit tests for engine/layers/layer2_scheduler/scheduler_center.py."""

from __future__ import annotations

import asyncio
import time

import pytest

from engine.layers.layer2_scheduler.scheduler_center import SchedulerCenter
from shared.event_bus import EventBus
from shared.errors import NoAvailableAIError, TaskValidationError
from shared.types import (
    AIResponse,
    AIStatus,
    AIAvailability,
    ProviderStatus,
    QueryRequest,
    TaskMode,
    TaskStatus,
    TaskStatusInfo,
)


class FakeAIManager:
    def __init__(self, ais=None):
        self._ais = ais or [
            ProviderStatus(ai_id="deepseek", ai_name="DeepSeek", status=AIStatus.READY),
            ProviderStatus(ai_id="qianwen", ai_name="Qianwen", status=AIStatus.READY),
        ]

    def get_ready_ais(self):
        return self._ais

    async def send_to_ai(self, ai_id, prompt, options=None, task_id=""):
        return AIResponse(
            success=True, ai_id=ai_id, task_id=task_id,
            content=f"response from {ai_id}", model=ai_id,
            timestamp=time.time(), duration=1.0, word_count=3,
        )


class TestSchedulerCenter:
    def setup_method(self):
        EventBus.reset()

    def teardown_method(self):
        EventBus.reset()

    @pytest.mark.asyncio
    async def test_submit_query(self):
        bus = EventBus()
        manager = FakeAIManager()
        scheduler = SchedulerCenter(ai_manager=manager, event_bus=bus)

        request = QueryRequest(
            query="hello",
            selected_ai_ids=["deepseek", "qianwen"],
            mode=TaskMode.PARALLEL,
        )
        handle = await scheduler.submit_query(request)

        assert handle.task_id.startswith("task_")
        assert handle.status == TaskStatus.DISPATCHED

        # Wait for background task
        await asyncio.sleep(0.5)

        status = scheduler.get_task_status(handle.task_id)
        assert status is not None
        assert status.status in (TaskStatus.COMPLETED, TaskStatus.RUNNING)

    @pytest.mark.asyncio
    async def test_submit_empty_query_raises(self):
        bus = EventBus()
        manager = FakeAIManager()
        scheduler = SchedulerCenter(ai_manager=manager, event_bus=bus)

        request = QueryRequest(query="", selected_ai_ids=["deepseek"])
        with pytest.raises(TaskValidationError):
            await scheduler.submit_query(request)

    @pytest.mark.asyncio
    async def test_submit_no_ai_raises(self):
        bus = EventBus()
        manager = FakeAIManager()
        scheduler = SchedulerCenter(ai_manager=manager, event_bus=bus)

        request = QueryRequest(query="hello", selected_ai_ids=[])
        with pytest.raises(TaskValidationError):
            await scheduler.submit_query(request)

    @pytest.mark.asyncio
    async def test_submit_unavailable_ai_raises(self):
        bus = EventBus()
        manager = FakeAIManager(ais=[
            ProviderStatus(ai_id="deepseek", ai_name="DeepSeek", status=AIStatus.ERROR),
        ])
        scheduler = SchedulerCenter(ai_manager=manager, event_bus=bus)

        request = QueryRequest(query="hello", selected_ai_ids=["deepseek"])
        with pytest.raises(NoAvailableAIError):
            await scheduler.submit_query(request)

    @pytest.mark.asyncio
    async def test_cancel_task(self):
        bus = EventBus()
        manager = FakeAIManager()
        scheduler = SchedulerCenter(ai_manager=manager, event_bus=bus)

        request = QueryRequest(query="hello", selected_ai_ids=["deepseek"])
        handle = await scheduler.submit_query(request)
        scheduler.cancel_task(handle.task_id)

        status = scheduler.get_task_status(handle.task_id)
        assert status.status == TaskStatus.CANCELLED

    def test_get_available_ais(self):
        bus = EventBus()
        manager = FakeAIManager()
        scheduler = SchedulerCenter(ai_manager=manager, event_bus=bus)

        availability = scheduler.get_available_ais()
        assert len(availability.available) == 2
        assert len(availability.unavailable) == 0

    def test_get_available_ais_with_unavailable(self):
        bus = EventBus()
        manager = FakeAIManager(ais=[
            ProviderStatus(ai_id="deepseek", ai_name="DeepSeek", status=AIStatus.READY),
            ProviderStatus(ai_id="qianwen", ai_name="Qianwen", status=AIStatus.LOGIN_REQUIRED),
        ])
        scheduler = SchedulerCenter(ai_manager=manager, event_bus=bus)

        availability = scheduler.get_available_ais()
        assert len(availability.available) == 1
        assert len(availability.unavailable) == 1

    def test_cleanup_old_tasks(self):
        bus = EventBus()
        manager = FakeAIManager()
        scheduler = SchedulerCenter(ai_manager=manager, event_bus=bus)

        # Add old completed tasks
        for i in range(5):
            scheduler._tasks[f"old_{i}"] = TaskStatusInfo(
                task_id=f"old_{i}",
                status=TaskStatus.COMPLETED,
                updated_at=time.time() - 7200,
            )

        cleaned = scheduler.cleanup_old_tasks(max_age_seconds=3600)
        assert cleaned == 5
