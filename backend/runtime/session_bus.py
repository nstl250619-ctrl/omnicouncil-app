"""SessionStateBus — per-Provider login state event bus.

Solves: when one instance completes login, other instances know immediately.
Location: RuntimeRegistry layer, not AuthManager layer.

Usage:
    bus = SessionStateBus()
    bus.subscribe("deepseek", my_callback)
    await bus.emit("deepseek", LifecycleState.VALID)
    await bus.wait_for_login("deepseek", timeout_s=300)
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from auth.session_lifecycle import LifecycleState

logger = logging.getLogger(__name__)


class SessionStateBus:
    """Per-provider login state event bus.

    Allows multiple AIRuntimeEngine instances sharing the same provider
    to synchronize login state changes without polling.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callable[[str, str], None]]] = {}
        self._waiters: dict[str, list[asyncio.Event]] = {}
        self._last_state: dict[str, str] = {}

    def subscribe(self, platform: str, callback: Callable[[str, str], None]) -> None:
        """Subscribe to platform login state changes."""
        if platform not in self._subscribers:
            self._subscribers[platform] = []
        self._subscribers[platform].append(callback)
        logger.debug("SessionStateBus: subscribed to %s", platform)

    def unsubscribe(self, platform: str, callback: Callable[[str, str], None]) -> None:
        """Unsubscribe from platform login state changes."""
        if platform in self._subscribers:
            self._subscribers[platform] = [
                cb for cb in self._subscribers[platform] if cb is not callback
            ]

    async def emit(self, platform: str, state: str) -> None:
        """Broadcast platform login state change."""
        self._last_state[platform] = state
        logger.info("SessionStateBus: %s → %s", platform, state)

        # Notify subscribers
        for callback in self._subscribers.get(platform, []):
            try:
                callback(platform, state)
            except Exception:
                logger.exception("SessionStateBus: callback failed for %s", platform)

        # Wake up waiters
        if state in ("valid", "authenticated"):
            for event in self._waiters.get(platform, []):
                event.set()
            self._waiters[platform] = []

    async def wait_for_login(self, platform: str, timeout_s: float = 300) -> bool:
        """Wait for platform to reach VALID state.

        Returns True if login completed, False on timeout.
        """
        # Check if already valid
        if self._last_state.get(platform) in ("valid", "authenticated"):
            return True

        event = asyncio.Event()
        if platform not in self._waiters:
            self._waiters[platform] = []
        self._waiters[platform].append(event)

        try:
            await asyncio.wait_for(event.wait(), timeout=timeout_s)
            return True
        except asyncio.TimeoutError:
            return False
        finally:
            # Clean up
            if platform in self._waiters:
                self._waiters[platform] = [
                    e for e in self._waiters[platform] if e is not event
                ]

    def get_last_state(self, platform: str) -> str | None:
        """Get last known state for platform."""
        return self._last_state.get(platform)
