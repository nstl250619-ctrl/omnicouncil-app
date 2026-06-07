"""Tests for RuntimeStateMachine — state transitions, concurrency, conversions.

Covers:
    - All 24 legal transitions in the TRANSITIONS matrix
    - All illegal transitions (every unreachable pair)
    - History recording and ordering
    - Concurrency safety (parallel transitions)
    - Conversion helpers (SessionState ↔ RuntimeState, RuntimeState → HealthStatus)
    - reset(), can_transition(), transition_safe()
    - Callback invocation
"""

from __future__ import annotations

import asyncio

import pytest

from engine.contracts import (
    TRANSITIONS,
    HealthStatus,
    IllegalStateTransitionError,
    RuntimeState,
    StateTransition,
)
from runtime.state_machine import (
    RuntimeStateMachine,
    runtime_state_to_health,
    session_state_to_runtime,
)
from shared.types import SessionState

# ============================================================
#  Fixtures
# ============================================================


@pytest.fixture
def sm() -> RuntimeStateMachine:
    """Fresh state machine in UNKNOWN state."""
    return RuntimeStateMachine()


# ============================================================
#  1. All legal transitions (24 edges)
# ============================================================

class TestLegalTransitions:
    """Every edge in TRANSITIONS must succeed."""

    @pytest.mark.parametrize(
        "from_state,to_state",
        [
            (src, dst)
            for src, dsts in TRANSITIONS.items()
            for dst in dsts
        ],
        ids=lambda v: f"{v[0].value}->{v[1].value}" if isinstance(v, tuple) else str(v),
    )
    def test_legal_transition(self, from_state: RuntimeState, to_state: RuntimeState):
        sm = RuntimeStateMachine(initial=from_state)
        # Should not raise
        asyncio.run(sm.transition(to_state, reason="test"))
        assert sm.current == to_state


# ============================================================
#  2. All illegal transitions
# ============================================================

class TestIllegalTransitions:
    """Every pair NOT in TRANSITIONS must raise IllegalStateTransitionError."""

    def _illegal_pairs(self):
        all_states = set(RuntimeState)
        for src in RuntimeState:
            allowed = TRANSITIONS.get(src, set())
            illegal = all_states - allowed - {src}  # exclude self-transitions too
            for dst in illegal:
                yield src, dst

    @pytest.mark.parametrize(
        "from_state,to_state",
        list(_illegal_pairs(None)),
        ids=lambda v: f"{v[0].value}->!{v[1].value}" if isinstance(v, tuple) else str(v),
    )
    def test_illegal_transition_raises(self, from_state: RuntimeState, to_state: RuntimeState):
        sm = RuntimeStateMachine(initial=from_state)
        with pytest.raises(IllegalStateTransitionError) as exc_info:
            asyncio.run(sm.transition(to_state))
        assert exc_info.value.from_state == from_state
        assert exc_info.value.to_state == to_state
        assert exc_info.value.code == "ILLEGAL_TRANSITION"
        # State must not have changed
        assert sm.current == from_state


# ============================================================
#  3. History recording
# ============================================================

class TestHistory:
    """Transitions are recorded in order with correct metadata."""

    def test_history_records_transitions(self, sm: RuntimeStateMachine):
        asyncio.run(sm.transition(RuntimeState.INITIALIZING, reason="boot"))
        asyncio.run(sm.transition(RuntimeState.PROFILE_LOADING, reason="load profile"))

        history = sm.history
        assert len(history) == 2

        assert history[0].from_state == RuntimeState.UNKNOWN
        assert history[0].to_state == RuntimeState.INITIALIZING
        assert history[0].reason == "boot"
        assert history[0].success is True
        assert history[0].timestamp > 0

        assert history[1].from_state == RuntimeState.INITIALIZING
        assert history[1].to_state == RuntimeState.PROFILE_LOADING
        assert history[1].reason == "load profile"

    def test_history_is_copy(self, sm: RuntimeStateMachine):
        asyncio.run(sm.transition(RuntimeState.INITIALIZING))
        h1 = sm.history
        h2 = sm.history
        assert h1 == h2
        assert h1 is not h2  # returned list is a copy

    def test_last_transition(self, sm: RuntimeStateMachine):
        assert sm.last_transition() is None
        asyncio.run(sm.transition(RuntimeState.INITIALIZING))
        last = sm.last_transition()
        assert last is not None
        assert last.to_state == RuntimeState.INITIALIZING

    def test_history_cleared_on_reset(self, sm: RuntimeStateMachine):
        asyncio.run(sm.transition(RuntimeState.INITIALIZING))
        assert len(sm.history) == 1
        asyncio.run(sm.reset(RuntimeState.UNKNOWN))
        assert len(sm.history) == 0
        assert sm.current == RuntimeState.UNKNOWN


