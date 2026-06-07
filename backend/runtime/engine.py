"""AIRuntimeEngine — concrete implementation of the Runtime Engine.

Integrates all components from phases 2-5 into a single cohesive engine:

    - ``RuntimeStateMachine``  — 10-state lifecycle (phase 2)
    - ``ProfileManager``       — profile backup/restore (phase 3)
    - ``SessionValidator``     — offline + online checks (phase 4)
    - ``HealthMonitor``        — background heartbeat (phase 4)
    - ``RecoveryEngine``       — 4-level strategy chain (phase 5)

This is the **only** class that the Scheduler and AIAccessManager
interact with.  All browser, profile, session, and recovery complexity
is hidden behind ``ensure_ready()`` and ``get_page()``.

Usage::

    config = PlatformConfig(name="deepseek", home_url="https://chat.deepseek.com")
    engine = AIRuntimeEngine(config)
    await engine.boot()        # cold start
    page = engine.get_page()   # only valid when READY

    # or, idempotently:
    state = await engine.ensure_ready()
    page = engine.get_page()
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from pathlib import Path
from typing import Any

from engine.contracts import (
    AIRuntimeEngine as AIRuntimeEngineABC,
)
from engine.contracts import (
    HealthMonitor as HealthMonitorProtocol,
)
from engine.contracts import (
    PlatformConfig,
    RecoveryFailedError,
    RuntimeHealth,
    RuntimeNotReadyError,
    RuntimeState,
    StateTransition,
)
from engine.contracts import (
    ProfileManager as ProfileManagerABC,
)
from engine.contracts import (
    SessionValidator as SessionValidatorProtocol,
)
from runtime.health_monitor import HealthMonitor
from runtime.profile_manager import ProfileManager
from runtime.recovery_engine import RecoveryEngine
from runtime.recovery_strategies import default_recovery_chain
from runtime.session_validator import SessionValidator
from runtime.state_machine import RuntimeStateMachine

logger = logging.getLogger(__name__)

# Default page eviction thresholds (from EmbeddedEngine)
_MAX_PAGE_AGE_S = 600       # 10 minutes
_MAX_PAGE_IDLE_S = 120      # 2 minutes
_WATCHDOG_INTERVAL_S = 30   # ChatGPT visible window check


class AIRuntimeEngine(AIRuntimeEngineABC):
    """Concrete ``AIRuntimeEngine`` backed by Playwright + patchright.

    Parameters
    ----------
    config:
        Platform-specific configuration.
    profile_manager:
        Optional override for the profile manager.  If None, a
        default ``ProfileManager`` is created.
    session_validator:
        Optional override.  If None, a default ``SessionValidator``
        is created from the config.
    health_monitor:
        Optional override.  If None, a default ``HealthMonitor`` is
        created.
    recovery_engine:
        Optional override.  If None, a default ``RecoveryEngine`` is
        created with the standard 4-level chain.
    """

    def __init__(
        self,
        config: PlatformConfig,
        profile_manager: ProfileManagerABC | None = None,
        session_validator: SessionValidatorProtocol | None = None,
        health_monitor: HealthMonitorProtocol | None = None,
        recovery_engine: RecoveryEngine | None = None,
    ) -> None:
        self._config = config
        self._platform = config.name

        # State machine
        self._state_machine = RuntimeStateMachine(
            initial=RuntimeState.UNKNOWN,
            on_transition=self._on_state_change,
        )

        # Profile manager
        self._profile_manager = profile_manager or ProfileManager(
            auth_dir=config.profile_dir and Path(config.profile_dir).parent or None,
        )

        # Session validator
        self._session_validator = session_validator or SessionValidator(
            profile_dir=self._profile_manager.get_profile_path(self._platform).parent,
            platform=self._platform,
            mode=config.session_check_mode,
            home_url=config.home_url,
        )

        # Health monitor
        self._health_monitor = health_monitor or HealthMonitor(
            interval_s=config.heartbeat_interval_s,
            on_session_expired=self._on_session_expired,
        )

        # Recovery engine
        self._recovery_engine = recovery_engine or RecoveryEngine(
            strategies=default_recovery_chain(),
            max_attempts=config.max_recovery_attempts,
            cooldown_s=config.recovery_cooldown_s,
        )

        # Browser state
        self._playwright: Any = None
        self._context: Any = None
        self._page: Any = None
        self._page_created_at: float = 0.0
        self._page_last_used: float = 0.0

        # Watchdog task (ChatGPT visible window)
        self._watchdog_task: asyncio.Task[None] | None = None

    # ── Properties (from ABC) ──────────────────────────────

    @property
    def state(self) -> RuntimeState:
        return self._state_machine.current

    @property
    def platform(self) -> str:
        return self._platform

    @property
    def state_history(self) -> list[StateTransition]:
        return self._state_machine.history

    @property
    def is_connected(self) -> bool:
        return self._playwright is not None and self._context is not None

    # ── Sub-component access ───────────────────────────────

    def get_profile_manager(self) -> ProfileManagerABC:
        return self._profile_manager

    def get_session_validator(self) -> SessionValidatorProtocol:
        return self._session_validator

    def get_health_monitor(self) -> HealthMonitorProtocol:
        return self._health_monitor

    def get_platform_config(self) -> PlatformConfig:
        """Return the platform config (used by recovery strategies)."""
        return self._config

    @property
    def state_machine(self) -> RuntimeStateMachine:
        """Expose state machine for recovery engine transitions."""
        return self._state_machine

    # ── Lifecycle: boot ────────────────────────────────────

    async def boot(self) -> RuntimeState:
        """Cold-start the engine.

        UNKNOWN → INITIALIZING → PROFILE_LOADING → SESSION_CHECKING → READY

        On failure at any phase, transitions to UNAVAILABLE.
        """
        if self.state not in (RuntimeState.UNKNOWN, RuntimeState.SHUTDOWN, RuntimeState.UNAVAILABLE):
            logger.warning("boot() called in state %s — ignoring", self.state.value)
            return self.state

        try:
            # Phase 1: Initialize browser
            await self._state_machine.transition(
                RuntimeState.INITIALIZING, reason="launching browser"
            )
            await self._launch_browser()

            # Phase 2: Load profile
            await self._state_machine.transition(
                RuntimeState.PROFILE_LOADING, reason="loading profile"
            )
            await self._profile_manager.create(self._platform)

            # Phase 3: Check session
            await self._state_machine.transition(
                RuntimeState.SESSION_CHECKING, reason="checking session"
            )
            session_state = await self._session_validator.validate(self._page)

            from shared.types import SessionState

            if session_state == SessionState.AUTHENTICATED:
                await self._state_machine.transition(
                    RuntimeState.READY, reason="session valid"
                )
                # Start health monitor
                self._health_monitor.register(
                    self._platform,
                    self._session_validator,
                    get_page_fn=lambda: self._page,
                )
                self._health_monitor.start()
                # Start watchdog for visible windows (ChatGPT)
                if not self._config.headless:
                    self._start_watchdog()
            else:
                await self._state_machine.transition(
                    RuntimeState.LOGIN_REQUIRED,
                    reason=f"session state: {session_state.value}",
                )

        except Exception as exc:
            logger.exception("boot() failed for %s", self._platform)
            if self._state_machine.can_transition(RuntimeState.UNAVAILABLE):
                await self._state_machine.transition(
                    RuntimeState.UNAVAILABLE, reason=f"boot failed: {exc}"
                )
            raise

        return self.state

    # ── Lifecycle: shutdown ────────────────────────────────

    async def shutdown(self) -> None:
        """Gracefully shut down: stop heartbeat, close browser, → SHUTDOWN."""
        if self.state == RuntimeState.SHUTDOWN:
            return

        # Stop watchdog
        if self._watchdog_task is not None:
            self._watchdog_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._watchdog_task
            self._watchdog_task = None

        # Stop health monitor
        await self._health_monitor.stop()

        # Close browser
        await self._close_browser()

        # Transition
        if self._state_machine.can_transition(RuntimeState.SHUTDOWN):
            await self._state_machine.transition(
                RuntimeState.SHUTDOWN, reason="user requested"
            )

    # ── Core: ensure_ready ─────────────────────────────────

    async def ensure_ready(self) -> RuntimeState:
        """Idempotent entry point — blocks until READY or raises."""
        current = self.state

        if current == RuntimeState.READY:
            return current

        if current in (RuntimeState.UNKNOWN, RuntimeState.SHUTDOWN):
            return await self.boot()

        if current in (
            RuntimeState.DEGRADED,
            RuntimeState.LOGIN_REQUIRED,
            RuntimeState.UNAVAILABLE,
        ):
            try:
                success = await self.attempt_recovery()
                if success:
                    return self.state
            except RecoveryFailedError:
                # Recovery exhausted — try a full boot as last resort
                logger.info("Recovery exhausted, attempting full boot")
                return await self.boot()

        # If recovery left us in a non-READY state, try boot
        if self.state != RuntimeState.READY:
            return await self.boot()

        raise RuntimeError(
            f"ensure_ready() cannot handle state {current.value}"
        )

    # ── Core: get_page ─────────────────────────────────────

    def get_page(self) -> Any:
        """Return the cached Playwright Page (only when READY)."""
        if self.state != RuntimeState.READY:
            raise RuntimeNotReadyError(self.state)

        if self._page is None or self._page.is_closed():
            raise RuntimeNotReadyError(self.state)

        self._page_last_used = time.time()
        return self._page

    # ── Core: check_health ─────────────────────────────────

    async def check_health(self) -> RuntimeHealth:
        """Run a full health check (does NOT trigger recovery)."""
        browser_alive = self._playwright is not None and self._context is not None
        page_alive = False
        session_valid = False

        if self._page is not None:
            try:
                page_alive = not self._page.is_closed()
            except Exception:
                page_alive = False

        if page_alive:
            try:
                from shared.types import SessionState
                session_state = await self._session_validator.validate_offline()
                session_valid = session_state == SessionState.AUTHENTICATED
            except Exception:
                session_valid = False

        return RuntimeHealth(
            platform=self._platform,
            state=self.state,
            browser_alive=browser_alive,
            page_alive=page_alive,
            session_valid=session_valid,
            last_heartbeat=time.time(),
            uptime_seconds=time.time() - (self._page_created_at or time.time()),
        )

    # ── Core: attempt_recovery ─────────────────────────────

    async def attempt_recovery(self) -> bool:
        """Execute the recovery strategy chain."""
        try:
            return await self._recovery_engine.recover(self, self._platform)
        except RecoveryFailedError:
            raise

    # ── Browser lifecycle ──────────────────────────────────

    async def _launch_browser(self) -> None:
        """Launch Playwright + persistent context."""
        from patchright.async_api import async_playwright

        self._playwright = await async_playwright().start()

        profile_path = self._profile_manager.get_profile_path(self._platform)
        profile_path.mkdir(parents=True, exist_ok=True)

        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-features=IsolateOrigins,site-per-process",
            *self._config.extra_browser_args,
        ]

        self._context = await self._playwright.chromium.launch_persistent_context(
            str(profile_path),
            headless=self._config.headless,
            args=launch_args,
        )

        # Create initial page and navigate
        self._page = await self._context.new_page()
        await self._page.goto(
            self._config.home_url,
            wait_until="domcontentloaded",
            timeout=30000,
        )
        await self._page.wait_for_timeout(2000)

        self._page_created_at = time.time()
        self._page_last_used = time.time()

        logger.info(
            "%s: browser launched (headless=%s)", self._platform, self._config.headless
        )

    async def _close_browser(self) -> None:
        """Close browser context and playwright."""
        if self._page is not None:
            with contextlib.suppress(Exception):
                await self._page.close()
            self._page = None

        if self._context is not None:
            with contextlib.suppress(Exception):
                await self._context.close()
            self._context = None

        if self._playwright is not None:
            with contextlib.suppress(Exception):
                await self._playwright.stop()
            self._playwright = None

        logger.info("%s: browser closed", self._platform)

    # ── Page management (from EmbeddedEngine) ──────────────

    def _evict_stale_pages(self) -> int:
        """Evict cached page if too old or idle."""
        if self._page is None:
            return 0

        now = time.time()
        age = now - self._page_created_at
        idle = now - self._page_last_used

        if age > _MAX_PAGE_AGE_S or (idle > _MAX_PAGE_IDLE_S and self._page_last_used > 0):
            logger.info(
                "%s: evicting stale page (age=%.0fs, idle=%.0fs)",
                self._platform, age, idle,
            )
            asyncio.ensure_future(self._evict_page())
            return 1
        return 0

    async def _evict_page(self) -> None:
        """Close and clear the cached page."""
        if self._page is not None:
            with contextlib.suppress(Exception):
                await self._page.close()
            self._page = None
        self._page_created_at = 0.0
        self._page_last_used = 0.0

    # ── Watchdog (ChatGPT visible window) ──────────────────

    def _start_watchdog(self) -> None:
        """Start the visible-window watchdog for non-headless platforms."""
        if self._watchdog_task is not None:
            return
        self._watchdog_task = asyncio.create_task(self._watchdog_loop())
        logger.info("%s: visible-window watchdog started", self._platform)

    async def _watchdog_loop(self) -> None:
        """Periodically check that visible browser windows are still alive."""
        while True:
            await asyncio.sleep(_WATCHDOG_INTERVAL_S)
            try:
                if self._context is None:
                    continue
                pages = self._context.pages
                if not pages:
                    logger.warning(
                        "%s: watchdog detected no pages, triggering recovery",
                        self._platform,
                    )
                    await self._evict_page()
                    # Trigger recovery via health monitor callback
                    await self._on_session_expired(self._platform)
            except Exception as exc:
                logger.warning(
                    "%s: watchdog error (%s), triggering recovery",
                    self._platform, exc,
                )
                await self._evict_page()
                await self._on_session_expired(self._platform)

    # ── Callbacks ──────────────────────────────────────────

    async def _on_state_change(self, record: StateTransition) -> None:
        """Callback for state machine transitions."""
        logger.info(
            "%s: state %s -> %s (%s)",
            self._platform,
            record.from_state.value,
            record.to_state.value,
            record.reason,
        )

    async def _on_session_expired(self, platform: str) -> None:
        """Callback from HealthMonitor when session expires."""
        logger.info("%s: session expired callback — attempting recovery", platform)
        try:
            await self.attempt_recovery()
        except RecoveryFailedError:
            logger.error("%s: auto-recovery after session expiry failed", platform)
        except Exception:
            logger.exception("%s: unexpected error in session expiry recovery", platform)
