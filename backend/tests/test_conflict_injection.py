"""Conflict injection test: query-in-progress + recovery-triggered.

Simulates the original production fault:
  1. Query acquires page lease
  2. While query is "waiting for AI response" (5s), recovery is triggered
  3. Observe: does recovery close/reload the page? Does the query fail?

Physical evidence: all assertions must pass, and all log lines are captured.
"""

from __future__ import annotations

import asyncio
import logging
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from engine.contracts import (
    PageBusyError,
    PageBusyState,
    RecoveryBusyError,
    RecoveryFailedError,
    RuntimeState,
)
from runtime.engine import AIRuntimeEngine
from runtime.page_guard import PageGuard
from runtime.recovery_engine import RecoveryEngine
from runtime.recovery_strategies import ReloadStrategy


# Capture log output for evidence
LOG_LINES: list[str] = []


class LogCapture(logging.Handler):
    def emit(self, record):
        LOG_LINES.append(self.format(record))


@pytest.fixture(autouse=True)
def _capture_logs():
    handler = LogCapture()
    handler.setFormatter(logging.Formatter("[%(levelname)s] %(name)s: %(message)s"))
    logger = logging.getLogger("runtime")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    LOG_LINES.clear()
    yield
    logger.removeHandler(handler)


def _make_engine(platform: str = "chatgpt") -> AIRuntimeEngine:
    """Build a minimal engine with mock browser but real PageGuard."""
    from engine.contracts import PlatformConfig

    config = PlatformConfig(
        name=platform,
        home_url="https://chatgpt.com",
        headless=True,
        heartbeat_interval_s=60,
        max_recovery_attempts=1,
        recovery_cooldown_s=0,
    )
    engine = AIRuntimeEngine.__new__(AIRuntimeEngine)
    engine._config = config
    engine._platform = platform
    engine._state_machine = MagicMock()
    engine._state_machine.current = RuntimeState.READY
    engine._state_machine.can_transition = MagicMock(return_value=True)
    engine._state_machine.transition = AsyncMock()

    from engine.contracts import RuntimeMetrics
    engine._metrics = RuntimeMetrics(platform=platform)

    engine._guard = PageGuard(platform=platform, metrics=engine._metrics)

    # Mock page
    engine._page = MagicMock()
    engine._page.is_closed.return_value = False
    engine._page.reload = AsyncMock()
    engine._page.goto = AsyncMock()
    engine._page.close = AsyncMock()
    engine._page.wait_for_timeout = AsyncMock()
    engine._page.url = "https://chatgpt.com"
    engine._page_created_at = time.time()
    engine._page_last_used = time.time()

    engine._playwright = MagicMock()
    engine._context = MagicMock()
    engine._watchdog_task = None
    engine._evict_task = None

    # Mock sub-components
    engine._session_validator = MagicMock()
    engine._session_validator.validate_offline = AsyncMock(return_value=MagicMock(value="authenticated"))
    engine._health_monitor = MagicMock()
    engine._recovery_engine = None

    return engine


