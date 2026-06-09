"""ChatGPT query adapter — send/wait/extract for chatgpt.com."""

from __future__ import annotations

import logging
import time
from typing import Any

from engine.contracts import SendError
from providers.base.query_adapter import BaseQueryAdapter, QueryAdapterConfig

logger = logging.getLogger(__name__)


class ChatGPTQueryAdapter(BaseQueryAdapter):

    def config(self) -> QueryAdapterConfig:
        return QueryAdapterConfig(
            platform="chatgpt",
            display_name="ChatGPT",
            home_url="https://chatgpt.com",
            icon_color="#10A37F",
            icon_emoji="🤖",
        )

    async def send_prompt(self, page: Any, prompt: str) -> None:
        """ChatGPT-specific send: wait for Cloudflare + use send button."""
        # Wait for Cloudflare challenge
        for _ in range(8):
            await page.wait_for_timeout(1000)
            page_title = await page.title()
            if "Just a moment" not in page_title and "challenge" not in page_title.lower():
                break
        else:
            logger.warning("ChatGPT: page still showing Cloudflare after 8s wait")

        input_box = await self._find_input(page)
        if input_box is None:
            # Diagnostic
            try:
                page_url = page.url
                page_title = await page.title()
                body_text = await page.locator("body").inner_text(timeout=2000)
                logger.warning(
                    "ChatGPT input box not found. URL=%s title=%s body=%s",
                    page_url, page_title, body_text[:200],
                )
            except Exception:
                pass
            raise SendError("chatgpt", "input element not found")

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

    async def _find_stop_button(self, page: Any) -> Any:
        selectors = [
            'button[aria-label="Stop generating"]',
            'button[data-testid="stop-button"]',
            'button:has-text("Stop")',
        ]
        for sel in selectors:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=500):
                    return el
            except Exception:
                continue
        return None

    def _is_ui_element(self, text: str) -> bool:
        ui_elements = {
            "ChatGPT", "Regenerate", "Copy", "Good response", "Bad response",
            "New chat", "Upgrade", "Sign in", "Send", "Stop",
        }
        return text in ui_elements or len(text) < 2

    async def _extract_response(self, page: Any, prompt: str, timeout_ms: int) -> str:
        idle_ms = 5000
        last_response = ""
        idle_start = None
        deadline = time.time() + timeout_ms / 1000

        while time.time() < deadline:
            # Check stop button
            stop_btn = await self._find_stop_button(page)
            if stop_btn is not None:
                try:
                    if await stop_btn.is_visible(timeout=500):
                        idle_start = None
                        await page.wait_for_timeout(500)
                        continue
                except Exception:
                    pass

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
                        clean = "\n".join(ln for ln in text.split("\n") if not self._is_ui_element(ln.strip()))
                        if clean:
                            return clean
            except Exception:
                continue
        return ""

    async def _try_body_extraction(self, page: Any, prompt: str) -> str:
        try:
            body = await page.locator("body").inner_text(timeout=3000)
            body = body.replace("\xa0", " ")
            lines = [ln.strip() for ln in body.split("\n") if ln.strip()]
            prompt_idx = None
            for i, line in enumerate(lines):
                if prompt in line:
                    prompt_idx = i
                    break
            if prompt_idx is not None:
                response_lines = [ln for ln in lines[prompt_idx + 1:] if not self._is_ui_element(ln)]
                return "\n".join(response_lines) if response_lines else ""
        except Exception:
            pass
        return ""

    async def pre_flight_check(self, page: Any) -> tuple[bool, str]:
        """ChatGPT-specific pre-flight with Cloudflare detection."""
        if page.is_closed():
            return False, "page_closed"

        url = page.url
        if "/auth/login" in url or "auth0.openai.com" in url or "/login" in url:
            return False, "login_required"

        try:
            title = await page.title()
            if "just a moment" in title.lower() or "cloudflare" in title.lower():
                return False, "cloudflare_challenge"
        except Exception:
            return False, "page_unresponsive"

        return True, "ok"
