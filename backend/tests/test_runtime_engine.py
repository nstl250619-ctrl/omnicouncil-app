"""Integration tests for AIRuntimeEngine — full boot → ready → query cycle.

Tests use mock Playwright objects to avoid real browser launches.

Covers:
    - Full boot sequence: UNKNOWN → INITIALIZING → PROFILE_LOADING → SESSION_CHECKING → READY
    - ensure_ready() idempotency
    - get_page() raises RuntimeNotReadyError when not READY
    - shutdown() transitions to SHUTDOWN
    - attempt_recovery() delegates to RecoveryEngine
    - Health monitoring integration
    - Watchdog for non-headless platforms
    - Sub-component access
"""

from __future__ import annotations

import asyncio
from pathlib import Path  # noqa: TC003
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from engine.contracts import (
    PlatformConfig,
    RecoveryFailedError,
    RuntimeNotReadyError,
    RuntimeState,
)
from runtime.engine import AIRuntimeEngine
from shared.types import SessionState

# Patch target for Playwright — imported inside _launch_browser()
_PATCHRIGHT_PATCH = "patchright.async_api.async_playwright"


# ============================================================
#  Helpers
# ============================================================


def _mock_playwright():
    """Create a mock Playwright setup."""
    pw = MagicMock()
    context = MagicMock()
    page = MagicMock()
    page.is_closed.return_value = False
    page.url = "https://chat.deepseek.com"
    page.goto = AsyncMock()
    page.wait_for_timeout = AsyncMock()
    page.reload = AsyncMock()
    page.close = AsyncMock()
    page.title = AsyncMock(return_value="DeepSeek")

    context.new_page = AsyncMock(return_value=page)
    context.close = AsyncMock()
    context.pages = [page]

    pw.chromium = MagicMock()
    pw.chromium.launch_persistent_context = AsyncMock(return_value=context)
    pw.stop = AsyncMock()
    return pw, context, page


def _make_config(**overrides) -> PlatformConfig:
    defaults = dict(
        name="deepseek",
        home_url="https://chat.deepseek.com",
        headless=True,
        heartbeat_interval_s=60,
        max_recovery_attempts=3,
        recovery_cooldown_s=0,
        session_check_mode="offline",
    )
    defaults.update(overrides)
    return PlatformConfig(**defaults)


# ============================================================
#  1. Full boot sequence
# ============================================================


class TestBoot:

    def test_boot_transitions_to_ready(self, tmp_path: Path):
        """Happy path: UNKNOWN → INITIALIZING → PROFILE_LOADING → SESSION_CHECKING → READY."""
        config = _make_config()
        engine = AIRuntimeEngine(config)

        pw, ctx, page = _mock_playwright()
        # Session is valid
        sv = MagicMock()
        sv.validate = AsyncMock(return_value=SessionState.AUTHENTICATED)
        sv.validate_offline = AsyncMock(return_value=SessionState.AUTHENTICATED)
        engine._session_validator = sv

        with patch(_PATCHRIGHT_PATCH, return_value=MagicMock(start=AsyncMock(return_value=pw))):
            # Mock profile manager to use tmp_path
            pm = MagicMock()
            pm.create = AsyncMock(return_value=tmp_path / "deepseek_profile")
            pm.get_profile_path.return_value = tmp_path / "deepseek_profile"
            pm.backup = AsyncMock()
            engine._profile_manager = pm

            result = asyncio.run(engine.boot())

        assert result == RuntimeState.READY
        assert engine.state == RuntimeState.READY
        assert engine.is_connected is True
        assert len(engine.state_history) == 4

    def test_boot_session_invalid_transitions_to_login_required(self, tmp_path: Path):
        config = _make_config()
        engine = AIRuntimeEngine(config)

        pw, ctx, page = _mock_playwright()
        sv = MagicMock()
        sv.validate = AsyncMock(return_value=SessionState.AUTH_EXPIRED)
        engine._session_validator = sv

        with patch(_PATCHRIGHT_PATCH, return_value=MagicMock(start=AsyncMock(return_value=pw))):
            pm = MagicMock()
            pm.create = AsyncMock(return_value=tmp_path / "deepseek_profile")
            pm.get_profile_path.return_value = tmp_path / "deepseek_profile"
            engine._profile_manager = pm

            result = asyncio.run(engine.boot())

        assert result == RuntimeState.LOGIN_REQUIRED

    def test_boot_browser_failure_transitions_to_unavailable(self, tmp_path: Path):
        config = _make_config()
        engine = AIRuntimeEngine(config)

        # Make browser launch fail
        with patch(_PATCHRIGHT_PATCH, side_effect=RuntimeError("no browser")):
            pm = MagicMock()
            pm.create = AsyncMock(return_value=tmp_path)
            pm.get_profile_path.return_value = tmp_path
            engine._profile_manager = pm

            with pytest.raises(RuntimeError, match="no browser"):
                asyncio.run(engine.boot())

        assert engine.state == RuntimeState.UNAVAILABLE

    def test_boot_ignores_in_ready_state(self):
        config = _make_config()
        engine = AIRuntimeEngine(config)
        # Force to READY
        asyncio.run(engine._state_machine.transition(RuntimeState.INITIALIZING))
        asyncio.run(engine._state_machine.transition(RuntimeState.PROFILE_LOADING))
        asyncio.run(engine._state_machine.transition(RuntimeState.SESSION_CHECKING))
        asyncio.run(engine._state_machine.transition(RuntimeState.READY))

        result = asyncio.run(engine.boot())
        assert result == RuntimeState.READY  # no-op


