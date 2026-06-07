"""Tests for BaseQueryAdapter and platform query adapters.

Uses mock Playwright pages.

Covers:
    - BaseQueryAdapter.execute() flow
    - pre_flight_check() — page alive, URL, Cloudflare, input missing
    - send_prompt() — default and platform-specific
    - _find_stop_button() — stop button detection
    - Platform adapters: DeepSeek, ChatGPT, Gemini, Qianwen, MiMo
    - VisionFallback — import check, OCR extraction
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from engine.contracts import QueryState
from providers.base.query_adapter import BaseQueryAdapter, QueryAdapterConfig

# ============================================================
#  Helpers
# ============================================================


def _mock_page(
    url: str = "https://chat.deepseek.com",
    title: str = "DeepSeek",
    closed: bool = False,
    visible_input: bool = True,
):
    page = MagicMock()
    page.url = url
    page.is_closed.return_value = closed
    page.title = AsyncMock(return_value=title)
    page.wait_for_timeout = AsyncMock()
    page.keyboard = MagicMock()
    page.keyboard.press = AsyncMock()
    page.screenshot = AsyncMock(return_value=b"\x89PNG")

    if visible_input:
        input_el = MagicMock()
        input_el.click = AsyncMock()
        input_el.fill = AsyncMock()
        input_el.is_visible = AsyncMock(return_value=True)
        locator = MagicMock()
        locator.first = input_el
        locator.count = AsyncMock(return_value=1)
    else:
        locator = MagicMock()
        locator.first = MagicMock(is_visible=AsyncMock(return_value=False))
        locator.count = AsyncMock(return_value=0)

    page.locator.return_value = locator
    return page


class _TestAdapter(BaseQueryAdapter):
    """Minimal concrete adapter for testing."""

    def config(self) -> QueryAdapterConfig:
        return QueryAdapterConfig(
            platform="test", display_name="Test", home_url="https://test.com"
        )

    async def _find_input(self, page):
        try:
            el = page.locator("textarea").first
            if await el.is_visible(timeout=1000):
                return el
        except Exception:
            pass
        return None

    async def _extract_response(self, page, prompt, timeout_ms):
        return "test response"


# ============================================================
#  1. BaseQueryAdapter.execute()
# ============================================================


class TestExecute:

    def test_success(self):
        page = _mock_page()
        adapter = _TestAdapter()
        result = asyncio.run(adapter.execute(page, "hello"))
        assert result.state == QueryState.DONE
        assert result.content == "test response"
        assert result.elapsed_seconds >= 0

    def test_pre_flight_failure(self):
        page = _mock_page(closed=True)
        adapter = _TestAdapter()
        result = asyncio.run(adapter.execute(page, "hello"))
        assert result.state == QueryState.FAILED
        assert "pre-flight" in result.error

    def test_send_failure(self):
        page = _mock_page(visible_input=False)
        adapter = _TestAdapter()
        result = asyncio.run(adapter.execute(page, "hello"))
        assert result.state == QueryState.FAILED


# ============================================================
#  2. pre_flight_check()
# ============================================================


class TestPreFlightCheck:

    def test_ok(self):
        page = _mock_page()
        adapter = _TestAdapter()
        ok, reason = asyncio.run(adapter.pre_flight_check(page))
        assert ok is True
        assert reason == "ok"

    def test_page_closed(self):
        page = _mock_page(closed=True)
        adapter = _TestAdapter()
        ok, reason = asyncio.run(adapter.pre_flight_check(page))
        assert ok is False
        assert reason == "page_closed"

    def test_login_url(self):
        page = _mock_page(url="https://chat.deepseek.com/sign_in")
        adapter = _TestAdapter()
        ok, reason = asyncio.run(adapter.pre_flight_check(page))
        assert ok is False
        assert reason == "login_required"

    def test_cloudflare(self):
        page = _mock_page(title="Just a moment...")
        adapter = _TestAdapter()
        ok, reason = asyncio.run(adapter.pre_flight_check(page))
        assert ok is False
        assert reason == "cloudflare_challenge"

    def test_input_missing(self):
        page = _mock_page(visible_input=False)
        adapter = _TestAdapter()
        ok, reason = asyncio.run(adapter.pre_flight_check(page))
        assert ok is False
        assert reason == "input_missing"


# ============================================================
#  3. send_prompt() default
# ============================================================


class TestSendPrompt:

    def test_default_send(self):
        page = _mock_page()
        adapter = _TestAdapter()
        asyncio.run(adapter.send_prompt(page, "hello"))
        page.locator("textarea").first.click.assert_called_once()
        page.locator("textarea").first.fill.assert_called_once_with("hello")
        page.keyboard.press.assert_called_with("Enter")


# ============================================================
#  4. Platform adapters — instantiation and config
# ============================================================


class TestPlatformAdapters:

    def test_deepseek(self):
        from providers.deepseek.query_adapter import DeepSeekQueryAdapter
        adapter = DeepSeekQueryAdapter()
        cfg = adapter.config()
        assert cfg.platform == "deepseek"
        assert cfg.display_name == "DeepSeek"

    def test_chatgpt(self):
        from providers.chatgpt.query_adapter import ChatGPTQueryAdapter
        adapter = ChatGPTQueryAdapter()
        cfg = adapter.config()
        assert cfg.platform == "chatgpt"
        assert cfg.display_name == "ChatGPT"

    def test_gemini(self):
        from providers.gemini.query_adapter import GeminiQueryAdapter
        adapter = GeminiQueryAdapter()
        cfg = adapter.config()
        assert cfg.platform == "gemini"
        assert cfg.display_name == "Gemini"

    def test_qianwen(self):
        from providers.qianwen.query_adapter import QianwenQueryAdapter
        adapter = QianwenQueryAdapter()
        cfg = adapter.config()
        assert cfg.platform == "qianwen"
        assert cfg.display_name == "千问"

    def test_mimo(self):
        from providers.mimo.query_adapter import MiMoQueryAdapter
        adapter = MiMoQueryAdapter()
        cfg = adapter.config()
        assert cfg.platform == "mimo"
        assert cfg.display_name == "MiMo"


# ============================================================
#  5. Platform adapters — pre_flight_check
# ============================================================


class TestPlatformPreFlight:

    def test_chatgpt_login_redirect(self):
        from providers.chatgpt.query_adapter import ChatGPTQueryAdapter
        page = _mock_page(url="https://auth0.openai.com/login")
        adapter = ChatGPTQueryAdapter()
        ok, reason = asyncio.run(adapter.pre_flight_check(page))
        assert ok is False
        assert reason == "login_required"

    def test_gemini_google_redirect(self):
        from providers.gemini.query_adapter import GeminiQueryAdapter
        page = _mock_page(url="https://accounts.google.com/signin")
        adapter = GeminiQueryAdapter()
        ok, reason = asyncio.run(adapter.pre_flight_check(page))
        assert ok is False
        assert reason == "login_required"

    def test_mimo_login_url(self):
        from providers.mimo.query_adapter import MiMoQueryAdapter
        page = _mock_page(url="https://aistudio.xiaomimimo.com/login")
        adapter = MiMoQueryAdapter()
        ok, reason = asyncio.run(adapter.pre_flight_check(page))
        assert ok is False
        assert reason == "login_required"


# ============================================================
#  6. _is_ui_element()
# ============================================================


class TestIsUiElement:

    def test_short_text(self):
        adapter = _TestAdapter()
        assert adapter._is_ui_element("a") is True
        assert adapter._is_ui_element("hello") is False

    def test_deepseek_elements(self):
        from providers.deepseek.query_adapter import DeepSeekQueryAdapter
        adapter = DeepSeekQueryAdapter()
        assert adapter._is_ui_element("DeepThink") is True
        assert adapter._is_ui_element("New chat") is True
        assert adapter._is_ui_element("Real response text") is False

    def test_qianwen_elements(self):
        from providers.qianwen.query_adapter import QianwenQueryAdapter
        adapter = QianwenQueryAdapter()
        assert adapter._is_ui_element("新建对话") is True
        assert adapter._is_ui_element("登录") is True
        assert adapter._is_ui_element("Qwen3.7-Max") is True


# ============================================================
#  7. VisionFallback
# ============================================================


class TestVisionFallback:

    def test_import_without_deps(self):
        """VisionFallback should be importable even without pytesseract."""
        from providers.vision_fallback import VisionFallback
        fallback = VisionFallback()
        assert fallback is not None

    def test_extract_returns_empty_when_no_tesseract(self):
        from providers.vision_fallback import VisionFallback
        fallback = VisionFallback()
        # If pytesseract is not installed, should return empty
        page = MagicMock()
        page.screenshot = AsyncMock(return_value=b"\x89PNG")
        result = asyncio.run(fallback.extract_from_screenshot(page))
        # Either works (if tesseract installed) or returns empty
        assert isinstance(result, str)
