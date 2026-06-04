"""CircuitBreaker — CLOSED → OPEN → HALF_OPEN state machine."""

from __future__ import annotations

import time
from typing import Callable

from shared.types import CircuitState


class CircuitBreaker:
    """Circuit breaker for an individual AI.

    States:
    - CLOSED: Normal operation, requests pass through
    - OPEN: Too many failures, requests rejected
    - HALF_OPEN: Testing recovery, limited requests allowed
    """

    def __init__(
        self,
        ai_id: str,
        failure_threshold: int = 5,
        cooldown_seconds: float = 300.0,
        on_state_change: Callable[[str, CircuitState, CircuitState], None] | None = None,
    ) -> None:
        self._ai_id = ai_id
        self._failure_threshold = failure_threshold
        self._cooldown_seconds = cooldown_seconds
        self._on_state_change = on_state_change

        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._last_failure_time = 0.0

    @property
    def state(self) -> CircuitState:
        return self._state

    def is_open(self) -> bool:
        """Pure check: is the circuit currently open? No side effects."""
        if self._state == CircuitState.OPEN:
            return True
        return False

    def should_allow(self) -> bool:
        """Check if a request should be allowed. May trigger HALF_OPEN transition."""
        if self._state == CircuitState.CLOSED:
            return True
        if self._state == CircuitState.HALF_OPEN:
            return True
        # OPEN state — check if cooldown passed
        if time.time() - self._last_failure_time >= self._cooldown_seconds:
            self._transition(CircuitState.HALF_OPEN)
            return True
        return False

    def record_success(self) -> None:
        """Record a successful request."""
        self._consecutive_failures = 0
        if self._state == CircuitState.HALF_OPEN:
            self._transition(CircuitState.CLOSED)

    def record_failure(self) -> None:
        """Record a failed request."""
        self._consecutive_failures += 1
        self._last_failure_time = time.time()

        if self._state == CircuitState.HALF_OPEN:
            self._transition(CircuitState.OPEN)
        elif self._consecutive_failures >= self._failure_threshold:
            self._transition(CircuitState.OPEN)

    def _transition(self, new_state: CircuitState) -> None:
        """Transition to a new state."""
        old = self._state
        self._state = new_state
        if self._on_state_change and old != new_state:
            self._on_state_change(self._ai_id, old, new_state)

    def reset(self) -> None:
        """Reset to CLOSED state."""
        self._consecutive_failures = 0
        self._state = CircuitState.CLOSED
