"""HealthMonitor — background heartbeat for all AI platform runtimes.

Implements the ``HealthMonitor`` protocol from ``engine.contracts``.

Runs a periodic loop that, for each registered platform:
    1. Checks browser/page liveness (``page.is_closed()``,
       ``navigator.onLine``).
    2. Calls ``SessionValidator.validate_offline()`` for a fast
       session probe.
    3. Updates ``RuntimeHealth`` snapshot.
    4. Emits events via ``EventBus`` when health state changes.

When session expiry or login requirement is detected, the monitor
emits ``"health:session_expired"`` so the RecoveryEngine can react.

Usage::

    monitor = HealthMonitor(event_bus=bus, interval_s=60)
    monitor.register("chatgpt", profile_dir, session_validator, get_page_fn)
    monitor.start()
    ...
    health = monitor.get_health("chatgpt")
    ...
    await monitor.stop()
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from engine.contracts import RuntimeHealth, RuntimeState
from shared.types import SessionState

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from runtime.session_validator import SessionValidator
    from shared.event_bus import EventBus

logger = logging.getLogger(__name__)


@dataclass
class _PlatformRegistration:
    """Internal registration for a monitored platform."""

    platform: str
    session_validator: SessionValidator
    get_page_fn: Callable[[], Any] | None = None  # Returns current Page or None


@dataclass
class _HealthSnapshot:
    """Mutable internal snapshot — converted to frozen RuntimeHealth on read."""

    platform: str
    state: RuntimeState = RuntimeState.UNKNOWN
    browser_alive: bool = False
    page_alive: bool = False
    session_valid: bool = False
    last_heartbeat: float = 0.0
    last_error: str | None = None
    recovery_attempts: int = 0
    uptime_seconds: float = 0.0
    start_time: float = field(default_factory=time.time)


class HealthMonitor:
    """Background health monitor for all registered platforms.

    Parameters
    ----------
    event_bus:
        EventBus for emitting health change events.  Optional — if
        None, events are silently skipped.
    interval_s:
        Heartbeat interval in seconds (default 60).
    on_session_expired:
        Optional async callback ``(platform: str) -> None`` invoked
        when session expiry is detected.  Used by RecoveryEngine.
    """

    def __init__(
        self,
        event_bus: EventBus | None = None,
        interval_s: int = 60,
        on_session_expired: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._interval_s = interval_s
        self._on_session_expired = on_session_expired

        self._registrations: dict[str, _PlatformRegistration] = {}
        self._snapshots: dict[str, _HealthSnapshot] = {}
        self._task: asyncio.Task[None] | None = None

    # ── Registration ───────────────────────────────────────

    def register(
        self,
        platform: str,
        session_validator: SessionValidator,
        get_page_fn: Callable[[], Any] | None = None,
    ) -> None:
        """Register a platform for monitoring.

        Args:
            platform: e.g. ``"chatgpt"``
            session_validator: Validator instance for this platform.
            get_page_fn: Callable returning the current Page (or None
                if no page is cached).  Used for liveness checks.
        """
        self._registrations[platform] = _PlatformRegistration(
            platform=platform,
            session_validator=session_validator,
            get_page_fn=get_page_fn,
        )
        self._snapshots[platform] = _HealthSnapshot(platform=platform)
        logger.info("HealthMonitor: registered %s", platform)

    def unregister(self, platform: str) -> None:
        """Stop monitoring a platform."""
        self._registrations.pop(platform, None)
        self._snapshots.pop(platform, None)

    # ── Lifecycle ──────────────────────────────────────────

    def start(self) -> None:
        """Start the background heartbeat loop."""
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run())
        logger.info("HealthMonitor started (interval=%ds)", self._interval_s)

    async def stop(self) -> None:
        """Cancel the heartbeat loop and await cleanup."""
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
            logger.info("HealthMonitor stopped")

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    # ── Health queries ─────────────────────────────────────

    def get_health(self, platform: str) -> RuntimeHealth:
        """Return the latest health snapshot for *platform*."""
        snap = self._snapshots.get(platform)
        if snap is None:
            return RuntimeHealth(
                platform=platform,
                state=RuntimeState.UNKNOWN,
                browser_alive=False,
                page_alive=False,
                session_valid=False,
            )
        return self._snapshot_to_health(snap)

    def get_all_health(self) -> dict[str, RuntimeHealth]:
        """Return health snapshots for all registered platforms."""
        return {
            platform: self._snapshot_to_health(snap)
            for platform, snap in self._snapshots.items()
        }

    # ── Heartbeat loop ─────────────────────────────────────

    async def _run(self) -> None:
        """Background loop — runs until cancelled."""
        # Initial delay to let engines boot
        await asyncio.sleep(min(5, self._interval_s))

        while True:
            try:
                await self._heartbeat_round()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("HealthMonitor: heartbeat round failed")

            await asyncio.sleep(self._interval_s)

    async def _heartbeat_round(self) -> None:
        """Run health checks on all registered platforms."""
        for platform, reg in self._registrations.items():
            try:
                await self._check_one(platform, reg)
            except Exception as exc:
                logger.warning("HealthMonitor: check failed for %s: %s", platform, exc)
                snap = self._snapshots.get(platform)
                if snap:
                    snap.last_error = str(exc)

    async def _check_one(self, platform: str, reg: _PlatformRegistration) -> None:
        """Run health check on a single platform."""
        snap = self._snapshots[platform]
        old_session_valid = snap.session_valid

        # 1. Browser/page liveness
        page = None
        if reg.get_page_fn is not None:
            try:
                page = reg.get_page_fn()
            except Exception:
                page = None

        snap.browser_alive = page is not None
        snap.page_alive = False

        if page is not None:
            try:
                snap.page_alive = not page.is_closed()
            except Exception:
                snap.page_alive = False

        # 2. Session validity (offline probe — fast)
        try:
            session_state = await reg.session_validator.validate_offline()
            snap.session_valid = session_state == SessionState.AUTHENTICATED
        except Exception as exc:
            logger.debug("HealthMonitor: session check failed for %s: %s", platform, exc)
            snap.session_valid = False

        # 3. Determine overall state
        if snap.browser_alive and snap.page_alive and snap.session_valid:
            snap.state = RuntimeState.READY
        elif snap.browser_alive and snap.page_alive and not snap.session_valid:
            snap.state = RuntimeState.LOGIN_REQUIRED
        elif snap.browser_alive and not snap.page_alive:
            snap.state = RuntimeState.DEGRADED
        else:
            snap.state = RuntimeState.UNAVAILABLE

        snap.last_heartbeat = time.time()
        snap.uptime_seconds = time.time() - snap.start_time
        snap.last_error = None

        # 4. Emit events on state changes
        if old_session_valid and not snap.session_valid:
            logger.warning("HealthMonitor: %s session EXPIRED", platform)
            await self._emit("health:session_expired", platform=platform)

            if self._on_session_expired is not None:
                try:
                    await self._on_session_expired(platform)
                except Exception:
                    logger.exception("HealthMonitor: on_session_expired callback failed")

        # 5. Log heartbeat
        logger.debug(
            "HealthMonitor: %s state=%s browser=%s page=%s session=%s",
            platform,
            snap.state.value,
            snap.browser_alive,
            snap.page_alive,
            snap.session_valid,
        )

    # ── Helpers ────────────────────────────────────────────

    @staticmethod
    def _snapshot_to_health(snap: _HealthSnapshot) -> RuntimeHealth:
        return RuntimeHealth(
            platform=snap.platform,
            state=snap.state,
            browser_alive=snap.browser_alive,
            page_alive=snap.page_alive,
            session_valid=snap.session_valid,
            last_heartbeat=snap.last_heartbeat,
            last_error=snap.last_error,
            recovery_attempts=snap.recovery_attempts,
            uptime_seconds=snap.uptime_seconds,
        )

    async def _emit(self, event: str, **kwargs: Any) -> None:
        """Emit an event if EventBus is available."""
        if self._event_bus is not None:
            try:
                await self._event_bus.emit(event, **kwargs)
            except Exception:
                logger.exception("HealthMonitor: failed to emit %s", event)
