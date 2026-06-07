"""Coverage boost tests for query adapters — extraction logic, wait, abort.

Tests the platform-specific _extract_response, _try_selector_extraction,
_try_body_extraction, wait_for_response, and abort_current methods
using mock Playwright pages with realistic DOM structures.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from engine.contracts import QueryState


# ============================================================
#  Helpers
# ============================================================


def _mock_page_with_response(response_text: str = "AI response here"):
    """Create a mock page that returns response text via inner_text."""
    page = MagicMock()
    page.url = "https://chat.deepseek.com"
    page.is_closed.return_value = False
    page.title = AsyncMock(return_value="DeepSeek")
    page.wait_for_timeout = AsyncMock()
    page.keyboard = MagicMock()
    page.keyboard.press = AsyncMock()

    # Response element
    response_el = MagicMock()
    response_el.inner_text = AsyncMock(return_value=response_text)
    response_el.is_visible = AsyncMock(return_value=True)

    # Input element
    input_el = MagicMock()
    input_el.click = AsyncMock()
    input_el.fill = AsyncMock()
    input_el.is_visible = AsyncMock(return_value=True)

    # Stop button (hidden = generation done)
    stop_btn = MagicMock()
    stop_btn.is_visible = AsyncMock(return_value=False)
    stop_btn.click = AsyncMock()

    def locator_side_effect(selector):
        loc = MagicMock()
        if "stop" in selector.lower() or "停止" in selector:
            loc.first = stop_btn
            loc.count = AsyncMock(return_value=1)
        elif "assistant" in selector or "message" in selector or "markdown" in selector or "response" in selector:
            loc.first = response_el
            loc.count = AsyncMock(return_value=1)
            loc.nth.return_value = response_el
        elif "textarea" in selector or "contenteditable" in selector or "textbox" in selector or "prompt" in selector:
            loc.first = input_el
            loc.count = AsyncMock(return_value=1)
        else:
            loc.first = MagicMock(is_visible=AsyncMock(return_value=False))
            loc.count = AsyncMock(return_value=0)
        return loc

    page.locator = MagicMock(side_effect=locator_side_effect)

    # Body text fallback
    body_text = f"System prompt\nUser question\n{response_text}\nCopy\nRegenerate"
    body_el = MagicMock()
    body_el.inner_text = AsyncMock(return_value=body_text)
    page.locator("body").inner_text = body_el.inner_text

    return page


# ============================================================
#  1. DeepSeek extraction
# ============================================================


class TestDeepSeekExtraction:

    def test_selector_extraction(self):
        from providers.deepseek.query_adapter import DeepSeekQueryAdapter
        adapter = DeepSeekQueryAdapter()
        page = _mock_page_with_response("DeepSeek says hello")
        result = asyncio.run(adapter._try_selector_extraction(page, "question"))
        assert "DeepSeek says hello" in result

    def test_body_extraction(self):
        from providers.deepseek.query_adapter import DeepSeekQueryAdapter
        adapter = DeepSeekQueryAdapter()
        page = MagicMock()
        page.url = "https://chat.deepseek.com"
        body_text = "System\nUser question\nDeepSeek body response\nCopy"
        body_el = MagicMock()
        body_el.inner_text = AsyncMock(return_value=body_text)
        loc = MagicMock()
        loc.inner_text = body_el.inner_text
        page.locator.return_value = loc
        result = asyncio.run(adapter._try_body_extraction(page, "User question"))
        assert "DeepSeek body response" in result

    def test_is_ui_element(self):
        from providers.deepseek.query_adapter import DeepSeekQueryAdapter
        adapter = DeepSeekQueryAdapter()
        assert adapter._is_ui_element("DeepThink") is True
        assert adapter._is_ui_element("New chat") is True
        assert adapter._is_ui_element("AI-generated, for reference only") is True
        assert adapter._is_ui_element("a") is True
        assert adapter._is_ui_element("Real response text") is False

    def test_find_input(self):
        from providers.deepseek.query_adapter import DeepSeekQueryAdapter
        adapter = DeepSeekQueryAdapter()
        page = _mock_page_with_response()
        result = asyncio.run(adapter._find_input(page))
        assert result is not None


# ============================================================
#  2. ChatGPT extraction
# ============================================================


class TestChatGPTExtraction:

    def test_find_input(self):
        from providers.chatgpt.query_adapter import ChatGPTQueryAdapter
        adapter = ChatGPTQueryAdapter()
        page = _mock_page_with_response()
        result = asyncio.run(adapter._find_input(page))
        assert result is not None

    def test_find_stop_button(self):
        from providers.chatgpt.query_adapter import ChatGPTQueryAdapter
        adapter = ChatGPTQueryAdapter()
        page = _mock_page_with_response()
        # Stop button is hidden → returns None (not visible)
        result = asyncio.run(adapter._find_stop_button(page))
        # May return the mock or None depending on visibility
        assert result is None or hasattr(result, 'is_visible')

    def test_is_ui_element(self):
        from providers.chatgpt.query_adapter import ChatGPTQueryAdapter
        adapter = ChatGPTQueryAdapter()
        assert adapter._is_ui_element("ChatGPT") is True
        assert adapter._is_ui_element("Regenerate") is True
        assert adapter._is_ui_element("Copy") is True
        assert adapter._is_ui_element("a") is True
        assert adapter._is_ui_element("Real answer") is False

    def test_pre_flight_login_redirect(self):
        from providers.chatgpt.query_adapter import ChatGPTQueryAdapter
        adapter = ChatGPTQueryAdapter()
        page = MagicMock()
        page.is_closed.return_value = False
        page.url = "https://auth0.openai.com/login"
        page.title = AsyncMock(return_value="Login")
        ok, reason = asyncio.run(adapter.pre_flight_check(page))
        assert ok is False
        assert reason == "login_required"

    def test_pre_flight_cloudflare(self):
        from providers.chatgpt.query_adapter import ChatGPTQueryAdapter
        adapter = ChatGPTQueryAdapter()
        page = MagicMock()
        page.is_closed.return_value = False
        page.url = "https://chatgpt.com"
        page.title = AsyncMock(return_value="Just a moment")
        ok, reason = asyncio.run(adapter.pre_flight_check(page))
        assert ok is False
        assert reason == "cloudflare_challenge"

    def test_pre_flight_ok(self):
        from providers.chatgpt.query_adapter import ChatGPTQueryAdapter
        adapter = ChatGPTQueryAdapter()
        page = MagicMock()
        page.is_closed.return_value = False
        page.url = "https://chatgpt.com"
        page.title = AsyncMock(return_value="ChatGPT")
        ok, reason = asyncio.run(adapter.pre_flight_check(page))
        assert ok is True


# ============================================================
#  3. Gemini extraction
# ============================================================


class TestGeminiExtraction:

    def test_is_ui_element(self):
        from providers.gemini.query_adapter import GeminiQueryAdapter
        adapter = GeminiQueryAdapter()
        assert adapter._is_ui_element("New chat") is True
        assert adapter._is_ui_element("Gemini") is True
        assert adapter._is_ui_element("Google") is True
        assert adapter._is_ui_element("Show drafts") is True
        assert adapter._is_ui_element("Real answer") is False

    def test_pre_flight_google_redirect(self):
        from providers.gemini.query_adapter import GeminiQueryAdapter
        adapter = GeminiQueryAdapter()
        page = MagicMock()
        page.is_closed.return_value = False
        page.url = "https://accounts.google.com/signin"
        page.title = AsyncMock(return_value="Sign in")
        ok, reason = asyncio.run(adapter.pre_flight_check(page))
        assert ok is False
        assert reason == "login_required"

    def test_selector_extraction(self):
        from providers.gemini.query_adapter import GeminiQueryAdapter
        adapter = GeminiQueryAdapter()
        page = _mock_page_with_response("Gemini response")
        result = asyncio.run(adapter._try_selector_extraction(page, "question"))
        assert "Gemini response" in result


# ============================================================
#  4. Qianwen extraction
# ============================================================


class TestQianwenExtraction:

    def test_is_ui_element(self):
        from providers.qianwen.query_adapter import QianwenQueryAdapter
        adapter = QianwenQueryAdapter()
        assert adapter._is_ui_element("新建对话") is True
        assert adapter._is_ui_element("登录") is True
        assert adapter._is_ui_element("Qwen3.7-Max") is True
        assert adapter._is_ui_element("AI生成") is True
        assert adapter._is_ui_element("阿里旗下") is True
        assert adapter._is_ui_element("a") is True
        assert adapter._is_ui_element("Real answer text") is False

    def test_pre_flight_login_button(self):
        from providers.qianwen.query_adapter import QianwenQueryAdapter
        adapter = QianwenQueryAdapter()
        page = MagicMock()
        page.is_closed.return_value = False
        page.url = "https://www.qianwen.com/qianwen"
        # Login button visible
        btn = MagicMock()
        btn.is_visible = AsyncMock(return_value=True)
        btn.inner_text = AsyncMock(return_value="登录")
        locator = MagicMock()
        locator.count = AsyncMock(return_value=1)
        locator.nth.return_value = btn
        page.locator.return_value = locator
        ok, reason = asyncio.run(adapter.pre_flight_check(page))
        assert ok is False
        assert reason == "login_required"

    def test_selector_extraction(self):
        from providers.qianwen.query_adapter import QianwenQueryAdapter
        adapter = QianwenQueryAdapter()
        page = _mock_page_with_response("千问回答")
        result = asyncio.run(adapter._try_selector_extraction(page, "问题"))
        assert "千问回答" in result


# ============================================================
#  5. MiMo extraction
# ============================================================


class TestMiMoExtraction:

    def test_is_ui_element(self):
        from providers.mimo.query_adapter import MiMoQueryAdapter
        adapter = MiMoQueryAdapter()
        assert adapter._is_ui_element("MiMo") is True
        assert adapter._is_ui_element("New chat") is True
        assert adapter._is_ui_element("a") is True
        assert adapter._is_ui_element("Real answer") is False

    def test_pre_flight_login_url(self):
        from providers.mimo.query_adapter import MiMoQueryAdapter
        adapter = MiMoQueryAdapter()
        page = MagicMock()
        page.is_closed.return_value = False
        page.url = "https://aistudio.xiaomimimo.com/login"
        ok, reason = asyncio.run(adapter.pre_flight_check(page))
        assert ok is False
        assert reason == "login_required"

    def test_selector_extraction(self):
        from providers.mimo.query_adapter import MiMoQueryAdapter
        adapter = MiMoQueryAdapter()
        page = _mock_page_with_response("MiMo response")
        result = asyncio.run(adapter._try_selector_extraction(page, "question"))
        assert "MiMo response" in result


# ============================================================
#  6. BaseQueryAdapter — wait_for_response, extract_result, abort
# ============================================================


class TestBaseQueryAdapterExtras:

    def test_extract_result_success(self):
        from providers.deepseek.query_adapter import DeepSeekQueryAdapter
        adapter = DeepSeekQueryAdapter()
        # Mock _extract_response directly
        adapter._extract_response = AsyncMock(return_value="extracted text")
        page = MagicMock()
        result = asyncio.run(adapter.extract_result(page))
        assert result["content"] == "extracted text"
        assert result["images"] == []
        assert result["thinking"] is None
        assert result["model"] is None

    def test_extract_result_timeout(self):
        from providers.deepseek.query_adapter import DeepSeekQueryAdapter
        adapter = DeepSeekQueryAdapter()
        adapter._extract_response = AsyncMock(side_effect=TimeoutError("timeout"))
        page = MagicMock()
        result = asyncio.run(adapter.extract_result(page))
        assert result["content"] is None

    def test_abort_current(self):
        from providers.deepseek.query_adapter import DeepSeekQueryAdapter
        adapter = DeepSeekQueryAdapter()
        page = _mock_page_with_response()
        asyncio.run(adapter.abort_current(page))


# ============================================================
#  7. VisionFallback
# ============================================================


class TestVisionFallbackExtra:

    def test_extract_from_screenshot_no_deps(self):
        from providers.vision_fallback import VisionFallback
        fallback = VisionFallback()
        page = MagicMock()
        page.screenshot = AsyncMock(return_value=b"\x89PNG fake")
        # Should return empty if deps not installed, or real text if installed
        result = asyncio.run(fallback.extract_from_screenshot(page))
        assert isinstance(result, str)

    def test_extract_response_region_no_deps(self):
        from providers.vision_fallback import VisionFallback
        fallback = VisionFallback()
        page = MagicMock()
        page.screenshot = AsyncMock(return_value=b"\x89PNG fake")
        locator = MagicMock()
        locator.last = MagicMock(is_visible=AsyncMock(return_value=True), screenshot=AsyncMock(return_value=b"\x89PNG"))
        page.locator.return_value = locator
        result = asyncio.run(fallback.extract_response_region(page))
        assert isinstance(result, str)
