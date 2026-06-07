"""Gemini provider implementation."""

from __future__ import annotations

import contextlib
import logging
import time
from typing import Any

from shared.errors import AILoginRequiredError

from ..base import BaseProvider, ProviderConfig

logger = logging.getLogger(__name__)


class GeminiProvider(BaseProvider):

    def config(self) -> ProviderConfig:
        return ProviderConfig(
            provider_id="gemini",
            display_name="Gemini",
            login_url="https://gemini.google.com",
            chat_url="https://gemini.google.com/app",
            icon_color="#A78BFA",
            icon_emoji="💎",
        )

    async def _send_async(self, prompt: str, timeout_ms: int) -> str:
        """Gemini-specific send flow."""
        if not self._engine:
            raise RuntimeError("Gemini: no browser engine")

        cfg = self.config()
        page = await self._engine.get_page(cfg.provider_id, cfg.chat_url)
        await page.wait_for_timeout(3000)

        # Check login
        if not await self._is_logged_in(page):
            raise AILoginRequiredError(cfg.provider_id)

        # Find input
        input_box = await self._find_input(page)
        if input_box is None:
            if await self._has_login_redirect(page):
                raise AILoginRequiredError(cfg.provider_id)
            # Diagnostic: capture page state
            try:
                page_url = page.url
                page_title = await page.title()
                body_text = await page.locator("body").inner_text(timeout=2000)
                body_preview = body_text[:500].replace("\n", " | ")
                logger.warning(
                    "Gemini input box not found. URL=%s title=%s body_preview=%s",
                    page_url, page_title, body_preview,
                )
            except Exception as diag_err:
                logger.warning("Gemini diagnostic failed: %s", diag_err)
            raise RuntimeError("Gemini: could not find input box")

        # Type and send
        await input_box.click()
        await page.wait_for_timeout(300)
        await input_box.fill(prompt)
        await page.wait_for_timeout(500)
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(2000)

        return await self._extract_response(page, prompt, timeout_ms)

    async def _find_input(self, page: Any) -> Any:
        selectors = [
            "[contenteditable='true']",
            "div[contenteditable='true']",
            "textarea",
            "[role='textbox']",
            "main textarea",
            "gemini-app textarea",
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
        """Check if logged in via Google account."""
        url = page.url
        if url in ("about:blank", "chrome://error/", "chrome://newtab/"):
            return False
        if "accounts.google.com" in url:
            return False
        if "signin" in url.lower() or "login" in url.lower():
            return False
        # Cloudflare / challenge pages
        try:
            title = await page.title()
            if "just a moment" in title.lower() or "cloudflare" in title.lower():
                return False
        except Exception:
            return False
        return True

    async def _has_login_redirect(self, page: Any) -> bool:
        url = page.url
        return "accounts.google.com" in url or "signin" in url.lower()

    async def _extract_response(self, page: Any, prompt: str, timeout_ms: int) -> str:
        """Extract Gemini response."""
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
        raise TimeoutError("Gemini response timed out")

    async def _try_selector_extraction(self, page: Any, prompt: str) -> str:
        selectors = [
            '[data-role="assistant"]',
            '[class*="response"]',
            '[class*="model-response"]',
            '[class*="message-content"]',
            '[class*="conversation-turn"] [class*="response"]',
            '[class*="gemini"] [class*="message"]',
            '[class*="chat-message"][class*="assistant"]',
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
            # Find last occurrence of prompt (user's message)
            prompt_idx = None
            for i in range(len(lines) - 1, -1, -1):
                if prompt in lines[i]:
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
            "New chat", "Gemini", "Google", "Upgrade", "Settings",
            "Help", "Activity", "Sign in", "Send", "Copy",
            "Stop", "Regenerate", "Show drafts",
        }
        return text in ui_elements or len(text) < 2

    async def check_login(self, page: Any) -> bool:
        return await self._is_logged_in(page)
