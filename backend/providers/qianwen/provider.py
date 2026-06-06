"""Qianwen (千问) provider implementation."""

from __future__ import annotations

import contextlib
import time
from typing import Any

from shared.errors import AILoginRequiredError

from ..base import BaseProvider, ProviderConfig


class QianwenProvider(BaseProvider):

    def config(self) -> ProviderConfig:
        return ProviderConfig(
            provider_id="qianwen",
            display_name="千问",
            login_url="https://www.qianwen.com/qianwen",
            chat_url="https://www.qianwen.com/qianwen",
            icon_color="#F59E0B",
            icon_emoji="🟠",
        )

    async def _find_input(self, page: Any) -> Any:
        """Qianwen uses contenteditable div or textarea."""
        selectors = [
            "[contenteditable='true'][role='textbox']",
            "[contenteditable='true']",
            "textarea",
        ]
        for sel in selectors:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=2000):
                    return el
            except Exception:
                continue
        return None

    async def _send_async(self, prompt: str, timeout_ms: int) -> str:
        """Qianwen-specific send flow with DOM-based auth check."""
        if not self._engine:
            raise RuntimeError("千问: no browser engine")

        cfg = self.config()
        page = await self._engine.get_page(cfg.provider_id, cfg.chat_url)
        await page.wait_for_timeout(2000)

        # DOM-based auth check (not URL-based)
        if not await self._is_logged_in(page):
            raise AILoginRequiredError(cfg.provider_id)

        # Find input
        input_box = await self._find_input(page)
        if input_box is None:
            body = ""
            with contextlib.suppress(Exception):
                body = (await page.locator("body").inner_text(timeout=3000))[:200]
            if await self._has_login_button(page):
                raise AILoginRequiredError(cfg.provider_id)
            raise RuntimeError(f"千问: could not find input box. Body: {body[:100]}")

        # Type and send
        await input_box.click()
        await page.wait_for_timeout(300)
        await input_box.fill(prompt)
        await page.wait_for_timeout(500)
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(2000)

        # Extract response via selector
        return await self._extract_response(page, prompt, timeout_ms)

    async def _is_logged_in(self, page: Any) -> bool:
        """DOM-based login detection. Checks for visible login button."""
        return not await self._has_login_button(page)

    async def _has_login_button(self, page: Any) -> bool:
        """Check if page has a visible login button."""
        try:
            # Check for visible "登录" button
            login_btns = page.locator(
                'button:has-text("登录"), '
                'a:has-text("登录"), '
                '[class*="login"]:has-text("登录")'
            )
            count = await login_btns.count()
            for i in range(count):
                btn = login_btns.nth(i)
                if await btn.is_visible():
                    text = await btn.inner_text()
                    # Exclude "用千问APP扫码登录" (hidden modal)
                    if text.strip() == "登录":
                        return True
            return False
        except Exception:
            return False

    async def _extract_response(self, page: Any, prompt: str, timeout_ms: int) -> str:
        """Qianwen response extraction using DOM selectors.

        Strategy:
        1. Try to find AI response container via selector
        2. Fallback: use body text with aggressive UI filtering
        """
        idle_ms = 3000
        last_response = ""
        idle_start = None
        deadline = time.time() + timeout_ms / 1000

        while time.time() < deadline:
            response_text = await self._try_selector_extraction(page, prompt)

            if not response_text:
                response_text = await self._try_body_extraction(page, prompt)

            if response_text:
                if response_text != last_response:
                    last_response = response_text
                    idle_start = time.time()
                elif idle_start and (time.time() - idle_start) * 1000 >= idle_ms:
                    return response_text

            await page.wait_for_timeout(500)

        if last_response:
            return last_response
        raise TimeoutError("千问 response timed out")

    async def _try_selector_extraction(self, page: Any, prompt: str) -> str:
        """Try to extract AI response via DOM selectors."""
        # Qianwen uses div with data attributes for messages
        # Try common patterns for AI response containers
        selectors = [
            # Qianwen message container patterns
            '[data-role="assistant"]',
            '[class*="assistant"]',
            '[class*="message"][class*="ai"]',
            '[class*="bot-message"]',
            '[class*="response-content"]',
            '[class*="answer-content"]',
            '[class*="markdown-container"]',
        ]

        for sel in selectors:
            try:
                elements = page.locator(sel)
                count = await elements.count()
                if count > 0:
                    # Get the last element (most recent response)
                    last_el = elements.nth(count - 1)
                    text = await last_el.inner_text(timeout=2000)
                    text = text.replace("\xa0", " ").strip()
                    if text and len(text) > 2:
                        # Filter out prompt echoes and UI elements
                        lines = [l.strip() for l in text.split("\n") if l.strip()]
                        clean_lines = [
                            l for l in lines
                            if not self._is_ui_element(l) and prompt not in l
                        ]
                        clean_text = "\n".join(clean_lines)
                        if clean_text:
                            return clean_text
            except Exception:
                continue
        return ""

    async def _try_body_extraction(self, page: Any, prompt: str) -> str:
        """Fallback: extract from body text with aggressive filtering."""
        try:
            body = await page.locator("body").inner_text(timeout=3000)
            body = body.replace("\xa0", " ")
            lines = [line.strip() for line in body.split("\n") if line.strip()]

            prompt_idx = None
            for i, line in enumerate(lines):
                if prompt in line:
                    prompt_idx = i
                    break

            if prompt_idx is not None:
                response_lines = []
                for j in range(prompt_idx + 1, len(lines)):
                    candidate = lines[j]
                    if self._is_ui_element(candidate):
                        continue
                    response_lines.append(candidate)
                return "\n".join(response_lines) if response_lines else ""
        except Exception:
            pass
        return ""

    def _is_ui_element(self, text: str) -> bool:
        """Qianwen-specific UI elements to skip."""
        ui_elements = {
            # Navigation
            "新建对话", "我的空间", "智能体", "最近对话", "关于千问",
            # Model info
            "Qwen3.7-千问", "Qwen3.7-Max", "Qwen3.7-Turbo", "API 服务", "下载电脑端",
            # Welcome
            "你好，我是千问", "向千问提问", "打招呼：你好！",
            # Features
            "任务助理", "思考", "研究", "千问高考", "PPT创作",
            "更多", "内测", "AI生图", "AI生视频", "代码",
            "翻译", "AI写作", "录音纪要", "HappyHorse",
            # Login
            "登录", "注册", "用千问APP扫码登录",
            # Footer
            "用户协议", "隐私政策", "帮助中心",
            "内容由AI生成，可能不准确，请注意核实",
            "千问 - 阿里旗下全能AI助手",
        }
        if text in ui_elements:
            return True
        # Filter short text
        if len(text) < 2:
            return True
        # Filter text that looks like a menu item
        if text.startswith("新建") or text.startswith("关于"):
            return True
        # Filter model names (Qwen + version)
        if text.startswith("Qwen") and len(text) < 20:
            return True
        # Filter AI disclaimer
        if "AI生成" in text or "不准确" in text:
            return True
        # Filter footer
        if "阿里旗下" in text or "全能AI助手" in text:
            return True
        return False

    async def check_login(self, page: Any) -> bool:
        """DOM-based login check. Returns True if logged in."""
        return await self._is_logged_in(page)
