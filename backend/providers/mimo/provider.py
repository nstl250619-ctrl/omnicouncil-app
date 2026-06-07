"""XiaoMiMo provider implementation.

XiaoMiMo is Xiaomi's AI assistant.
Chat URL: https://aistudio.xiaomimimo.com/#/
"""

from __future__ import annotations

import logging
import time
from typing import Any

from shared.errors import AILoginRequiredError

from ..base import BaseProvider, ProviderConfig

logger = logging.getLogger(__name__)


class XiaoMiMoProvider(BaseProvider):

    def config(self) -> ProviderConfig:
        return ProviderConfig(
            provider_id="mimo",
            display_name="MiMo",
            login_url="https://aistudio.xiaomimimo.com/#/",
            chat_url="https://aistudio.xiaomimimo.com/#/",
            icon_color="#FF6900",
            icon_emoji="🟠",
        )

    async def _send_async(self, prompt: str, timeout_ms: int) -> str:
        """MiMo-specific send flow."""
        if not self._engine:
            raise RuntimeError("MiMo: no browser engine")

        cfg = self.config()
        page = await self._engine.get_page(cfg.provider_id, cfg.chat_url)
        await page.wait_for_timeout(3000)

        if not await self._is_logged_in(page):
            raise AILoginRequiredError(cfg.provider_id)

        # Activate chat mode if on aistudio landing page
        await self._activate_chat_mode(page)

        input_box = await self._find_input(page)
        if input_box is None:
            # Diagnostic: capture page state when input box not found
            try:
                page_url = page.url
                page_title = await page.title()
                body_text = await page.locator("body").inner_text(timeout=2000)
                body_preview = body_text[:500].replace("\n", " | ")
                logger.warning(
                    "MiMo input box not found. URL=%s title=%s body_preview=%s",
                    page_url, page_title, body_preview,
                )
            except Exception as diag_err:
                logger.warning("MiMo diagnostic failed: %s", diag_err)
            raise RuntimeError("MiMo: could not find input box")

        await input_box.click()
        await page.wait_for_timeout(300)
        await input_box.fill(prompt)
        await page.wait_for_timeout(500)
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(2000)

        return await self._extract_response(page, prompt, timeout_ms)

    async def _activate_chat_mode(self, page: Any) -> None:
        """Activate the 'MiMo Chat' mode if on the aistudio landing page.

        The aistudio landing page may default to a non-chat view.
        Look for and click a 'MiMo Chat' / 'mimo chat' / '聊天' tab/button.
        This is best-effort — if no matching element is found, proceed anyway.
        """
        mimo_chat_labels = ["mimo chat", "MiMo Chat", "MIMO Chat", "聊天", "对话"]
        for label in mimo_chat_labels:
            try:
                btn = page.locator(f"button:has-text('{label}'), a:has-text('{label}'), [class*='tab']:has-text('{label}'), [role='tab']:has-text('{label}')").first
                if await btn.is_visible(timeout=1000):
                    logger.info("MiMo: clicking '%s' to activate chat mode", label)
                    await btn.click()
                    await page.wait_for_timeout(2000)
                    return
            except Exception:
                continue
        logger.info("MiMo: no chat mode button found, proceeding as-is")

    async def _find_input(self, page: Any) -> Any:
        selectors = [
            "[contenteditable='true'][role='textbox']",
            "[contenteditable='true']",
            "div[contenteditable='true']",
            "textarea",
            "[role='textbox']",
            "main textarea",
            "main [contenteditable='true']",
        ]
        for sel in selectors:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=2000):
                    return el
            except Exception:
                continue
        return None

    async def _is_logged_in(self, page: Any) -> bool:
        url = page.url
        if "login" in url.lower() or "signin" in url.lower() or "sign-in" in url.lower():
            return False
        return True

    async def _extract_response(self, page: Any, prompt: str, timeout_ms: int) -> str:
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
        raise TimeoutError("MiMo response timed out")

    async def _try_selector_extraction(self, page: Any, prompt: str) -> str:
        selectors = [
            '[data-role="assistant"]',
            '[class*="assistant"]',
            '[class*="response"]',
            '[class*="bot-message"]',
            '[class*="ai-message"]',
        ]
        for sel in selectors:
            try:
                elements = page.locator(sel)
                count = await elements.count()
                if count > 0:
                    text = await elements.nth(count - 1).inner_text(timeout=2000)
                    text = text.replace("\xa0", " ").strip()
                    if text and len(text) > 2 and prompt not in text:
                        clean = "\n".join(l for l in text.split("\n") if not self._is_ui_element(l.strip()))
                        if clean:
                            return clean
            except Exception:
                continue
        return ""

    async def _try_body_extraction(self, page: Any, prompt: str) -> str:
        try:
            body = await page.locator("body").inner_text(timeout=3000)
            body = body.replace("\xa0", " ")
            lines = [l.strip() for l in body.split("\n") if l.strip()]
            prompt_idx = None
            for i, line in enumerate(lines):
                if prompt in line:
                    prompt_idx = i
                    break
            if prompt_idx is not None:
                response_lines = [l for l in lines[prompt_idx + 1:] if not self._is_ui_element(l)]
                return "\n".join(response_lines) if response_lines else ""
        except Exception:
            pass
        return ""

    def _is_ui_element(self, text: str) -> bool:
        ui_elements = {
            "MiMo", "New chat", "Settings", "Sign in", "Send", "Copy",
            "Regenerate", "Help", "History",
        }
        return text in ui_elements or len(text) < 2

    async def check_login(self, page: Any) -> bool:
        return await self._is_logged_in(page)
