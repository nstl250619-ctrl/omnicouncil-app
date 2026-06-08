"""SessionManager — DEPRECATED: use runtime.health_monitor.HealthMonitor instead.

.. deprecated::
    This module is superseded by ``runtime.health_monitor.HealthMonitor``
    which unifies heartbeat, session validation, and health reporting.
    It will be removed in a future version.
"""

from __future__ import annotations

import asyncio

import logging
from typing import TYPE_CHECKING

from shared.types import SessionState

if TYPE_CHECKING:
    from browser.engine import BrowserEngine

logger = logging.getLogger(__name__)


class SessionManager:
    """Periodic session health monitor for all AI providers.

    Usage::

        mgr = SessionManager(browser_engine, interval_seconds=300)
        mgr.start()   # launches the background heartbeat
        ...
        mgr.stop()    # tears down the heartbeat task
    """

    def __init__(
        self,
        engine: BrowserEngine,
        interval_seconds: int = 300,
    ) -> None:
        self._engine = engine
        self._interval = interval_seconds
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        """Launch the background heartbeat loop."""
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run())
        logger.info("SessionManager heartbeat started (interval=%ds)", self._interval)

    async def stop(self) -> None:
        """Cancel the background heartbeat loop."""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
            logger.info("SessionManager heartbeat stopped")

    async def _run(self) -> None:
        """Heartbeat loop — periodically re-check all providers."""
        ai_ids = ["deepseek", "qianwen", "gemini", "chatgpt", "mimo"]
        while True:
            await asyncio.sleep(self._interval)
            for ai_id in ai_ids:
                try:
                    await self._check_one(ai_id)
                except Exception as exc:
                    logger.warning("Session heartbeat check failed for %s: %s", ai_id, exc)

    async def _check_one(self, ai_id: str) -> None:
        """Non-intrusive session health check for a single AI.

        Uses the engine's ``_has_valid_session`` (cookie-file SQLite probe)
        to decide whether the session is still alive.  No browser page is
        opened during the check.
        """
        if not hasattr(self._engine, "_has_valid_session"):
            return
        state = self._engine._has_valid_session(ai_id)
        if hasattr(self._engine, "set_session_state"):
            self._engine.set_session_state(ai_id, state)
        if state == SessionState.AUTH_EXPIRED:
            logger.warning("SessionManager: %s session EXPIRED", ai_id)
        elif state == SessionState.AUTHENTICATED:
            logger.debug("SessionManager: %s session OK", ai_id)
