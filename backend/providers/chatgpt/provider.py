"""OpenAI (ChatGPT) provider implementation."""

from __future__ import annotations

import logging
import time
from typing import Any

from shared.errors import AILoginRequiredError

from ..base import BaseProvider, ProviderConfig

logger = logging.getLogger(__name__)


class OpenAIProvider(BaseProvider):

    def config(self) -> ProviderConfig:
        return ProviderConfig(
            provider_id="chatgpt",
            display_name="ChatGPT",
            login_url="https://chatgpt.com",
            chat_url="https://chatgpt.com",
            icon_color="#10A37F",
            icon_emoji="🤖",
        )

    async def _send_async(self, prompt: str, timeout_ms: int) -> str:
        """ChatGPT-specific send flow."""
        if not self._engine:
            raise RuntimeError("ChatGPT: no browser engine")

        cfg = self.config()
        page = await self._engine.get_page(cfg.provider_id, cfg.chat_url)
        # Wait longer for Cloudflare challenge to complete (non-headless)
        for _ in range(8):
            await page.wait_for_timeout(1000)
            page_title = await page.title()
            if "Just a moment" not in page_title and "challenge" not in page_title.lower():
                break
        else:
            logger.warning("ChatGPT: page still showing Cloudflare after 8s wait")

        if not await self._is_logged_in(page):
            raise AILoginRequiredError(cfg.provider_id)

        input_box = await self._find_input(page)
        if input_box is None:
            if await self._has_login_redirect(page):
                raise AILoginRequiredError(cfg.provider_id)
            # Diagnostic: capture page state when input box not found
            try:
                page_url = page.url
                page_title = await page.title()
                body_text = await page.locator("body").inner_text(timeout=2000)
                body_preview = body_text[:500].replace("\n", " | ")
                logger.warning(
                    "ChatGPT input box not found. URL=%s title=%s body_preview=%s",
                    page_url, page_title, body_preview,
                )
                # Detect Cloudflare challenge
                if "Just a moment" in page_title or "challenge" in page_title.lower():
                    logger.error(
                        "ChatGPT: Cloudflare challenge detected. "
                        "Page is blocked by Cloudflare. "
                        "Suggestions: (1) re-login via visible browser in AI平台管理, "
                        "(2) install Chrome on this system for better stealth."
                    )
            except Exception as diag_err:
                logger.warning("ChatGPT diagnostic failed: %s", diag_err)

            raise RuntimeError("ChatGPT: could not find input box")

        await input_box.click()
        await page.wait_for_timeout(300)
        await input_box.fill(prompt)
        await page.wait_for_timeout(500)

        # Try send button first
        send_btn = page.locator("button[data-testid='send-button']").first
        try:
            if await send_btn.is_visible(timeout=1000):
                await send_btn.click()
            else:
                await page.keyboard.press("Enter")
        except Exception:
            await page.keyboard.press("Enter")

        await page.wait_for_timeout(2000)
        return await self._extract_response(page, prompt, timeout_ms)

    async def _find_input(self, page: Any) -> Any:
        selectors = [
            "#prompt-textarea",
            "[contenteditable='true']",
            "textarea",
            "div[contenteditable='true']",
            "[data-orientation='vertical'] textarea",
            "main textarea",
            "[role='textbox']",
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
        if url in ("about:blank", "chrome://error/", "chrome://newtab/"):
            return False
        if "/auth/login" in url or "auth0.openai.com" in url or "/login" in url:
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
        return "/auth/login" in url or "auth0.openai.com" in url or "/login" in url

    async def _extract_response(self, page: Any, prompt: str, timeout_ms: int) -> str:
        idle_ms = 5000
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
        raise TimeoutError("ChatGPT response timed out")

    async def _try_selector_extraction(self, page: Any, prompt: str) -> str:
        selectors = [
            '[data-message-author-role="assistant"]',
            '[class*="assistant-message"]',
            '[class*="markdown"]',
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
            "ChatGPT", "Regenerate", "Copy", "Good response", "Bad response",
            "New chat", "Upgrade", "Sign in", "Send", "Stop",
        }
        return text in ui_elements or len(text) < 2

    async def check_login(self, page: Any) -> bool:
        return await self._is_logged_in(page)
