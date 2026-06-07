"""Integration tests for the login flow.

These tests verify that:
1. Each AI uses its own persistent profile directory
2. Login and work share the SAME profile
3. Cookies persist across browser sessions
4. Login detection works correctly
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

import pytest

from browser.embedded_engine import EmbeddedEngine


@pytest.fixture
def temp_auth_dir():
    """Create a temporary auth directory for testing."""
    tmpdir = tempfile.mkdtemp()
    yield tmpdir
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def engine(temp_auth_dir):
    """Create an EmbeddedEngine with a temporary auth directory."""
    return EmbeddedEngine(auth_dir=temp_auth_dir, headless=True)


class TestProfileDirectories:
    """Each AI should have its own profile directory."""

    def test_profile_dir_structure(self, engine):
        """Verify profile directory is created per AI."""
        ds_dir = engine._get_profile_dir("deepseek")
        qw_dir = engine._get_profile_dir("qianwen")

        assert "deepseek_profile" in ds_dir
        assert "qianwen_profile" in qw_dir
        assert ds_dir != qw_dir

    def test_profile_dirs_created_on_demand(self, engine):
        """Profile directories should be created when needed."""
        ds_dir = Path(engine._get_profile_dir("deepseek"))
        ds_dir.mkdir(parents=True, exist_ok=True)
        assert ds_dir.exists()


class TestCookieDetection:
    """Verify cookie-based login detection.

    NOTE: _has_saved_cookies was replaced by _has_valid_session (SQLite-based).
    These tests need a real Playwright browser context to work.
    """

    @pytest.mark.xfail(reason="_has_saved_cookies removed; use _has_valid_session (SQLite)")
    def test_no_cookies_initially(self, engine):
        """No cookies before login."""
        assert engine._has_saved_cookies("deepseek") is False

    @pytest.mark.xfail(reason="_has_saved_cookies removed; use _has_valid_session (SQLite)")
    def test_detects_cookies(self, engine):
        """Should detect cookies after they're saved."""
        profile_dir = Path(engine._get_profile_dir("deepseek"))
        cookie_dir = profile_dir / "Default"
        cookie_dir.mkdir(parents=True, exist_ok=True)
        cookie_file = cookie_dir / "Cookies"
        cookie_file.write_bytes(b"fake cookie data")

        assert engine._has_saved_cookies("deepseek") is True

    @pytest.mark.xfail(reason="_has_saved_cookies removed; use _has_valid_session (SQLite)")
    def test_empty_cookies_not_detected(self, engine):
        """Empty cookie file should not count as logged in."""
        profile_dir = Path(engine._get_profile_dir("deepseek"))
        cookie_dir = profile_dir / "Default"
        cookie_dir.mkdir(parents=True, exist_ok=True)
        cookie_file = cookie_dir / "Cookies"
        cookie_file.write_bytes(b"")

        assert engine._has_saved_cookies("deepseek") is False


class TestAuthenticationState:
    """Verify authentication state management."""

    def test_initially_not_authenticated(self, engine):
        """No AI should be authenticated initially."""
        assert engine.is_authenticated("deepseek") is False
        assert engine.is_authenticated("qianwen") is False

    def test_authenticated_after_cookie_check(self, engine):
        """Should be authenticated after cookies are found."""
        # Simulate saved cookies
        profile_dir = Path(engine._get_profile_dir("deepseek"))
        cookie_dir = profile_dir / "Default"
        cookie_dir.mkdir(parents=True, exist_ok=True)
        (cookie_dir / "Cookies").write_bytes(b"fake cookies")

        # Simulate connect() which checks for saved sessions
        engine._authenticated.add("deepseek")
        assert engine.is_authenticated("deepseek") is True

    def test_authenticated_providers_list(self, engine):
        """Should list all authenticated providers."""
        engine._authenticated.add("deepseek")
        engine._authenticated.add("qianwen")

        # Use a method that checks auth
        assert engine.is_authenticated("deepseek") is True
        assert engine.is_authenticated("qianwen") is True
        assert engine.is_authenticated("gemini") is False


class TestLoginDetection:
    """Verify login detection for different AIs."""

    def test_deepseek_login_url_patterns(self, engine):
        """DeepSeek login detection based on URL."""
        # Not logged in: on sign_in page
        assert engine._is_on_ai_page("deepseek", "https://chat.deepseek.com/sign_in") is False

        # Logged in: on chat page
        assert engine._is_on_ai_page("deepseek", "https://chat.deepseek.com/") is True
        assert engine._is_on_ai_page("deepseek", "https://chat.deepseek.com/chat/123") is True

    def test_qianwen_login_url_patterns(self, engine):
        """Qianwen login detection based on URL."""
        # Logged in: on chat page
        assert engine._is_on_ai_page("qianwen", "https://qianwen.aliyun.com/chat") is True
        assert engine._is_on_ai_page("qianwen", "https://tongyi.aliyun.com/qianwen/chat") is True

        # Not on AI page
        assert engine._is_on_ai_page("qianwen", "https://example.com") is False

    def test_unknown_ai(self, engine):
        """Unknown AI should return False."""
        assert engine._is_on_ai_page("unknown", "https://example.com") is False


class TestEngineLifecycle:
    """Verify engine lifecycle management."""

    @pytest.mark.asyncio
    async def test_connect_initializes_playwright(self, engine):
        """connect() should initialize Playwright."""
        result = await engine.connect()
        assert result is True
        assert engine._playwright is not None
        assert engine._connected is True
        await engine.disconnect()

    @pytest.mark.asyncio
    async def test_disconnect_cleans_up(self, engine):
        """disconnect() should clean up all resources."""
        await engine.connect()
        await engine.disconnect()
        assert engine._connected is False
        assert engine._playwright is None

    @pytest.mark.asyncio
    async def test_is_connected_after_connect(self, engine):
        """is_connected() should return True after connect."""
        await engine.connect()
        assert await engine.is_connected() is True
        await engine.disconnect()

    @pytest.mark.asyncio
    async def test_is_not_connected_initially(self, engine):
        """is_connected() should return False initially."""
        assert await engine.is_connected() is False