# ============================================================
#  4. can_transition() — non-mutating check
# ============================================================

class TestCanTransition:

    def test_can_transition_valid(self, sm: RuntimeStateMachine):
        assert sm.can_transition(RuntimeState.INITIALIZING) is True

    def test_can_transition_invalid(self, sm: RuntimeStateMachine):
        assert sm.can_transition(RuntimeState.READY) is False
        assert sm.can_transition(RuntimeState.SHUTDOWN) is False

    def test_can_transition_after_move(self, sm: RuntimeStateMachine):
        asyncio.run(sm.transition(RuntimeState.INITIALIZING))
        assert sm.can_transition(RuntimeState.PROFILE_LOADING) is True
        assert sm.can_transition(RuntimeState.READY) is False


# ============================================================
#  5. transition_safe() — boolean wrapper
# ============================================================

class TestTransitionSafe:

    def test_safe_valid(self, sm: RuntimeStateMachine):
        result = asyncio.run(sm.transition_safe(RuntimeState.INITIALIZING))
        assert result is True
        assert sm.current == RuntimeState.INITIALIZING

    def test_safe_invalid(self, sm: RuntimeStateMachine):
        result = asyncio.run(sm.transition_safe(RuntimeState.READY))
        assert result is False
        assert sm.current == RuntimeState.UNKNOWN


# ============================================================
#  6. Concurrency safety
# ============================================================

class TestConcurrency:
    """Parallel transitions must not corrupt state."""

    def test_concurrent_transitions_only_one_succeeds(self):
        """Two coroutines racing to transition from UNKNOWN — only one wins."""
        sm = RuntimeStateMachine(initial=RuntimeState.UNKNOWN)
        results = []

        async def attempt():
            try:
                await sm.transition(RuntimeState.INITIALIZING, reason="race")
                results.append(True)
            except IllegalStateTransitionError:
                results.append(False)

        async def run_both():
            await asyncio.gather(attempt(), attempt())

        asyncio.run(run_both())

        # Exactly one should have succeeded
        assert sum(results) == 1
        assert sm.current == RuntimeState.INITIALIZING
        assert len(sm.history) == 1

    def test_concurrent_different_targets(self):
        """From READY, two coroutines try DEGRADED and SHUTDOWN concurrently."""
        sm = RuntimeStateMachine(initial=RuntimeState.READY)
        results = {}

        async def try_degraded():
            try:
                await sm.transition(RuntimeState.DEGRADED, reason="degraded")
                results["degraded"] = True
            except IllegalStateTransitionError:
                results["degraded"] = False

        async def try_shutdown():
            try:
                await sm.transition(RuntimeState.SHUTDOWN, reason="shutdown")
                results["shutdown"] = True
            except IllegalStateTransitionError:
                results["shutdown"] = False

        async def run_both():
            await asyncio.gather(try_degraded(), try_shutdown())

        asyncio.run(run_both())

        # Exactly one should succeed (both are valid from READY, but
        # after one succeeds the other becomes illegal)
        success_count = sum(1 for v in results.values() if v)
        assert success_count == 1
        assert len(sm.history) == 1

    def test_sequential_transitions_full_boot_cycle(self):
        """Full boot sequence: UNKNOWN → … → READY."""
        sm = RuntimeStateMachine()
        asyncio.run(sm.transition(RuntimeState.INITIALIZING, "boot"))
        asyncio.run(sm.transition(RuntimeState.PROFILE_LOADING, "profile"))
        asyncio.run(sm.transition(RuntimeState.SESSION_CHECKING, "session"))
        asyncio.run(sm.transition(RuntimeState.READY, "session valid"))

        assert sm.current == RuntimeState.READY
        assert len(sm.history) == 4
        assert sm.is_actionable is True


# ============================================================
#  7. Callback invocation
# ============================================================

class TestCallback:

    def test_callback_called_on_transition(self):
        records = []

        def cb(record: StateTransition):
            records.append(record)

        sm = RuntimeStateMachine(on_transition=cb)
        asyncio.run(sm.transition(RuntimeState.INITIALIZING, reason="boot"))

        assert len(records) == 1
        assert records[0].to_state == RuntimeState.INITIALIZING
        assert records[0].reason == "boot"

    def test_async_callback_called(self):
        records = []

        async def cb(record: StateTransition):
            records.append(record)

        sm = RuntimeStateMachine(on_transition=cb)
        asyncio.run(sm.transition(RuntimeState.INITIALIZING))

        assert len(records) == 1

    def test_callback_exception_does_not_propagate(self):
        def bad_cb(record: StateTransition):
            raise ValueError("oops")

        sm = RuntimeStateMachine(on_transition=bad_cb)
        # Should not raise — callback error is logged, not propagated
        asyncio.run(sm.transition(RuntimeState.INITIALIZING))
        assert sm.current == RuntimeState.INITIALIZING

    def test_callback_not_called_on_illegal_transition(self):
        records = []

        def cb(record: StateTransition):
            records.append(record)

        sm = RuntimeStateMachine(on_transition=cb)
        with pytest.raises(IllegalStateTransitionError):
            asyncio.run(sm.transition(RuntimeState.READY))

        assert len(records) == 0