# ============================================================
#  2. ensure_ready()
# ============================================================


class TestEnsureReady:

    def test_ready_returns_immediately(self):
        config = _make_config()
        engine = AIRuntimeEngine(config)
        # Force to READY
        for s in [RuntimeState.INITIALIZING, RuntimeState.PROFILE_LOADING,
                  RuntimeState.SESSION_CHECKING, RuntimeState.READY]:
            asyncio.run(engine._state_machine.transition(s))

        result = asyncio.run(engine.ensure_ready())
        assert result == RuntimeState.READY

    def test_unknown_triggers_boot(self, tmp_path: Path):
        config = _make_config()
        engine = AIRuntimeEngine(config)

        pw, ctx, page = _mock_playwright()
        sv = MagicMock()
        sv.validate = AsyncMock(return_value=SessionState.AUTHENTICATED)
        sv.validate_offline = AsyncMock(return_value=SessionState.AUTHENTICATED)
        engine._session_validator = sv

        with patch(_PATCHRIGHT_PATCH, return_value=MagicMock(start=AsyncMock(return_value=pw))):
            pm = MagicMock()
            pm.create = AsyncMock(return_value=tmp_path / "deepseek_profile")
            pm.get_profile_path.return_value = tmp_path / "deepseek_profile"
            pm.backup = AsyncMock()
            engine._profile_manager = pm

            result = asyncio.run(engine.ensure_ready())

        assert result == RuntimeState.READY

    def test_unavailable_triggers_boot_after_recovery_exhausted(self, tmp_path: Path):
        config = _make_config()
        engine = AIRuntimeEngine(config)
        asyncio.run(engine._state_machine.transition(RuntimeState.INITIALIZING))
        asyncio.run(engine._state_machine.transition(RuntimeState.UNAVAILABLE))

        pw, ctx, page = _mock_playwright()
        sv = MagicMock()
        sv.validate = AsyncMock(return_value=SessionState.AUTHENTICATED)
        sv.validate_offline = AsyncMock(return_value=SessionState.AUTHENTICATED)
        engine._session_validator = sv

        # Mock recovery engine to raise (simulating exhaustion)
        re = MagicMock()
        re.recover = AsyncMock(side_effect=RecoveryFailedError("deepseek", 3))
        engine._recovery_engine = re

        with patch(_PATCHRIGHT_PATCH, return_value=MagicMock(start=AsyncMock(return_value=pw))):
            pm = MagicMock()
            pm.create = AsyncMock(return_value=tmp_path / "deepseek_profile")
            pm.get_profile_path.return_value = tmp_path / "deepseek_profile"
            pm.backup = AsyncMock()
            engine._profile_manager = pm

            result = asyncio.run(engine.ensure_ready())

        assert result == RuntimeState.READY


# ============================================================
#  3. get_page()
# ============================================================


class TestGetPage:

    def test_raises_when_not_ready(self):
        config = _make_config()
        engine = AIRuntimeEngine(config)
        with pytest.raises(RuntimeNotReadyError):
            engine.get_page()

    def test_returns_page_when_ready(self):
        config = _make_config()
        engine = AIRuntimeEngine(config)
        # Force READY
        for s in [RuntimeState.INITIALIZING, RuntimeState.PROFILE_LOADING,
                  RuntimeState.SESSION_CHECKING, RuntimeState.READY]:
            asyncio.run(engine._state_machine.transition(s))

        # Set a mock page
        page = MagicMock()
        page.is_closed.return_value = False
        engine._page = page

        result = engine.get_page()
        assert result is page

    def test_raises_when_page_closed(self):
        config = _make_config()
        engine = AIRuntimeEngine(config)
        for s in [RuntimeState.INITIALIZING, RuntimeState.PROFILE_LOADING,
                  RuntimeState.SESSION_CHECKING, RuntimeState.READY]:
            asyncio.run(engine._state_machine.transition(s))

        page = MagicMock()
        page.is_closed.return_value = True
        engine._page = page

        with pytest.raises(RuntimeNotReadyError):
            engine.get_page()


