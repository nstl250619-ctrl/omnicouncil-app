"""RecoveryEngine — orchestrated automatic recovery for AI platform runtimes.

Executes the recovery strategy chain (Reload → Renavigate → NewTab →
RestartBrowser) with per-strategy timeouts, attempt counting, and
EventBus integration.

Usage::

    engine_obj = ...  # AIRuntimeEngine instance
    recovery = RecoveryEngine(
        strategies=default_recovery_chain(),
        max_attempts=3,
        event_bus=bus,
    )
    success = await recovery.recover(engine_obj, "chatgpt")

State transitions during recovery::

    DEGRADED / LOGIN_REQUIRED / UNAVAILABLE
        → RECOVERING   (recovery starts)
        → READY        (strategy succeeded)
        → UNAVAILABLE  (all strategies exhausted)
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from engine.contracts import (
    RecoveryFailedError,
    RuntimeState,
)

if TYPE_CHECKING:
    from shared.event_bus import EventBus

logger = logging.getLogger(__name__)


@dataclass
class RecoveryAttempt:
    """Record of a single strategy attempt within a recovery round."""

    strategy_name: str
    platform: str
    started_at: float
    finished_at: float = 0.0
    success: bool = False
    error: str | None = None
    timed_out: bool = False


@dataclass
class RecoveryRound:
    """Record of a complete recovery round (one pass through the chain)."""

    platform: str
    round_number: int
    started_at: float
    finished_at: float = 0.0
    final_state: RuntimeState = RuntimeState.RECOVERING
    attempts: list[RecoveryAttempt] = field(default_factory=list)

    @property
    def succeeded(self) -> bool:
        return any(a.success for a in self.attempts)


class RecoveryEngine:
    """Orchestrates the recovery strategy chain.

    Parameters
    ----------
    strategies:
        Ordered list of ``RecoveryStrategy`` implementations.
        Each is tried in sequence until one succeeds.
    max_attempts:
        Maximum consecutive recovery rounds before giving up.
        Default 3 (configurable via ``PlatformConfig.max_recovery_attempts``).
    cooldown_s:
        Seconds to wait between recovery rounds.  Default 30.
    event_bus:
        Optional EventBus for emitting recovery events.
    """

    def __init__(
        self,
        strategies: list[Any] | None = None,
        max_attempts: int = 3,
        cooldown_s: int = 30,
        event_bus: EventBus | None = None,
    ) -> None:
        from runtime.recovery_strategies import default_recovery_chain

        self._strategies = strategies if strategies is not None else default_recovery_chain()
        self._max_attempts = max_attempts
        self._cooldown_s = cooldown_s
        self._event_bus = event_bus

        # Per-platform attempt counters
        self._attempt_counts: dict[str, int] = {}
        self._last_attempt_time: dict[str, float] = {}

        # History
        self._history: list[RecoveryRound] = []

    # ── Public API ─────────────────────────────────────────

    async def recover(self, engine: Any, platform: str) -> bool:
        """Execute the recovery chain for *platform*.

        Sets engine state to RECOVERING, tries each strategy in order,
        and transitions to READY on success or UNAVAILABLE on total
        failure.

        Args:
            engine: The ``AIRuntimeEngine`` instance.
            platform: Platform identifier.

        Returns:
            True if recovery succeeded.

        Raises:
            RecoveryFailedError: All strategies exhausted.
        """
        # Check attempt limit
        current_attempts = self._attempt_counts.get(platform, 0)
        if current_attempts >= self._max_attempts:
            logger.error(
                "%s: max recovery attempts (%d) reached",
                platform,
                self._max_attempts,
            )
            await self._emit_failure(engine, platform)
            raise RecoveryFailedError(platform, current_attempts)

        # Cooldown check
        last_time = self._last_attempt_time.get(platform, 0)
        elapsed = time.time() - last_time
        if elapsed < self._cooldown_s and last_time > 0:
            wait_time = self._cooldown_s - elapsed
            logger.info(
                "%s: recovery cooldown (%.0fs remaining)", platform, wait_time
            )
            await asyncio.sleep(wait_time)

        # Transition to RECOVERING
        state_machine = engine.state_machine
        if state_machine.can_transition(RuntimeState.RECOVERING):
            await state_machine.transition(
                RuntimeState.RECOVERING, reason="recovery started"
            )

        # Increment attempt counter
        self._attempt_counts[platform] = current_attempts + 1
        self._last_attempt_time[platform] = time.time()

        round_num = current_attempts + 1
        logger.info(
            "%s: recovery round %d/%d started",
            platform,
            round_num,
            self._max_attempts,
        )

        recovery_round = RecoveryRound(
            platform=platform,
            round_number=round_num,
            started_at=time.time(),
        )

        # Execute strategy chain
        for strategy in self._strategies:
            attempt = await self._try_strategy(engine, platform, strategy)
            recovery_round.attempts.append(attempt)

            if attempt.success:
                recovery_round.finished_at = time.time()
                recovery_round.final_state = RuntimeState.READY
                self._history.append(recovery_round)

                # Reset attempt counter on success
                self._attempt_counts[platform] = 0

                # Transition to READY
                if state_machine.can_transition(RuntimeState.READY):
                    await state_machine.transition(
                        RuntimeState.READY,
                        reason=f"recovery succeeded via {strategy.name}",
                    )

                await self._emit_event(
                    "recovery:succeeded",
                    platform=platform,
                    strategy=strategy.name,
                    round_number=round_num,
                )

                logger.info(
                    "%s: recovery succeeded via %s (round %d)",
                    platform,
                    strategy.name,
                    round_num,
                )
                return True

        # All strategies failed
        recovery_round.finished_at = time.time()
        recovery_round.final_state = RuntimeState.UNAVAILABLE
        self._history.append(recovery_round)

        logger.warning(
            "%s: all %d strategies failed (round %d/%d)",
            platform,
            len(self._strategies),
            round_num,
            self._max_attempts,
        )

        # Check if we've exhausted all attempts
        if self._attempt_counts[platform] >= self._max_attempts:
            await self._emit_failure(engine, platform)
            if state_machine.can_transition(RuntimeState.UNAVAILABLE):
                await state_machine.transition(
                    RuntimeState.UNAVAILABLE,
                    reason=f"all {self._max_attempts} recovery rounds failed",
                )
            raise RecoveryFailedError(platform, self._max_attempts)

        # Still have attempts left — transition back to DEGRADED
        if state_machine.can_transition(RuntimeState.DEGRADED):
            await state_machine.transition(
                RuntimeState.DEGRADED,
                reason=f"recovery round {round_num} failed, retrying",
            )

        return False

    def reset(self, platform: str | None = None) -> None:
        """Reset attempt counter for *platform* (or all if None)."""
        if platform is None:
            self._attempt_counts.clear()
            self._last_attempt_time.clear()
        else:
            self._attempt_counts.pop(platform, None)
            self._last_attempt_time.pop(platform, None)

    @property
    def history(self) -> list[RecoveryRound]:
        """All recovery rounds (copy)."""
        return list(self._history)

    def get_attempt_count(self, platform: str) -> int:
        """Return the current attempt count for *platform*."""
        return self._attempt_counts.get(platform, 0)

    # ── Internal ───────────────────────────────────────────

    async def _try_strategy(
        self, engine: Any, platform: str, strategy: Any
    ) -> RecoveryAttempt:
        """Execute a single strategy with timeout."""
        attempt = RecoveryAttempt(
            strategy_name=strategy.name,
            platform=platform,
            started_at=time.time(),
        )

        try:
            success = await asyncio.wait_for(
                strategy.recover(engine, platform),
                timeout=strategy.timeout_s,
            )
            attempt.success = success
            attempt.finished_at = time.time()

            if success:
                logger.info(
                    "%s: strategy %s succeeded (%.1fs)",
                    platform,
                    strategy.name,
                    attempt.finished_at - attempt.started_at,
                )
            else:
                logger.info(
                    "%s: strategy %s failed (%.1fs)",
                    platform,
                    strategy.name,
                    attempt.finished_at - attempt.started_at,
                )

        except TimeoutError:
            attempt.timed_out = True
            attempt.finished_at = time.time()
            attempt.error = f"timed out after {strategy.timeout_s}s"
            logger.warning(
                "%s: strategy %s timed out (%ds)",
                platform,
                strategy.name,
                strategy.timeout_s,
            )

        except Exception as exc:
            attempt.finished_at = time.time()
            attempt.error = str(exc)
            logger.debug(
                "%s: strategy %s error: %s", platform, strategy.name, exc
            )

        return attempt

    async def _emit_failure(self, engine: Any, platform: str) -> None:
        """Handle total recovery failure — emit events."""
        await self._emit_event(
            "recovery:failed",
            platform=platform,
            attempts=self._attempt_counts.get(platform, 0),
        )
        await self._emit_event(
            "ai:unavailable",
            platform=platform,
            reason="recovery_exhausted",
        )

    async def _emit_event(self, event: str, **kwargs: Any) -> None:
        """Emit an event if EventBus is available."""
        if self._event_bus is not None:
            try:
                await self._event_bus.emit(event, **kwargs)
            except Exception:
                logger.exception("RecoveryEngine: failed to emit %s", event)