# ============================================================
#  8. allowed_targets / is_terminal / is_actionable
# ============================================================

class TestProperties:

    def test_allowed_targets(self, sm: RuntimeStateMachine):
        assert sm.allowed_targets == {RuntimeState.INITIALIZING}

    def test_is_terminal(self, sm: RuntimeStateMachine):
        assert sm.is_terminal is False

        asyncio.run(sm.transition(RuntimeState.INITIALIZING))
        asyncio.run(sm.transition(RuntimeState.UNAVAILABLE))
        assert sm.is_terminal is True

    def test_is_actionable(self, sm: RuntimeStateMachine):
        assert sm.is_actionable is False
        asyncio.run(sm.transition(RuntimeState.INITIALIZING))
        asyncio.run(sm.transition(RuntimeState.PROFILE_LOADING))
        asyncio.run(sm.transition(RuntimeState.SESSION_CHECKING))
        asyncio.run(sm.transition(RuntimeState.READY))
        assert sm.is_actionable is True


# ============================================================
#  9. Conversion helpers
# ============================================================

class TestConversions:

    # --- SessionState → RuntimeState ---

    def test_session_authenticated_maps_to_none(self):
        assert session_state_to_runtime(SessionState.AUTHENTICATED) is None

    def test_session_unknown_maps_to_none(self):
        assert session_state_to_runtime(SessionState.UNKNOWN) is None

    def test_session_expired_maps_to_login_required(self):
        assert session_state_to_runtime(SessionState.AUTH_EXPIRED) == RuntimeState.LOGIN_REQUIRED

    def test_session_reauth_maps_to_recovering(self):
        assert session_state_to_runtime(SessionState.REAUTH_IN_PROGRESS) == RuntimeState.RECOVERING

    # --- RuntimeState → HealthStatus ---

    def test_ready_maps_to_healthy(self):
        assert runtime_state_to_health(RuntimeState.READY) == HealthStatus.HEALTHY

    def test_degraded_maps_to_degraded(self):
        assert runtime_state_to_health(RuntimeState.DEGRADED) == HealthStatus.DEGRADED

    def test_unavailable_maps_to_unhealthy(self):
        assert runtime_state_to_health(RuntimeState.UNAVAILABLE) == HealthStatus.UNHEALTHY

    def test_login_required_maps_to_unhealthy(self):
        assert runtime_state_to_health(RuntimeState.LOGIN_REQUIRED) == HealthStatus.UNHEALTHY

    def test_recovering_maps_to_degraded(self):
        assert runtime_state_to_health(RuntimeState.RECOVERING) == HealthStatus.DEGRADED

    def test_unknown_states_map_to_unknown(self):
        for state in (
            RuntimeState.UNKNOWN,
            RuntimeState.INITIALIZING,
            RuntimeState.PROFILE_LOADING,
            RuntimeState.SESSION_CHECKING,
            RuntimeState.SHUTDOWN,
        ):
            assert runtime_state_to_health(state) == HealthStatus.UNKNOWN, f"{state} should map to UNKNOWN"


# ============================================================
#  10. Full lifecycle scenarios
# ============================================================

