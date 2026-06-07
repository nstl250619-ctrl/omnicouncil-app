"""RuntimeStateMachine — the heart of the Runtime Engine.

Implements the 10-state lifecycle machine defined in ``engine.contracts``.
Every transition is validated against the hard-coded ``TRANSITIONS`` matrix,
logged, recorded in history, and optionally triggers a callback.

Concurrency safety:
    All public methods acquire ``self._lock`` so that concurrent coroutines
    cannot observe an intermediate state or race on the same transition.

Usage::

    sm = RuntimeStateMachine(initial=RuntimeState.UNKNOWN)
    sm.transition(RuntimeState.INITIALIZING, reason="boot started")
    assert sm.current == RuntimeState.INITIALIZING
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from engine.contracts import (
    TRANSITIONS,
    HealthStatus,
    IllegalStateTransitionError,
    RuntimeState,
    StateTransition,
)
from shared.types import SessionState

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


class RuntimeStateMachine:
    """Concrete implementation of the ``RuntimeStateMachine`` Protocol.

    Parameters
    ----------
    initial:
        The starting state (default ``UNKNOWN``).
    on_transition:
        Optional async callback invoked after every successful transition.
        Signature: ``async def cb(record: StateTransition) -> None``.
    """

    def __init__(
        self,
        initial: RuntimeState = RuntimeState.UNKNOWN,
        on_transition: Callable[[StateTransition], Any] | None = None,
    ) -> None:
        self._current: RuntimeState = initial
        self._history: list[StateTransition] = []
        self._on_transition = on_transition
        self._lock = asyncio.Lock()

    # ── Properties ─────────────────────────────────────────

    @property
    def current(self) -> RuntimeState:
        """The current state (read-only)."""
        return self._current

    @property
    def history(self) -> list[StateTransition]:
        """Ordered list of all transitions since creation or last reset."""
        return list(self._history)

    # ── Core operations ────────────────────────────────────

    def can_transition(self, new_state: RuntimeState) -> bool:
        """Check whether *new_state* is reachable from the current state.

        Non-mutating — does not perform the transition.
        """
        allowed = TRANSITIONS.get(self._current, set())
        return new_state in allowed

    async def transition(self, new_state: RuntimeState, reason: str = "") -> None:
        """Attempt a state transition.

        Validates against ``TRANSITIONS``, records the transition in history,
        logs at INFO level, and invokes the optional callback.

        Args:
            new_state: Target state.
            reason: Human-readable reason for the transition.

        Raises:
            IllegalStateTransitionError: If the transition is not allowed.
        """
        async with self._lock:
            old_state = self._current

            if not self.can_transition(new_state):
                raise IllegalStateTransitionError(old_state, new_state)

            now = time.time()
            record = StateTransition(
                from_state=old_state,
                to_state=new_state,
                timestamp=now,
                reason=reason,
                success=True,
            )

            self._current = new_state
            self._history.append(record)

            logger.info(
                "State: %s -> %s (%s)",
                old_state.value,
                new_state.value,
                reason or "no reason",
            )

        # Callback outside the lock to prevent deadlocks.
        if self._on_transition is not None:
            try:
                result = self._on_transition(record)
                import asyncio as _asyncio
                if _asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.exception("Transition callback failed")

    async def transition_safe(
        self, new_state: RuntimeState, reason: str = ""
    ) -> bool:
        """Attempt a transition, returning False instead of raising.

        Convenience wrapper for callers that prefer a boolean check
        over exception handling.

        Returns:
            True if the transition succeeded, False if illegal.
        """
        try:
            await self.transition(new_state, reason)
            return True
        except IllegalStateTransitionError:
            return False

    async def reset(
        self, initial_state: RuntimeState = RuntimeState.UNKNOWN
    ) -> None:
        """Reset the machine to *initial_state* and clear history.

        Thread-safe — acquires the lock.
        """
        async with self._lock:
            old = self._current
            self._current = initial_state
            self._history.clear()
            logger.info("State machine reset: %s -> %s", old.value, initial_state.value)

    # ── Convenience query helpers ──────────────────────────

    @property
    def allowed_targets(self) -> set[RuntimeState]:
        """Return the set of states reachable from the current state."""
        return TRANSITIONS.get(self._current, set())

    @property
    def is_terminal(self) -> bool:
        """True if the current state has no outgoing transitions except
        re-initialisation (SHUTDOWN, UNAVAILABLE)."""
        return self._current in (RuntimeState.SHUTDOWN, RuntimeState.UNAVAILABLE)

    @property
    def is_actionable(self) -> bool:
        """True if the engine is in a state where it can serve queries."""
        return self._current == RuntimeState.READY

    def last_transition(self) -> StateTransition | None:
        """Return the most recent transition, or None if no transitions yet."""
        return self._history[-1] if self._history else None


# ============================================================
#  Conversion helpers (SessionState / HealthStatus ↔ RuntimeState)
# ============================================================


def session_state_to_runtime(session: SessionState) -> RuntimeState | None:
    """Map a ``SessionState`` to the corresponding ``RuntimeState``.

    Returns None when there is no direct mapping (e.g. ``AUTHENTICATED``
    does not imply a specific runtime state — the runtime could be READY
    or DEGRADED for other reasons).
    """
    mapping: dict[SessionState, RuntimeState | None] = {
        SessionState.UNKNOWN: None,
        SessionState.AUTHENTICATED: None,  # Session OK, but runtime state depends on other factors
        SessionState.AUTH_EXPIRED: RuntimeState.LOGIN_REQUIRED,
        SessionState.REAUTH_IN_PROGRESS: RuntimeState.RECOVERING,
    }
    return mapping.get(session)


def runtime_state_to_health(state: RuntimeState) -> HealthStatus:
    """Map a ``RuntimeState`` to the corresponding ``HealthStatus``.

    This is a best-effort diagnostic mapping — HealthStatus is a
    *symptom* label while RuntimeState is a *control-flow* label.
    """
    mapping: dict[RuntimeState, HealthStatus] = {
        RuntimeState.UNKNOWN: HealthStatus.UNKNOWN,
        RuntimeState.INITIALIZING: HealthStatus.UNKNOWN,
        RuntimeState.PROFILE_LOADING: HealthStatus.UNKNOWN,
        RuntimeState.SESSION_CHECKING: HealthStatus.UNKNOWN,
        RuntimeState.READY: HealthStatus.HEALTHY,
        RuntimeState.DEGRADED: HealthStatus.DEGRADED,
        RuntimeState.LOGIN_REQUIRED: HealthStatus.UNHEALTHY,
        RuntimeState.RECOVERING: HealthStatus.DEGRADED,
        RuntimeState.UNAVAILABLE: HealthStatus.UNHEALTHY,
        RuntimeState.SHUTDOWN: HealthStatus.UNKNOWN,
    }
    return mapping.get(state, HealthStatus.UNKNOWN)
