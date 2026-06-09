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
    PageBusyError,
    PageBusyState,
    PlatformConfig,
    RecoveryFailedError,
    RuntimeHealth,
    RuntimeMetrics,
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

        # Auth manager (from config.auth)
        from auth.auth_manager import AuthManager
        self._auth_manager = AuthManager(config.auth)

        # Session validator (with AuthManager injection)
        self._session_validator = session_validator or SessionValidator(
            profile_dir=self._profile_manager.get_profile_path(self._platform).parent,
            platform=self._platform,
            mode=config.session_check_mode,
            home_url=config.home_url,
            auth_manager=self._auth_manager,
        )

        # Session lifecycle + recovery (only if auth config exists)
        self._session_lifecycle = None
        self._session_bus = None
        self._login_recovery = None
        if config.auth is not None:
            from auth.login_recovery import LoginRecoveryHandler
            from auth.session_lifecycle import SessionLifecycle
            from runtime.session_bus import SessionStateBus

            self._session_bus = SessionStateBus()
            self._login_recovery = LoginRecoveryHandler(
                platform=self._platform,
                auth_manager=self._auth_manager,
                session_bus=self._session_bus,
            )
            self._session_lifecycle = SessionLifecycle(
                platform=self._platform,
                auth_manager=self._auth_manager,
                check_interval_s=config.heartbeat_interval_s,
                login_recovery=self._login_recovery,
                session_bus=self._session_bus,
            )
            # Subscribe to login success from other instances
            self._session_bus.subscribe(self._platform, self._on_session_state_change)

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

        # === Page Lease / Concurrency control (Phase 3-5 remediation) ===
        # P1-3: extracted to PageGuard — single source of truth for
        # lease lock / recovery flag / pending-evict flag / ref count.
        from runtime.page_guard import PageGuard
        self._guard: PageGuard = PageGuard(
            platform=self._platform,
            metrics=None,  # set below, after RuntimeMetrics is created
        )
        self._evict_task: asyncio.Task[None] | None = None

        # Per-platform metrics (exposed via /metrics/runtime)
        self._metrics: RuntimeMetrics = RuntimeMetrics(platform=self._platform)
        # Back-fill the guard with the now-constructed metrics object
        self._guard._metrics = self._metrics

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

            # Always register and start health monitor (even if not authenticated)
            # so the platform is tracked regardless of session state.
            self._health_monitor.register(
                self._platform,
                self._session_validator,
                get_page_fn=lambda: self._page,
            )
            self._health_monitor.start()

            if session_state == SessionState.AUTHENTICATED:
                await self._state_machine.transition(
                    RuntimeState.READY, reason="session valid"
                )
                # Start watchdog for visible windows (ChatGPT)
                if not self._config.headless:
                    self._start_watchdog()
                # Start session lifecycle probe (if auth configured)
                if self._session_lifecycle is not None:
                    profile_dir = str(self._profile_manager.get_profile_path(self._platform).parent)
                    self._session_lifecycle.start(self._page, profile_dir)
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

        # Stop session lifecycle
        if self._session_lifecycle is not None:
            await self._session_lifecycle.stop()

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
        """Return the cached Playwright Page.

        Allowed states: READY, RECOVERING (recovery strategies need
        page access to perform reload/goto/close).

        .. deprecated::
            Prefer :meth:`acquire_page` — it is the only safe way to use
            the page in V2.  Direct ``get_page()`` calls bypass the lease
            and will race with eviction / recovery.
        """
        if self.state not in (RuntimeState.READY, RuntimeState.RECOVERING):
            raise RuntimeNotReadyError(self.state)

        if self._page is None or self._page.is_closed():
            raise RuntimeNotReadyError(self.state)

        self._page_last_used = time.time()
        return self._page

    # ── Core: acquire_page (Page Lease) ─────────────────────

    @contextlib.asynccontextmanager
    async def acquire_page(
        self, *, timeout: float = 30.0
    ):
        """Lease the page to a single query (async context manager).

        Phase 7 P1-3: guard logic delegated to ``PageGuard`` so the
        same state machine powers ``acquire_page()`` and
        ``RecoveryEngine.recover()``.
        """
        if self.state != RuntimeState.READY:
            self._metrics.page_busy_rejections += 1
            raise RuntimeNotReadyError(self.state)

        # Block queries during session recovery
        if self._session_lifecycle is not None:
            from auth.session_lifecycle import LifecycleState
            if self._session_lifecycle.state in (
                LifecycleState.RECOVERY_PENDING,
                LifecycleState.RECOVERY_IN_PROGRESS,
                LifecycleState.LOGIN_REQUIRED,
            ):
                self._metrics.page_busy_rejections += 1
                raise RuntimeNotReadyError(self.state)

        # P0-2: opportunistic eviction — check both time-based and liveness
        try:
            # Check if page is closed/crashed (not just stale)
            if self._page is not None:
                try:
                    if self._page.is_closed():
                        logger.info("%s: page closed externally, triggering eviction", self._platform)
                        self._guard.mark_evict()
                        if self._evict_task is None or self._evict_task.done():
                            self._evict_task = asyncio.create_task(self._evict_page())
                except Exception:
                    logger.info("%s: page liveness check failed, triggering eviction", self._platform)
                    self._guard.mark_evict()
                    if self._evict_task is None or self._evict_task.done():
                        self._evict_task = asyncio.create_task(self._evict_page())

            self._evict_stale_pages()
            if self._guard.is_pending_evict and self._evict_task is not None:
                try:
                    await asyncio.wait_for(self._evict_task, timeout=timeout)
                except asyncio.TimeoutError:
                    self._metrics.page_busy_rejections += 1
                    raise PageBusyError(
                        self._platform,
                        f"eviction did not complete within {timeout:.1f}s",
                    )
        except PageBusyError:
            raise
        except Exception as exc:
            logger.warning("%s: opportunistic eviction failed: %s",
                           self._platform, exc)

        # After eviction, self._page is None.  If we're still in
        # READY state, re-create the page before handing it out.
        if self._page is None and self.state == RuntimeState.READY:
            try:
                await self._recreate_page()
            except Exception as exc:
                self._metrics.page_busy_rejections += 1
                raise PageBusyError(
                    self._platform,
                    f"page recreation after eviction failed: {exc}",
                ) from exc

        if self._page is None:
            self._metrics.page_busy_rejections += 1
            raise RuntimeNotReadyError(self.state)

        page_to_lease = self._page

        # P1-3: actual lease acquisition is in PageGuard
        async with self._guard.lease(timeout=timeout):
            self._page_last_used = time.time()
            try:
                yield page_to_lease
            finally:
                pass  # lease() context manager handles metrics/state

    # ── Core: metrics ──────────────────────────────────────

    def metrics(self) -> RuntimeMetrics:
        """Return this engine's mutable metrics counters."""
        return self._metrics

    @property
    def page_state(self) -> PageBusyState:
        """Current sub-state of the page lease (P1-3: delegates to guard)."""
        return self._guard.state

    @property
    def query_ref_count(self) -> int:
        """Number of queries currently holding the page lease."""
        return self._guard.query_ref_count

    @property
    def recovery_in_progress(self) -> bool:
        """True while a recovery round is running."""
        return self._guard.recovery_in_progress

    # ── Recovery guard (public API for RecoveryEngine) ─────

    async def guard_recovery(self, *, timeout: float = 5.0) -> None:
        """Wait for idle page + mark recovery in progress.

        Public API for ``RecoveryEngine`` — replaces private
        ``_guard`` access.  Raises ``RecoveryBusyError`` if the
        page is still leased after *timeout* seconds.
        """
        await self._guard.guard_recovery(timeout=timeout)

    def clear_recovery(self, *, succeeded: bool = True) -> None:
        """Clear the recovery flag.

        Public API for ``RecoveryEngine`` — replaces private
        ``_guard`` access.
        """
        self._guard.clear_recovery(succeeded=succeeded)

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

    # ── Session state bus callback ──────────────────────────

    def _on_session_state_change(self, platform: str, state: str) -> None:
        """Callback from SessionStateBus when another instance logs in."""
        if platform != self._platform:
            return
        if state in ("valid", "authenticated"):
            logger.info("%s: login detected from another instance, notifying lifecycle", platform)
            if self._session_lifecycle is not None:
                self._session_lifecycle.notify_login_success()

    # ── Core: attempt_recovery ─────────────────────────────

    async def attempt_recovery(self) -> bool:
        """Execute the recovery strategy chain."""
        try:
            return await self._recovery_engine.recover(self, self._platform)
        except RecoveryFailedError:
            raise

    # ── Core: manual login ─────────────────────────────────

    async def login(self, timeout_s: int = 300) -> tuple[bool, str]:
        """Open a visible browser for manual login.

        Launches a non-headless browser, navigates to the platform's
        home URL, and waits for the user to complete login.  After
        the user closes the browser or timeout is reached, checks
        session validity.

        Returns:
            (success, error_message)
        """
        import os
        from patchright.async_api import async_playwright

        profile_path = self._profile_manager.get_profile_path(self._platform)
        profile_path.mkdir(parents=True, exist_ok=True)

        # Use the real display (:0) instead of Xvfb (:99)
        # so the browser window is visible to the user
        original_display = os.environ.get("DISPLAY")
        os.environ["DISPLAY"] = ":0"

        playwright = None
        browser = None
        try:
            playwright = await async_playwright().start()
            browser = await playwright.chromium.launch_persistent_context(
                str(profile_path),
                headless=False,
                no_viewport=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                ],
            )

            page = browser.pages[0] if browser.pages else await browser.new_page()
            await page.goto(
                self._config.home_url,
                wait_until="commit",
                timeout=45000,
            )

            # Wait for user to close the browser or timeout
            page_closed = asyncio.Event()

            def on_page_close(*args):
                page_closed.set()

            page.on("close", on_page_close)

            try:
                await asyncio.wait_for(page_closed.wait(), timeout=timeout_s)
            except asyncio.TimeoutError:
                return False, "登录超时"

            # Save storage state
            auth_json = profile_path.parent / f"{self._platform}.json"
            try:
                await browser.storage_state(path=str(auth_json))
            except Exception:
                pass

            # Wait for cookies to flush
            await asyncio.sleep(2)

            # Check session
            session_state = await self._session_validator.validate_offline()
            from shared.types import SessionState
            if session_state == SessionState.AUTHENTICATED:
                # Notify SessionStateBus so other instances know
                if self._session_bus is not None:
                    await self._session_bus.emit(self._platform, "valid")
                return True, ""

            # Retry once
            await asyncio.sleep(3)
            session_state = await self._session_validator.validate_offline()
            if session_state == SessionState.AUTHENTICATED:
                if self._session_bus is not None:
                    await self._session_bus.emit(self._platform, "valid")
                return True, ""

            return False, "未检测到登录状态"

        except Exception as e:
            return False, str(e)
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass
            # Restore original DISPLAY
            if original_display is not None:
                os.environ["DISPLAY"] = original_display

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

        # Defensive: non-headless platforms (currently just chatgpt) get the
        # full set of hide-window args merged in even if the platform config
        # lost them. Key= / value flags are deduped by exact prefix. This
        # mirrors the defensive block in recovery_strategies.py so both the
        # initial launch AND a watchdog-driven restart stay invisible.
        if not self._config.headless:
            home_url = self._config.home_url or "about:blank"
            forced_args = [
                "--window-position=-32000,-32000",
                "--window-size=1,1",
                f"--app={home_url}",
                "--no-startup-window",
                "--disable-notifications",
                "--disable-infobars",
            ]
            for arg in forced_args:
                if not any(
                    a.split("=")[0] == arg.split("=")[0] for a in launch_args
                ):
                    launch_args.append(arg)

        self._context = await self._playwright.chromium.launch_persistent_context(
            str(profile_path),
            headless=self._config.headless,
            args=launch_args,
        )

        # Create initial page and navigate
        self._page = await self._context.new_page()

        # For non-headless platforms (chatgpt), tag the window title with
        # [background] so the user can tell at a glance that any visible
        # window is OmniCouncil-managed. Same MutationObserver strategy as
        # RestartBrowserStrategy — survives SPA title rewrites.
        if not self._config.headless:
            try:
                await self._page.add_init_script(
                    """
                    (() => {
                        const tag = '[background] ';
                        const apply = () => {
                            try {
                                if (
                                    document.title &&
                                    !document.title.startsWith(tag)
                                ) {
                                    document.title = tag + document.title;
                                }
                            } catch (_) {}
                        };
                        const installObserver = () => {
                            const head = document.head || document.documentElement;
                            if (!head || head.__bgObserved) return;
                            head.__bgObserved = true;
                            const obs = new MutationObserver(apply);
                            obs.observe(head, {
                                childList: true,
                                subtree: true,
                                characterData: true,
                            });
                            apply();
                        };
                        if (document.readyState === 'loading') {
                            document.addEventListener(
                                'DOMContentLoaded',
                                installObserver,
                                { once: true },
                            );
                        } else {
                            installObserver();
                        }
                    })();
                    """
                )
            except Exception as exc:
                logger.debug(
                    "%s: failed to install [background] title tag (%s)",
                    self._platform, exc,
                )

        await self._page.goto(
            self._config.home_url,
            wait_until="domcontentloaded",
            timeout=30000,
        )
        await self._page.wait_for_timeout(2000)

        self._page_created_at = time.time()
        self._page_last_used = time.time()
        self._metrics.page_created += 1

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

    async def _recreate_page(self) -> None:
        """Create a fresh Page after an eviction (Phase 7 P0-2).

        Reuses the existing ``_context`` if alive; otherwise launches
        a new browser.  Bumps ``page_created`` metric.
        """
        if self._context is None:
            await self._launch_browser()
            return
        self._page = await self._context.new_page()
        await self._page.goto(
            self._config.home_url,
            wait_until="domcontentloaded",
            timeout=30000,
        )
        await self._page.wait_for_timeout(2000)
        self._page_created_at = time.time()
        self._page_last_used = time.time()
        self._metrics.page_created += 1
        logger.info("%s: page recreated", self._platform)

    # ── Page management (from EmbeddedEngine) ──────────────

    def _evict_stale_pages(self) -> int:
        """Evict cached page if too old or idle.

        V2 contract: this method NEVER returns a page that is about to
        be evicted.  The eviction is scheduled as a tracked task and
        the ``_pending_evict`` flag is raised *before* scheduling, so
        any new ``acquire_page()`` call is rejected until the eviction
        completes.  This closes the historical race where
        ``get_page()`` returned a page reference that was about to be
        torn down by ``asyncio.ensure_future``.
        """
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
            # P1-3: mark eviction via guard (single source of truth)
            self._guard.mark_evict()
            if self._evict_task is None or self._evict_task.done():
                self._evict_task = asyncio.create_task(self._evict_page())
            return 1
        return 0

    async def _evict_page(self) -> None:
        """Close and clear the cached page (synchronous w.r.t. the caller).

        P1-3: lease / state management goes through ``PageGuard``.
        """
        # Mark eviction start (idempotent — guard prevents double-count)
        self._guard.mark_evict()
        try:
            # If a query is still using the page, wait for it to release
            if self._guard.is_leased:
                await self._guard.wait_until_idle(timeout=5.0)
            if self._page is not None:
                with contextlib.suppress(Exception):
                    await self._page.close()
                self._page = None
            self._page_created_at = 0.0
            self._page_last_used = 0.0
            self._metrics.page_destroyed += 1
        finally:
            # P1-3: clear via guard
            self._guard.clear_evict()

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
