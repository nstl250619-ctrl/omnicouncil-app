"""Profile sharing tests — ensures login and work use the same profile.

These tests verify the CORE invariant:
  login() 和 get_page() 使用同一个 profile 目录，Cookie 自动共享。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from browser.embedded_engine import EmbeddedEngine


@pytest.fixture
def auth_dir(tmp_path):
    """Create a temporary auth directory."""
    d = tmp_path / "auth"
    d.mkdir()
    return str(d)


@pytest.fixture
def engine(auth_dir):
    """Create an EmbeddedEngine with temporary auth directory."""
    return EmbeddedEngine(auth_dir=auth_dir, headless=True)


class TestProfileSharing:
    """login() and get_page() must use the same profile directory."""

    def test_profile_dir_consistency(self, engine):
        """_get_profile_dir returns the same path for the same AI."""
        path1 = engine._get_profile_dir("qianwen")
        path2 = engine._get_profile_dir("qianwen")
        assert path1 == path2

    def test_different_ai_different_profile(self, engine):
        """Different AIs must have different profile directories."""
        ds = engine._get_profile_dir("deepseek")
        qw = engine._get_profile_dir("qianwen")
        assert ds != qw
        assert "deepseek_profile" in ds
        assert "qianwen_profile" in qw


class TestCookieDetection:
    """_has_saved_cookies must detect valid cookies.

    NOTE: _has_saved_cookies was replaced by _has_valid_session (SQLite-based).
    """

    @pytest.mark.xfail(reason="_has_saved_cookies removed; use _has_valid_session (SQLite)")
    def test_no_cookies_initially(self, engine):
        assert engine._has_saved_cookies("deepseek") is False

    @pytest.mark.xfail(reason="_has_saved_cookies removed; use _has_valid_session (SQLite)")
    def test_detects_valid_cookies(self, engine):
        profile = Path(engine._get_profile_dir("deepseek"))
        cookie_dir = profile / "Default"
        cookie_dir.mkdir(parents=True)
        (cookie_dir / "Cookies").write_bytes(b"fake_cookie_data")
        assert engine._has_saved_cookies("deepseek") is True

    @pytest.mark.xfail(reason="_has_saved_cookies removed; use _has_valid_session (SQLite)")
    def test_empty_cookie_file_not_detected(self, engine):
        profile = Path(engine._get_profile_dir("deepseek"))
        cookie_dir = profile / "Default"
        cookie_dir.mkdir(parents=True)
        (cookie_dir / "Cookies").write_bytes(b"")
        assert engine._has_saved_cookies("deepseek") is False

    @pytest.mark.xfail(reason="_has_saved_cookies removed; use _has_valid_session (SQLite)")
    def test_missing_cookie_file(self, engine):
        assert engine._has_saved_cookies("nonexistent") is False


class TestAuthenticationState:
    """Authentication state management."""

    def test_initially_not_authenticated(self, engine):
        assert engine.is_authenticated("deepseek") is False
        assert engine.is_authenticated("qianwen") is False

    def test_authenticated_after_manual_set(self, engine):
        engine._authenticated.add("deepseek")
        assert engine.is_authenticated("deepseek") is True
        assert engine.is_authenticated("qianwen") is False

    def test_multiple_ais_independent(self, engine):
        engine._authenticated.add("deepseek")
        engine._authenticated.add("qianwen")
        assert engine.is_authenticated("deepseek") is True
        assert engine.is_authenticated("qianwen") is True
        assert engine.is_authenticated("gemini") is False


class TestLoginDetection:
    """URL-based login detection for different AIs."""

    def test_deepseek_not_logged_in(self, engine):
        assert engine._is_on_ai_page("deepseek", "https://chat.deepseek.com/sign_in") is False

    def test_deepseek_logged_in(self, engine):
        assert engine._is_on_ai_page("deepseek", "https://chat.deepseek.com/") is True
        assert engine._is_on_ai_page("deepseek", "https://chat.deepseek.com/chat/abc123") is True

    def test_qianwen_logged_in(self, engine):
        assert engine._is_on_ai_page("qianwen", "https://qianwen.aliyun.com/chat") is True
        assert engine._is_on_ai_page("qianwen", "https://www.qianwen.com/chat/abc") is True

    def test_qianwen_landing_page(self, engine):
        # Landing pages should NOT count as logged in
        assert engine._is_on_ai_page("qianwen", "https://qianwen.aliyun.com/") is False

    def test_unknown_ai(self, engine):
        assert engine._is_on_ai_page("unknown", "https://example.com") is False


class TestEngineLifecycle:
    """Engine connect/disconnect lifecycle."""

    @pytest.mark.asyncio
    async def test_connect(self, engine):
        result = await engine.connect()
        assert result is True
        assert engine._connected is True
        assert engine._playwright is not None
        await engine.disconnect()

    @pytest.mark.asyncio
    async def test_disconnect(self, engine):
        await engine.connect()
        await engine.disconnect()
        assert engine._connected is False
        assert engine._playwright is None

    @pytest.mark.asyncio
    async def test_is_connected(self, engine):
        assert await engine.is_connected() is False
        await engine.connect()
        assert await engine.is_connected() is True
        await engine.disconnect()
        assert await engine.is_connected() is False


class TestContextCreation:
    """Per-AI context creation."""

    @pytest.mark.asyncio
    async def test_context_created_per_ai(self, engine):
        """Each AI should get its own context."""
        await engine.connect()
        try:
            ctx1 = await engine._get_context("deepseek")
            ctx2 = await engine._get_context("qianwen")
            assert ctx1 is not ctx2
            assert len(engine._contexts) == 2
        finally:
            await engine.disconnect()

    @pytest.mark.asyncio
    async def test_context_reused(self, engine):
        """Same AI should reuse the same context."""
        await engine.connect()
        try:
            ctx1 = await engine._get_context("deepseek")
            ctx2 = await engine._get_context("deepseek")
            assert ctx1 is ctx2
            assert len(engine._contexts) == 1
        finally:
            await engine.disconnect()
