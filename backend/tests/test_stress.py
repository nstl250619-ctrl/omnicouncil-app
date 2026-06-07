"""Stress tests — simulate sustained heartbeat and random failure recovery.

Tests:
    - 100 heartbeat rounds with random session expiry
    - Recovery engine under repeated failures
    - State machine under rapid transitions
    - Concurrent ensure_ready calls
"""

from __future__ import annotations

import asyncio
import random
from unittest.mock import AsyncMock, MagicMock

import pytest

from engine.contracts import RecoveryFailedError, RuntimeState
from runtime.health_monitor import HealthMonitor
from runtime.recovery_engine import RecoveryEngine
from runtime.recovery_strategies import ReloadStrategy
from runtime.state_machine import RuntimeStateMachine
from shared.types import SessionState


# ============================================================
#  1. Heartbeat stress — 100 rounds with random expiry
# ============================================================


class TestHeartbeatStress:

    def test_100_rounds_random_expiry(self):
        """Simulate 100 heartbeat rounds with ~10% chance of session expiry."""
        hm = HealthMonitor(interval_s=1)
        sv = MagicMock()
        sv.validate_offline = AsyncMock(return_value=SessionState.AUTHENTICATED)
        page = MagicMock()
        page.is_closed.return_value = False
        hm.register("deepseek", sv, get_page_fn=lambda: page)

        expiry_count = 0
        for i in range(100):
            # 10% chance of session expiry
            if random.random() < 0.1:
                sv.validate_offline = AsyncMock(return_value=SessionState.AUTH_EXPIRED)
                expiry_count += 1
            else:
                sv.validate_offline = AsyncMock(return_value=SessionState.AUTHENTICATED)

            asyncio.run(hm._heartbeat_round())

        health = hm.get_health("deepseek")
        assert health.last_heartbeat > 0
        # After 100 rounds, the final state depends on the last check
        assert health.state in (RuntimeState.READY, RuntimeState.LOGIN_REQUIRED)


# ============================================================
#  2. Recovery engine stress — repeated failures
# ============================================================


class TestRecoveryStress:

    def test_recovery_exhaustion(self):
        """Exhaust all recovery attempts and verify RecoveryFailedError."""
        engine = MagicMock()
        sm = RuntimeStateMachine(initial=RuntimeState.DEGRADED)
        engine.state_machine = sm
        engine.get_page.return_value = None  # all strategies fail

        re = RecoveryEngine(max_attempts=3, cooldown_s=0)

        total_attempts = 0
        for round_num in range(3):
            try:
                asyncio.run(re.recover(engine, "deepseek"))
                total_attempts += 1
            except RecoveryFailedError:
                total_attempts += 1
                break

        assert total_attempts == 3
        assert re.get_attempt_count("deepseek") == 3

    def test_recovery_success_after_failures(self):
        """Recovery succeeds on the 3rd round."""
        call_count = 0

        class FlakyStrategy:
            name = "flaky"
            timeout_s = 5

            async def recover(self, engine, platform):
                nonlocal call_count
                call_count += 1
                return call_count >= 3  # succeeds on 3rd call

        engine = MagicMock()
        sm = RuntimeStateMachine(initial=RuntimeState.DEGRADED)
        engine.state_machine = sm

        re = RecoveryEngine(
            strategies=[FlakyStrategy()],
            max_attempts=5,
            cooldown_s=0,
        )

        # First 2 rounds fail
        result = asyncio.run(re.recover(engine, "deepseek"))
        assert result is False
        result = asyncio.run(re.recover(engine, "deepseek"))
        assert result is False

        # 3rd round succeeds
        result = asyncio.run(re.recover(engine, "deepseek"))
        assert result is True
        assert sm.current == RuntimeState.READY


# ============================================================
#  3. State machine stress — rapid transitions
# ============================================================


class TestStateMachineStress:

    def test_rapid_transitions(self):
        """Perform 1000 rapid transitions."""
        sm = RuntimeStateMachine()
        states = [
            RuntimeState.INITIALIZING,
            RuntimeState.PROFILE_LOADING,
            RuntimeState.SESSION_CHECKING,
            RuntimeState.READY,
            RuntimeState.DEGRADED,
            RuntimeState.RECOVERING,
            RuntimeState.READY,
            RuntimeState.SHUTDOWN,
        ]

        for _ in range(125):  # 125 * 8 = 1000
            for state in states:
                asyncio.run(sm.transition(state, "stress test"))

        assert len(sm.history) == 1000
        assert sm.current == RuntimeState.SHUTDOWN

    def test_concurrent_transitions(self):
        """50 concurrent coroutines racing for the same transition."""
        sm = RuntimeStateMachine(initial=RuntimeState.READY)
        results = []

        async def try_transition():
            try:
                await sm.transition(RuntimeState.DEGRADED, "race")
                results.append(True)
            except Exception:
                results.append(False)

        async def run_all():
            await asyncio.gather(*[try_transition() for _ in range(50)])

        asyncio.run(run_all())

        # Exactly one should succeed
        assert sum(results) == 1
        assert sm.current == RuntimeState.DEGRADED
        assert len(sm.history) == 1


# ============================================================
#  4. Health monitor stress — many platforms
# ============================================================


class TestHealthMonitorStress:

    def test_50_platforms(self):
        """Register 50 platforms and run a heartbeat round."""
        hm = HealthMonitor()
        for i in range(50):
            sv = MagicMock()
            sv.validate_offline = AsyncMock(return_value=SessionState.AUTHENTICATED)
            page = MagicMock()
            page.is_closed.return_value = False
            hm.register(f"platform_{i}", sv, get_page_fn=lambda p=page: p)

        asyncio.run(hm._heartbeat_round())

        all_health = hm.get_all_health()
        assert len(all_health) == 50
        for platform, health in all_health.items():
            assert health.state == RuntimeState.READY
