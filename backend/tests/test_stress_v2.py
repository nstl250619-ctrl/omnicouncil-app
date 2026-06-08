"""Stress tests for V2 Page Lease / Recovery / Eviction (Phase 8).

50 轮串行 + 100 轮 5-AI 并发压测。

Tests the new V2 contracts without spinning up a real browser:
    - ``PageBusyError`` is raised when the lease is held
    - ``acquire_page()`` releases the lease on exit
    - ``RecoveryEngine.recover()`` aborts on page busy
    - Eviction never returns a page reference that is being torn down
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any
from unittest.mock import MagicMock

import pytest

from engine.contracts import (
    PageBusyError,
    PlatformConfig,
    RecoveryBusyError,
    RuntimeMetrics,
    RuntimeState,
)
from runtime.engine import AIRuntimeEngine
from runtime.recovery_engine import RecoveryEngine


# ---------------- Helpers ----------------

PLATFORMS = ["deepseek", "qianwen", "gemini", "chatgpt", "mimo"]


def make_config(name: str) -> PlatformConfig:
    return PlatformConfig(
        name=name,
        home_url=f"https://example.com/{name}",
        headless=True,
        heartbeat_interval_s=60,
        max_recovery_attempts=3,
        recovery_cooldown_s=30,
        session_check_mode="offline_then_online",
    )


def make_engine(name: str) -> AIRuntimeEngine:
    """Build an engine without actually launching a browser."""
    config = make_config(name)
    # Stub out sub-components so __init__ does not touch disk/network
    engine = AIRuntimeEngine.__new__(AIRuntimeEngine)
    engine._config = config
    engine._platform = name

    # State machine stub
    sm = MagicMock()
    sm.current = RuntimeState.READY
    sm.can_transition.return_value = True
    sm.transition = AsyncMockOK()
    engine._state_machine = sm

    # Profile / session / health / recovery stubs
    engine._profile_manager = MagicMock()
    engine._session_validator = MagicMock()
    engine._health_monitor = MagicMock()
    engine._recovery_engine = MagicMock()

    # Browser state
    engine._playwright = MagicMock()
    engine._context = MagicMock()
    # _recreate_page() awaits _context.new_page() + page.goto() +
    # page.wait_for_timeout() — use real async callables so the
    # post-eviction recreation branch can be exercised.
    new_page_mock = MagicMock()
    new_page_mock.is_closed.return_value = False

    async def _new_page_async(*a, **kw):
        return new_page_mock

    async def _goto_async(*a, **kw):
        return None

    async def _wait_async(*a, **kw):
        return None

    new_page_mock.goto = _goto_async
    new_page_mock.wait_for_timeout = _wait_async
    engine._context.new_page = _new_page_async
    fake_page = MagicMock()
    fake_page.is_closed.return_value = False
    fake_page.goto = _goto_async
    fake_page.wait_for_timeout = _wait_async
    engine._page = fake_page
    engine._page_created_at = time.time()
    engine._page_last_used = time.time()

    # Watchdog
    engine._watchdog_task = None

    # Phase 3-5 lease control (P1-3: real PageGuard)
    from runtime.page_guard import PageGuard
    engine._metrics = RuntimeMetrics(platform=name)
    engine._guard = PageGuard(platform=name, metrics=engine._metrics)
    engine._evict_task = None

    return engine


class AsyncMockOK:
    """Mock for state machine transitions that always succeeds."""

    async def __call__(self, *args: Any, **kwargs: Any) -> None:
        return None


# ---------------- Phase 8: 50 轮串行压测 ----------------

@pytest.mark.asyncio
async def test_stress_50_serial() -> None:
    """5 platforms × 10 rounds = 50 serial queries."""
    engines = {p: make_engine(p) for p in PLATFORMS}
    rounds: list[dict[str, Any]] = []
    successes = 0
    failures = 0

    for round_idx in range(10):
        for platform, engine in engines.items():
            t0 = time.time()
            try:
                async with engine.acquire_page(timeout=5.0) as page:
                    # Simulate a quick query (no real DOM work)
                    await asyncio.sleep(0.001)
                    assert page is engine._page
                    engine._metrics.query_total += 1
                    engine._metrics.query_succeeded += 1
                successes += 1
            except Exception as exc:
                failures += 1
                engine._metrics.query_failed += 1
                pytest.fail(f"serial query failed: {platform}: {exc}")
            rounds.append(
                {
                    "round": round_idx,
                    "platform": platform,
                    "duration_ms": round((time.time() - t0) * 1000, 2),
                }
            )

    assert successes == 50
    assert failures == 0
    for engine in engines.values():
        m = engine.metrics()
        assert m.page_lease_acquired == 10
        assert m.page_lease_released == 10
        assert m.query_succeeded == 10
        assert m.page_busy_rejections == 0

    # Persist a snapshot for the stress report
    _write_log("stress_50_serial.json",
               {"rounds": rounds, "successes": successes, "failures": failures})


# ---------------- Phase 8: 100 轮 5-AI 并发压测 ----------------

@pytest.mark.asyncio
async def test_stress_100_concurrent() -> None:
    """100 rounds × 5 concurrent platforms = 500 queries."""
    engines = {p: make_engine(p) for p in PLATFORMS}
    rounds_log: list[dict[str, Any]] = []
    total_success = 0
    total_failure = 0
    recovery_rounds = 0

    async def one_query(platform: str, engine: AIRuntimeEngine, round_idx: int) -> bool:
        t0 = time.time()
        try:
            async with engine.acquire_page(timeout=5.0):
                await asyncio.sleep(0.001)
                engine._metrics.query_total += 1
                engine._metrics.query_succeeded += 1
            return True
        except PageBusyError:
            engine._metrics.query_failed += 1
            return False
        finally:
            rounds_log.append(
                {
                    "round": round_idx,
                    "platform": platform,
                    "duration_ms": round((time.time() - t0) * 1000, 2),
                }
            )

    for round_idx in range(100):
        tasks = [one_query(p, engines[p], round_idx) for p in PLATFORMS]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        total_success += sum(1 for r in results if r)
        total_failure += sum(1 for r in results if not r)

    # All 500 queries should succeed in synchronous-lease mode
    assert total_success == 500
    assert total_failure == 0
    for engine in engines.values():
        m = engine.metrics()
        assert m.page_lease_acquired == 100
        assert m.page_lease_released == 100
        assert m.query_succeeded == 100
        assert m.page_busy_rejections == 0
        # No recovery triggered (the runtime was healthy throughout)
        assert m.recovery_started == 0

    _write_log("stress_100_concurrent.json",
               {"rounds": rounds_log, "successes": total_success,
                "failures": total_failure, "recovery_rounds": recovery_rounds})


# ---------------- Targeted race / guard tests ----------------

@pytest.mark.asyncio
async def test_acquire_page_busy_rejected() -> None:
    """A second acquire while the first holds the lease must raise PageBusyError."""
    engine = make_engine("deepseek")
    async with engine.acquire_page(timeout=1.0):
        with pytest.raises(PageBusyError):
            async with engine.acquire_page(timeout=0.2):
                pass  # never reached
    assert engine.metrics().page_busy_rejections == 1
    # After the first releases, the second can acquire
    async with engine.acquire_page(timeout=0.2):
        pass
    assert engine.metrics().page_lease_acquired == 2


@pytest.mark.asyncio
async def test_recovery_blocks_new_acquires() -> None:
    """While _recovery_in_progress is True, new acquire_page() must reject."""
    engine = make_engine("qianwen")
    engine._guard.mark_recovery()
    with pytest.raises(PageBusyError):
        async with engine.acquire_page(timeout=0.2):
            pass
    assert engine.metrics().page_busy_rejections == 1
    # Once recovery clears, the next acquire succeeds
    engine._guard.clear_recovery(succeeded=True)
    async with engine.acquire_page(timeout=0.2):
        pass


@pytest.mark.asyncio
async def test_pending_evict_blocks_new_acquires() -> None:
    """While _pending_evict is True, new acquire_page() must reject."""
    engine = make_engine("gemini")
    engine._guard.mark_evict()
    with pytest.raises(PageBusyError):
        async with engine.acquire_page(timeout=0.2):
            pass


@pytest.mark.asyncio
async def test_evict_waits_for_lease() -> None:
    """_evict_page must wait for in-flight query to release the lease."""
    engine = make_engine("chatgpt")
    # Hold the lease in the background
    holder_acquired = asyncio.Event()
    holder_release = asyncio.Event()
    holder_done = asyncio.Event()

    async def holder() -> None:
        async with engine.acquire_page(timeout=1.0):
            holder_acquired.set()
            await holder_release.wait()
        holder_done.set()

    asyncio.create_task(holder())
    await holder_acquired.wait()

    # Trigger eviction while the lease is held
    evict_task = asyncio.create_task(engine._evict_page())

    # Eviction must NOT have completed yet
    await asyncio.sleep(0.1)
    assert not evict_task.done(), "eviction completed while lease was held"

    # Release the lease
    holder_release.set()
    await holder_done.wait()
    await evict_task

    # Page must now be None
    assert engine._page is None
    assert engine.metrics().eviction_completed == 1
    assert engine.metrics().page_destroyed == 1


@pytest.mark.asyncio
async def test_recovery_aborts_on_page_busy() -> None:
    """RecoveryEngine.recover() must raise RecoveryBusyError when page is held."""
    engine = make_engine("mimo")
    rec = RecoveryEngine(
        strategies=[],  # empty chain; we only test the busy guard
        max_attempts=3,
        cooldown_s=0,
    )

    # Hold the lease indefinitely
    async def hold_lease_forever() -> None:
        async with engine.acquire_page(timeout=10.0):
            await asyncio.sleep(10.0)

    holder = asyncio.create_task(hold_lease_forever())
    await asyncio.sleep(0.05)  # let the lock acquire

    with pytest.raises(RecoveryBusyError):
        await rec.recover(engine, "mimo")

    assert engine.metrics().recovery_aborted_busy == 1

    holder.cancel()
    try:
        await holder
    except (asyncio.CancelledError, Exception):
        pass


@pytest.mark.asyncio
async def test_metrics_snapshot_complete() -> None:
    """RuntimeMetrics.snapshot() exposes every counter required by Phase 7."""
    engine = make_engine("deepseek")
    async with engine.acquire_page(timeout=1.0):
        pass
    snap = engine.metrics().snapshot()
    required = {
        "page_created", "page_destroyed", "page_lease_acquired",
        "page_lease_released", "page_busy_rejections", "recovery_started",
        "recovery_succeeded", "recovery_failed", "recovery_aborted_busy",
        "session_expired", "query_total", "query_succeeded", "query_failed",
        "eviction_started", "eviction_completed",
    }
    assert required.issubset(snap.keys())


# ---------------- P0-2: Eviction actually triggered ----------------

@pytest.mark.asyncio
async def test_acquire_page_triggers_eviction_when_stale() -> None:
    """When the page is past MAX_IDLE, acquire_page() should fire eviction
    and the lease should still complete (or be rejected with PageBusyError
    if the eviction takes too long).  Either way, eviction_started > 0."""
    engine = make_engine("deepseek")
    # Backdate the page so it looks stale
    engine._page_last_used = time.time() - 200  # > MAX_IDLE_S (120)
    async with engine.acquire_page(timeout=2.0) as page:
        assert page is not None
    m = engine.metrics()
    assert m.eviction_started >= 1
    # If eviction ran fully, page_destroyed should bump
    # (best-effort — depending on race with lease acquisition)
    assert m.page_lease_acquired == 1
    assert m.page_lease_released == 1


@pytest.mark.asyncio
async def test_eviction_runs_to_completion_on_next_acquire() -> None:
    """The eviction scheduled by acquire_page() must complete and the
    page must be RECREATED before the lease is handed out."""
    engine = make_engine("qianwen")
    engine._page_last_used = time.time() - 300
    # First acquire triggers eviction + recreation
    async with engine.acquire_page(timeout=2.0) as page:
        # The lease should yield a non-None page (recreated)
        assert page is not None
    m = engine.metrics()
    # The eviction ran (page_destroyed bumped) AND a new page was created
    assert m.eviction_started >= 1
    assert m.eviction_completed >= 1
    assert m.page_destroyed >= 1
    # page_created bumped by _recreate_page (mock engine starts at 0)
    assert m.page_created >= 1
    assert m.page_lease_acquired == 1
    assert m.page_lease_released == 1


# ---------------- Logging helper ----------------

def _write_log(name: str, payload: dict[str, Any]) -> None:
    """Persist stress logs to /tmp for the Phase 8 report."""
    import os
    log_dir = "/tmp/omnicouncil_stress"
    os.makedirs(log_dir, exist_ok=True)
    with open(f"{log_dir}/{name}", "w") as f:
        json.dump(payload, f, indent=2)