# ============================================================
#  4. shutdown()
# ============================================================


class TestShutdown:

    def test_shutdown_transitions_to_shutdown(self):
        config = _make_config()
        engine = AIRuntimeEngine(config)
        for s in [RuntimeState.INITIALIZING, RuntimeState.PROFILE_LOADING,
                  RuntimeState.SESSION_CHECKING, RuntimeState.READY]:
            asyncio.run(engine._state_machine.transition(s))

        asyncio.run(engine.shutdown())
        assert engine.state == RuntimeState.SHUTDOWN

    def test_shutdown_idempotent(self):
        config = _make_config()
        engine = AIRuntimeEngine(config)
        asyncio.run(engine._state_machine.transition(RuntimeState.INITIALIZING))
        asyncio.run(engine._state_machine.transition(RuntimeState.UNAVAILABLE))
        asyncio.run(engine._state_machine.transition(RuntimeState.SHUTDOWN))

        asyncio.run(engine.shutdown())  # should not raise
        assert engine.state == RuntimeState.SHUTDOWN


# ============================================================
#  5. check_health()
# ============================================================


class TestCheckHealth:

    def test_health_returns_snapshot(self):
        config = _make_config()
        engine = AIRuntimeEngine(config)
        for s in [RuntimeState.INITIALIZING, RuntimeState.PROFILE_LOADING,
                  RuntimeState.SESSION_CHECKING, RuntimeState.READY]:
            asyncio.run(engine._state_machine.transition(s))

        page = MagicMock()
        page.is_closed.return_value = False
        engine._page = page
        engine._playwright = MagicMock()
        engine._context = MagicMock()

        sv = MagicMock()
        sv.validate_offline = AsyncMock(return_value=SessionState.AUTHENTICATED)
        engine._session_validator = sv

        health = asyncio.run(engine.check_health())
        assert health.platform == "deepseek"
        assert health.state == RuntimeState.READY
        assert health.browser_alive is True
        assert health.page_alive is True
        assert health.session_valid is True


# ============================================================
#  6. attempt_recovery()
# ============================================================


class TestAttemptRecovery:

    def test_delegates_to_recovery_engine(self):
        config = _make_config()
        engine = AIRuntimeEngine(config)
        for s in [RuntimeState.INITIALIZING, RuntimeState.PROFILE_LOADING,
                  RuntimeState.SESSION_CHECKING, RuntimeState.READY]:
            asyncio.run(engine._state_machine.transition(s))
        asyncio.run(engine._state_machine.transition(RuntimeState.DEGRADED))

        re = MagicMock()
        re.recover = AsyncMock(return_value=True)
        engine._recovery_engine = re

        result = asyncio.run(engine.attempt_recovery())
        assert result is True
        re.recover.assert_called_once_with(engine, "deepseek")


# ============================================================
#  7. Sub-component access
# ============================================================


class TestSubComponents:

    def test_get_profile_manager(self):
        config = _make_config()
        engine = AIRuntimeEngine(config)
        pm = engine.get_profile_manager()
        assert pm is not None

    def test_get_session_validator(self):
        config = _make_config()
        engine = AIRuntimeEngine(config)
        sv = engine.get_session_validator()
        assert sv is not None

    def test_get_health_monitor(self):
        config = _make_config()
        engine = AIRuntimeEngine(config)
        hm = engine.get_health_monitor()
        assert hm is not None

    def test_get_platform_config(self):
        config = _make_config()
        engine = AIRuntimeEngine(config)
        assert engine.get_platform_config().name == "deepseek"

    def test_state_machine_property(self):
        config = _make_config()
        engine = AIRuntimeEngine(config)
        assert engine.state_machine.current == RuntimeState.UNKNOWN


# ============================================================
#  8. Platform properties
# ============================================================


class TestProperties:

    def test_platform_name(self):
        config = _make_config(name="chatgpt")
        engine = AIRuntimeEngine(config)
        assert engine.platform == "chatgpt"

    def test_is_connected_false_initially(self):
        config = _make_config()
        engine = AIRuntimeEngine(config)
        assert engine.is_connected is False

    def test_state_history(self):
        config = _make_config()
        engine = AIRuntimeEngine(config)
        assert engine.state_history == []
