"""Tests for BrowserEngine abstraction layer."""

import pytest
from browser.engine import EngineMode, AuthStatus, EngineStatus, PageInfo
from browser.cdp_engine import CDPEngine
from browser.embedded_engine import EmbeddedEngine
from browser.factory import create_engine


class TestBrowserEngine:
    """Test browser engine factory and base functionality."""

    def test_create_cdp_engine(self):
        engine = create_engine("cdp")
        assert isinstance(engine, CDPEngine)
        assert engine.mode == EngineMode.CDP

    def test_create_embedded_engine(self):
        engine = create_engine("embedded")
        assert isinstance(engine, EmbeddedEngine)
        assert engine.mode == EngineMode.EMBEDDED

    def test_create_engine_with_enum(self):
        engine = create_engine(EngineMode.CDP)
        assert isinstance(engine, CDPEngine)


class TestCDPEngine:
    """Test CDP engine."""

    def test_initial_state(self):
        engine = CDPEngine()
        assert engine.mode == EngineMode.CDP

    @pytest.mark.asyncio
    async def test_initial_not_connected(self):
        engine = CDPEngine()
        assert await engine.is_connected() is False

    @pytest.mark.asyncio
    async def test_connect_failure(self):
        engine = CDPEngine(cdp_url="http://localhost:99999")
        result = await engine.connect()
        assert result is False

    @pytest.mark.asyncio
    async def test_disconnect(self):
        engine = CDPEngine()
        await engine.disconnect()  # Should not raise


class TestEmbeddedEngine:
    """Test embedded engine."""

    def test_initial_state(self):
        engine = EmbeddedEngine()
        assert engine.mode == EngineMode.EMBEDDED

    @pytest.mark.asyncio
    async def test_initial_not_connected(self):
        engine = EmbeddedEngine()
        assert await engine.is_connected() is False

    @pytest.mark.asyncio
    async def test_disconnect(self):
        engine = EmbeddedEngine()
        await engine.disconnect()  # Should not raise


class TestAuthStatus:
    """Test auth status enum."""

    def test_auth_status_values(self):
        assert AuthStatus.AUTHENTICATED.value == "authenticated"
        assert AuthStatus.EXPIRED.value == "expired"
        assert AuthStatus.NOT_LOGGED_IN.value == "not_logged_in"
        assert AuthStatus.CAPTCHA_REQUIRED.value == "captcha_required"


class TestEngineStatus:
    """Test engine status dataclass."""

    def test_create_status(self):
        status = EngineStatus(
            mode=EngineMode.CDP,
            connected=True,
            browser_version="1.0",
            active_pages=[],
        )
        assert status.mode == EngineMode.CDP
        assert status.connected is True
        assert len(status.active_pages) == 0

    def test_create_page_info(self):
        page = PageInfo(
            ai_id="deepseek",
            url="https://chat.deepseek.com",
            title="DeepSeek",
            is_logged_in=True,
            auth_status=AuthStatus.AUTHENTICATED,
        )
        assert page.ai_id == "deepseek"
        assert page.is_logged_in is True
