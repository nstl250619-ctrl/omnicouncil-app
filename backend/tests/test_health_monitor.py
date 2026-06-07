"""Tests for HealthMonitor — background heartbeat, event emission, health queries.

Uses mock SessionValidator and mock Pages.

Covers:
    - Registration / unregistration
    - Heartbeat round: browser alive + page alive + session valid
    - State transitions and event emission
    - Session expiry callback
    - start() / stop() lifecycle
    - get_health() / get_all_health()
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from engine.contracts import RuntimeState
from runtime.health_monitor import HealthMonitor
from shared.types import SessionState

# ============================================================
#  Helpers
# ============================================================


def _mock_session_validator(state: SessionState = SessionState.AUTHENTICATED):
    sv = MagicMock()
    sv.validate_offline = AsyncMock(return_value=state)
    return sv


def _mock_page(alive: bool = True):
    page = MagicMock()
    page.is_closed.return_value = not alive
    return page


# ============================================================
#  1. Registration
# ============================================================


class TestRegistration:

    def test_register_adds_platform(self):
        hm = HealthMonitor()
        sv = _mock_session_validator()
        hm.register("deepseek", sv)
        health = hm.get_health("deepseek")
        assert health.platform == "deepseek"
        assert health.state == RuntimeState.UNKNOWN  # not yet checked

    def test_unregister_removes_platform(self):
        hm = HealthMonitor()
        sv = _mock_session_validator()
        hm.register("deepseek", sv)
        hm.unregister("deepseek")
        health = hm.get_health("deepseek")
        assert health.state == RuntimeState.UNKNOWN

    def test_get_health_unregistered_returns_unknown(self):
        hm = HealthMonitor()
        health = hm.get_health("nonexistent")
        assert health.state == RuntimeState.UNKNOWN
        assert health.browser_alive is False


# ============================================================
#  2. Heartbeat round — manual trigger
# ============================================================


class TestHeartbeatRound:

    def test_all_green(self):
        """Browser alive + page alive + session valid → READY."""
        hm = HealthMonitor()
        sv = _mock_session_validator(SessionState.AUTHENTICATED)
        page = _mock_page(alive=True)
        hm.register("deepseek", sv, get_page_fn=lambda: page)

        asyncio.run(hm._heartbeat_round())

        health = hm.get_health("deepseek")
        assert health.state == RuntimeState.READY
        assert health.browser_alive is True
        assert health.page_alive is True
        assert health.session_valid is True
        assert health.last_heartbeat > 0

    def test_page_closed(self):
        """Browser alive + page closed → DEGRADED."""
        hm = HealthMonitor()
        sv = _mock_session_validator(SessionState.AUTHENTICATED)
        page = _mock_page(alive=False)
        hm.register("deepseek", sv, get_page_fn=lambda: page)

        asyncio.run(hm._heartbeat_round())

        health = hm.get_health("deepseek")
        assert health.state == RuntimeState.DEGRADED
        assert health.browser_alive is True
        assert health.page_alive is False

    def test_no_page(self):
        """No page → browser_alive=False → UNAVAILABLE."""
        hm = HealthMonitor()
        sv = _mock_session_validator(SessionState.AUTHENTICATED)
        hm.register("deepseek", sv, get_page_fn=lambda: None)

        asyncio.run(hm._heartbeat_round())

        health = hm.get_health("deepseek")
        assert health.state == RuntimeState.UNAVAILABLE
        assert health.browser_alive is False

    def test_session_expired(self):
        """Page alive + session expired → LOGIN_REQUIRED."""
        hm = HealthMonitor()
        sv = _mock_session_validator(SessionState.AUTH_EXPIRED)
        page = _mock_page(alive=True)
        hm.register("deepseek", sv, get_page_fn=lambda: page)

        asyncio.run(hm._heartbeat_round())

        health = hm.get_health("deepseek")
        assert health.state == RuntimeState.LOGIN_REQUIRED
        assert health.session_valid is False

    def test_no_get_page_fn(self):
        """No get_page_fn registered → browser_alive=False."""
        hm = HealthMonitor()
        sv = _mock_session_validator()
        hm.register("deepseek", sv)

        asyncio.run(hm._heartbeat_round())

        health = hm.get_health("deepseek")
        assert health.state == RuntimeState.UNAVAILABLE


# ============================================================
#  3. Event emission
# ============================================================


class TestEventEmission:

    def test_emits_session_expired_event(self):
        bus = MagicMock()
        bus.emit = AsyncMock()
        hm = HealthMonitor(event_bus=bus)

        sv_ok = _mock_session_validator(SessionState.AUTHENTICATED)
        page = _mock_page(alive=True)
        hm.register("deepseek", sv_ok, get_page_fn=lambda: page)

        # First round: all green
        asyncio.run(hm._heartbeat_round())
        bus.emit.assert_not_called()

        # Second round: session expires
        sv_expired = _mock_session_validator(SessionState.AUTH_EXPIRED)
        hm._registrations["deepseek"].session_validator = sv_expired

        asyncio.run(hm._heartbeat_round())
        bus.emit.assert_called_once_with("health:session_expired", platform="deepseek")

    def test_no_event_bus_no_crash(self):
        hm = HealthMonitor(event_bus=None)
        sv = _mock_session_validator()
        hm.register("deepseek", sv)
        # Should not crash
        asyncio.run(hm._heartbeat_round())


# ============================================================
#  4. Session expiry callback
# ============================================================


class TestSessionExpiryCallback:

    def test_callback_called_on_expiry(self):
        callback = AsyncMock()
        hm = HealthMonitor(on_session_expired=callback)

        sv_ok = _mock_session_validator(SessionState.AUTHENTICATED)
        page = _mock_page(alive=True)
        hm.register("deepseek", sv_ok, get_page_fn=lambda: page)

        # First round: green
        asyncio.run(hm._heartbeat_round())
        callback.assert_not_called()

        # Second round: expires
        sv_expired = _mock_session_validator(SessionState.AUTH_EXPIRED)
        hm._registrations["deepseek"].session_validator = sv_expired
        asyncio.run(hm._heartbeat_round())

        callback.assert_called_once_with("deepseek")

    def test_callback_exception_does_not_propagate(self):
        async def bad_callback(platform: str):
            raise ValueError("oops")

        hm = HealthMonitor(on_session_expired=bad_callback)
        sv_ok = _mock_session_validator(SessionState.AUTHENTICATED)
        page = _mock_page(alive=True)
        hm.register("deepseek", sv_ok, get_page_fn=lambda: page)
        asyncio.run(hm._heartbeat_round())

        sv_expired = _mock_session_validator(SessionState.AUTH_EXPIRED)
        hm._registrations["deepseek"].session_validator = sv_expired
        # Should not raise
        asyncio.run(hm._heartbeat_round())


# ============================================================
#  5. get_all_health()
# ============================================================


class TestGetAllHealth:

    def test_returns_all_platforms(self):
        hm = HealthMonitor()
        sv1 = _mock_session_validator(SessionState.AUTHENTICATED)
        sv2 = _mock_session_validator(SessionState.AUTH_EXPIRED)
        page = _mock_page(alive=True)
        hm.register("deepseek", sv1, get_page_fn=lambda: page)
        hm.register("gemini", sv2, get_page_fn=lambda: page)

        asyncio.run(hm._heartbeat_round())

        all_health = hm.get_all_health()
        assert len(all_health) == 2
        assert all_health["deepseek"].state == RuntimeState.READY
        assert all_health["gemini"].state == RuntimeState.LOGIN_REQUIRED


# ============================================================
#  6. Lifecycle — start / stop
# ============================================================


class TestLifecycle:

    def test_start_sets_running(self):
        async def _run():
            hm = HealthMonitor(interval_s=60)
            sv = _mock_session_validator()
            hm.register("deepseek", sv)
            hm.start()
            assert hm.is_running is True
            await hm.stop()
            assert hm.is_running is False
        asyncio.run(_run())

    def test_start_idempotent(self):
        async def _run():
            hm = HealthMonitor(interval_s=60)
            sv = _mock_session_validator()
            hm.register("deepseek", sv)
            hm.start()
            hm.start()  # should not create a second task
            assert hm.is_running is True
            await hm.stop()
        asyncio.run(_run())

    def test_stop_when_not_started(self):
        async def _run():
            hm = HealthMonitor()
            await hm.stop()  # should not crash
        asyncio.run(_run())


# ============================================================
#  7. Multiple platforms
# ============================================================


class TestMultiplePlatforms:

    def test_independent_health_per_platform(self):
        hm = HealthMonitor()
        sv1 = _mock_session_validator(SessionState.AUTHENTICATED)
        sv2 = _mock_session_validator(SessionState.AUTH_EXPIRED)
        page_ok = _mock_page(alive=True)
        page_bad = _mock_page(alive=False)

        hm.register("deepseek", sv1, get_page_fn=lambda: page_ok)
        hm.register("gemini", sv2, get_page_fn=lambda: page_bad)

        asyncio.run(hm._heartbeat_round())

        ds = hm.get_health("deepseek")
        ge = hm.get_health("gemini")

        assert ds.state == RuntimeState.READY
        assert ds.browser_alive is True
        assert ds.page_alive is True
        assert ds.session_valid is True

        assert ge.state == RuntimeState.DEGRADED  # browser alive but page closed
        assert ge.page_alive is False

    def test_unregister_mid_round(self):
        hm = HealthMonitor()
        sv = _mock_session_validator()
        page = _mock_page(alive=True)
        hm.register("deepseek", sv, get_page_fn=lambda: page)
        hm.register("gemini", sv, get_page_fn=lambda: page)

        hm.unregister("gemini")
        asyncio.run(hm._heartbeat_round())

        all_health = hm.get_all_health()
        assert "deepseek" in all_health
        assert "gemini" not in all_health