class TestFullLifecycle:
    """End-to-end state sequences that mirror real engine behaviour."""

    def test_happy_boot_to_ready(self, sm: RuntimeStateMachine):
        asyncio.run(sm.transition(RuntimeState.INITIALIZING, "launch browser"))
        asyncio.run(sm.transition(RuntimeState.PROFILE_LOADING, "load profile"))
        asyncio.run(sm.transition(RuntimeState.SESSION_CHECKING, "check cookies"))
        asyncio.run(sm.transition(RuntimeState.READY, "session valid"))
        assert sm.current == RuntimeState.READY
        assert sm.is_actionable

    def test_boot_fails_to_unavailable(self, sm: RuntimeStateMachine):
        asyncio.run(sm.transition(RuntimeState.INITIALIZING, "launch browser"))
        asyncio.run(sm.transition(RuntimeState.UNAVAILABLE, "browser crash"))
        assert sm.current == RuntimeState.UNAVAILABLE
        assert sm.is_terminal

    def test_session_expired_then_recovery(self, sm: RuntimeStateMachine):
        """READY → LOGIN_REQUIRED → RECOVERING → READY"""
        # Boot
        for state, reason in [
            (RuntimeState.INITIALIZING, "boot"),
            (RuntimeState.PROFILE_LOADING, "profile"),
            (RuntimeState.SESSION_CHECKING, "session"),
            (RuntimeState.READY, "ok"),
        ]:
            asyncio.run(sm.transition(state, reason))

        # Session expires
        asyncio.run(sm.transition(RuntimeState.LOGIN_REQUIRED, "cookie expired"))
        assert sm.current == RuntimeState.LOGIN_REQUIRED

        # Recovery starts
        asyncio.run(sm.transition(RuntimeState.RECOVERING, "reload page"))
        assert sm.current == RuntimeState.RECOVERING

        # Recovery succeeds
        asyncio.run(sm.transition(RuntimeState.READY, "session restored"))
        assert sm.current == RuntimeState.READY
        assert sm.is_actionable

    def test_degraded_then_recovery(self, sm: RuntimeStateMachine):
        """READY → DEGRADED → RECOVERING → READY"""
        for state, reason in [
            (RuntimeState.INITIALIZING, "boot"),
            (RuntimeState.PROFILE_LOADING, "profile"),
            (RuntimeState.SESSION_CHECKING, "session"),
            (RuntimeState.READY, "ok"),
        ]:
            asyncio.run(sm.transition(state, reason))

        asyncio.run(sm.transition(RuntimeState.DEGRADED, "page unresponsive"))
        asyncio.run(sm.transition(RuntimeState.RECOVERING, "try reload"))
        asyncio.run(sm.transition(RuntimeState.READY, "reload worked"))

        assert sm.current == RuntimeState.READY
        assert len(sm.history) == 7

    def test_recovery_exhaustion_to_unavailable(self, sm: RuntimeStateMachine):
        """READY → DEGRADED → RECOVERING → UNAVAILABLE"""
        for state, reason in [
            (RuntimeState.INITIALIZING, "boot"),
            (RuntimeState.PROFILE_LOADING, "profile"),
            (RuntimeState.SESSION_CHECKING, "session"),
            (RuntimeState.READY, "ok"),
        ]:
            asyncio.run(sm.transition(state, reason))

        asyncio.run(sm.transition(RuntimeState.DEGRADED, "page dead"))
        asyncio.run(sm.transition(RuntimeState.RECOVERING, "attempt 1"))
        asyncio.run(sm.transition(RuntimeState.UNAVAILABLE, "all strategies failed"))

        assert sm.current == RuntimeState.UNAVAILABLE
        assert sm.is_terminal

    def test_restart_from_shutdown(self, sm: RuntimeStateMachine):
        """SHUTDOWN → INITIALIZING → … → READY"""
        asyncio.run(sm.transition(RuntimeState.INITIALIZING, "boot"))
        asyncio.run(sm.transition(RuntimeState.PROFILE_LOADING, "profile"))
        asyncio.run(sm.transition(RuntimeState.SESSION_CHECKING, "session"))
        asyncio.run(sm.transition(RuntimeState.READY, "ok"))
        asyncio.run(sm.transition(RuntimeState.SHUTDOWN, "user quit"))

        # Restart
        asyncio.run(sm.transition(RuntimeState.INITIALIZING, "reboot"))
        asyncio.run(sm.transition(RuntimeState.PROFILE_LOADING, "profile"))
        asyncio.run(sm.transition(RuntimeState.SESSION_CHECKING, "session"))
        asyncio.run(sm.transition(RuntimeState.READY, "ok"))

        assert sm.current == RuntimeState.READY
        assert len(sm.history) == 9  # 5 first run + 4 restart

    def test_restart_from_unavailable(self, sm: RuntimeStateMachine):
        """UNAVAILABLE → INITIALIZING → … → READY"""
        asyncio.run(sm.transition(RuntimeState.INITIALIZING, "boot"))
        asyncio.run(sm.transition(RuntimeState.UNAVAILABLE, "fail"))

        asyncio.run(sm.transition(RuntimeState.INITIALIZING, "retry"))
        asyncio.run(sm.transition(RuntimeState.PROFILE_LOADING, "profile"))
        asyncio.run(sm.transition(RuntimeState.SESSION_CHECKING, "session"))
        asyncio.run(sm.transition(RuntimeState.READY, "ok"))

        assert sm.current == RuntimeState.READY