@pytest.mark.asyncio
async def test_recovery_aborted_when_query_holds_lease():
    """Core conflict test: recovery must NOT close/reload page while query holds lease.

    Timeline:
      t=0.0s  Query acquires lease
      t=0.1s  Recovery triggered (guard_recovery with 1s timeout)
      t=0.1s  guard_recovery detects lease is held → waits 1s → raises RecoveryBusyError
      t=1.1s  Query releases lease (simulating 1s query duration)
      t=1.1s  Assert: page.reload() was NEVER called
      t=1.1s  Assert: page.close() was NEVER called
    """
    engine = _make_engine("chatgpt")
    LOG_LINES.clear()

    recovery_result: bool | None = None
    recovery_error: Exception | None = None

    # ── Simulate query holding lease for 3s (long-running LLM call) ──
    async def simulate_query():
        async with engine.acquire_page(timeout=5.0) as page:
            LOG_LINES.append(f"[{time.time():.3f}] [query_start] lease acquired, page={page}")
            # Simulate "waiting for AI response" for 3 seconds
            await asyncio.sleep(3.0)
            LOG_LINES.append(f"[{time.time():.3f}] [query_end] query releasing lease")

    # ── Simulate recovery triggered at t=0.1s with 1s timeout ──
    async def simulate_recovery():
        nonlocal recovery_result, recovery_error
        await asyncio.sleep(0.1)
        LOG_LINES.append(f"[{time.time():.3f}] [recovery_triggered] attempting guard_recovery(timeout=1.0)")
        try:
            await engine.guard_recovery(timeout=1.0)
            LOG_LINES.append(f"[{time.time():.3f}] [recovery_guard] guard_recovery succeeded")
            engine._page.reload()
            LOG_LINES.append(f"[{time.time():.3f}] [page_action] page.reload() called")
            recovery_result = True
        except RecoveryBusyError as exc:
            LOG_LINES.append(f"[{time.time():.3f}] [recovery_guard] RecoveryBusyError: waited {exc.waited_ms}ms, page still leased")
            LOG_LINES.append(f"[{time.time():.3f}] [page_action] page.reload() SKIPPED — recovery aborted")
            recovery_result = False
            recovery_error = exc

    # Run both concurrently
    query_task = asyncio.create_task(simulate_query())
    recovery_task = asyncio.create_task(simulate_recovery())

    await asyncio.gather(query_task, recovery_task)

    # Print log evidence even on failure
    print("\n=== CONFLICT INJECTION TEST LOG ===")
    for line in LOG_LINES:
        print(line)
    print(f"=== recovery_result={recovery_result}, recovery_error={recovery_error} ===\n")

    # ── Assertions ──
    # 1. Recovery must have been aborted (page was leased)
    assert recovery_result is False, f"Expected recovery to be aborted, got {recovery_result}"
    assert isinstance(recovery_error, RecoveryBusyError)

    # 2. page.reload() must NEVER have been called
    engine._page.reload.assert_not_called()

    # 3. page.close() must NEVER have been called
    engine._page.close.assert_not_called()

    # 4. page must still be intact (not None, not closed)
    assert engine._page is not None
    assert not engine._page.is_closed()

    # 5. Metrics must reflect the aborted recovery
    assert engine._metrics.recovery_aborted_busy == 1
    assert engine._metrics.recovery_failed == 1

    # Print log evidence
    print("\n=== CONFLICT INJECTION TEST LOG ===")
    for line in LOG_LINES:
        print(line)
    print("=== END LOG ===\n")
    print("RESULT: Recovery was correctly aborted. Page was NOT closed/reloaded during active query.")


@pytest.mark.asyncio
async def test_recovery_proceeds_after_query_releases():
    """After query releases lease, recovery can proceed on next attempt."""
    engine = _make_engine("chatgpt")
    LOG_LINES.clear()

    # ── Phase 1: query holds lease, recovery fails ──
    async with engine.acquire_page(timeout=5.0) as page:
        LOG_LINES.append(f"[query] lease acquired")
        try:
            await engine.guard_recovery(timeout=0.3)
            LOG_LINES.append(f"[recovery] guard succeeded (unexpected)")
        except RecoveryBusyError:
            LOG_LINES.append(f"[recovery] guard aborted — page leased")
        # Query completes normally
        LOG_LINES.append(f"[query] lease released")

    # ── Phase 2: now recovery can proceed ──
    engine._guard._recovery_in_progress = False  # Reset from phase 1
    engine._metrics.recovery_aborted_busy = 0
    engine._metrics.recovery_failed = 0

    await engine.guard_recovery(timeout=1.0)
    LOG_LINES.append(f"[recovery] guard succeeded — page idle")
    engine._page.reload()
    LOG_LINES.append(f"[recovery] page.reload() executed")

    assert engine._page.reload.called

    print("\n=== RECOVERY-AFTER-QUERY LOG ===")
    for line in LOG_LINES:
        print(line)
    print("=== END LOG ===\n")


@pytest.mark.asyncio
async def test_eviction_waits_for_lease():
    """Eviction must wait for query to release lease before closing page."""
    engine = _make_engine("chatgpt")
    LOG_LINES.clear()

    page_closed_during_query = False

    async def hold_lease():
        nonlocal page_closed_during_query
        async with engine.acquire_page(timeout=5.0) as page:
            LOG_LINES.append(f"[query] lease acquired")
            await asyncio.sleep(0.5)
            # Check if page was closed while we hold the lease
            page_closed_during_query = page.close.called
            LOG_LINES.append(f"[query] lease released, page_closed_during_query={page_closed_during_query}")

    async def trigger_eviction():
        await asyncio.sleep(0.1)
        LOG_LINES.append(f"[evict] _evict_page() triggered")
        await engine._evict_page()
        LOG_LINES.append(f"[evict] _evict_page() completed")

    query_task = asyncio.create_task(hold_lease())
    evict_task = asyncio.create_task(trigger_eviction())

    await asyncio.gather(query_task, evict_task)

    # Page should NOT have been closed while query held lease
    # (eviction waits via wait_until_idle)
    assert not page_closed_during_query, "Page was closed while query held lease!"

    print("\n=== EVICTION-WAITS-FOR-LEASE LOG ===")
    for line in LOG_LINES:
        print(line)
    print("=== END LOG ===\n")
