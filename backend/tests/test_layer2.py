"""Unit tests for Layer 2: Scheduler components."""

from __future__ import annotations

import asyncio
import time

import pytest

from engine.layers.layer2_scheduler.concurrency_controller import ConcurrencyController
from engine.layers.layer2_scheduler.retry_manager import RetryManager
from engine.layers.layer2_scheduler.timeout_manager import TimeoutManager


class TestConcurrencyController:
    def test_initial_state(self):
        cc = ConcurrencyController(max_concurrent=2)
        assert cc.active_count == 0
        assert cc.available_slots == 2

    @pytest.mark.asyncio
    async def test_acquire_release(self):
        cc = ConcurrencyController(max_concurrent=2, ai_min_interval_ms=0)
        await cc.acquire("ai1")
        assert cc.active_count == 1
        cc.release()
        assert cc.active_count == 0

    @pytest.mark.asyncio
    async def test_respects_max_concurrent(self):
        cc = ConcurrencyController(max_concurrent=1, ai_min_interval_ms=0)
        await cc.acquire("ai1")
        assert cc.available_slots == 0
        cc.release()

    def test_reset(self):
        cc = ConcurrencyController()
        cc.reset()  # Should not raise


class TestRetryManager:
    def test_should_retry_on_retryable_error(self):
        rm = RetryManager(max_retries=2)
        assert rm.should_retry("task1", "AI_TIMEOUT") is True

    def test_should_not_retry_on_non_retryable_error(self):
        rm = RetryManager(max_retries=2)
        assert rm.should_retry("task1", "LOGIN_REQUIRED") is False

    def test_exhausts_retries(self):
        rm = RetryManager(max_retries=2)
        rm.record_attempt("task1")
        rm.record_attempt("task1")
        assert rm.should_retry("task1", "AI_TIMEOUT") is False

    def test_record_attempt_returns_count(self):
        rm = RetryManager()
        assert rm.record_attempt("task1") == 1
        assert rm.record_attempt("task1") == 2

    def test_get_delay_ms_backoff(self):
        rm = RetryManager(retry_delay_ms=1000, backoff_multiplier=2.0)
        rm.record_attempt("task1")
        assert rm.get_delay_ms("task1") == 2000

    def test_reset(self):
        rm = RetryManager(max_retries=1)
        rm.record_attempt("task1")
        rm.reset("task1")
        assert rm.should_retry("task1", "AI_TIMEOUT") is True

    def test_reset_all(self):
        rm = RetryManager(max_retries=1)
        rm.record_attempt("task1")
        rm.record_attempt("task2")
        rm.reset_all()
        assert rm.should_retry("task1", "AI_TIMEOUT") is True
        assert rm.should_retry("task2", "AI_TIMEOUT") is True


class TestTimeoutManager:
    def test_initial_state(self):
        tm = TimeoutManager(soft_timeout_ms=1000, hard_timeout_ms=2000)
        assert tm.check("task1") == "ok"

    def test_start_and_check(self):
        tm = TimeoutManager(soft_timeout_ms=100, hard_timeout_ms=200)
        tm.start("task1")
        assert tm.check("task1") == "ok"

    def test_soft_timeout(self):
        tm = TimeoutManager(soft_timeout_ms=10, hard_timeout_ms=100)
        tm.start("task1")
        time.sleep(0.02)
        assert tm.check("task1") == "soft_timeout"

    def test_hard_timeout(self):
        tm = TimeoutManager(soft_timeout_ms=10, hard_timeout_ms=20)
        tm.start("task1")
        time.sleep(0.03)
        assert tm.check("task1") == "hard_timeout"

    def test_finish(self):
        tm = TimeoutManager()
        tm.start("task1")
        tm.finish("task1")
        assert tm.check("task1") == "ok"

    def test_elapsed_ms(self):
        tm = TimeoutManager()
        tm.start("task1")
        time.sleep(0.01)
        elapsed = tm.elapsed_ms("task1")
        assert elapsed >= 10

    def test_properties(self):
        tm = TimeoutManager(soft_timeout_ms=5000, hard_timeout_ms=10000)
        assert tm.soft_timeout_ms == 5000
        assert tm.hard_timeout_ms == 10000
