"""Gemini query adapter — send/wait/extract for gemini.google.com."""

from __future__ import annotations

import time
from typing import Any

from providers.base.query_adapter import BaseQueryAdapter, QueryAdapterConfig


class GeminiQueryAdapter(BaseQueryAdapter):

    def config(self) -> QueryAdapterConfig:
        return QueryAdapterConfig(
            platform="gemini",
            display_name="Gemini",
            home_url="https://gemini.google.com/app",
            icon_color="#A78BFA",
            icon_emoji="💎",
        )

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

    def _is_ui_element(self, text: str) -> bool:
        ui_elements = {
            "New chat", "Gemini", "Google", "Upgrade", "Settings",
            "Help", "Activity", "Sign in", "Send", "Copy",
            "Stop", "Regenerate", "Show drafts",
        }
        return text in ui_elements or len(text) < 2

    async def _extract_response(self, page: Any, prompt: str, timeout_ms: int) -> str:
        idle_ms = 3000
        last_response = ""
        idle_start = None
        deadline = time.time() + timeout_ms / 1000

        while time.time() < deadline:
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
                    text = await elements.nth(count - 1).inner_html(timeout=2000)
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
            for i in range(len(lines) - 1, -1, -1):
                if prompt in lines[i]:
                    prompt_idx = i
                    break
            if prompt_idx is not None:
                response_lines = [ln for ln in lines[prompt_idx + 1:] if not self._is_ui_element(ln)]
                return "\n".join(response_lines) if response_lines else ""
        except Exception:
            pass
        return ""

    async def pre_flight_check(self, page: Any) -> tuple[bool, str]:
        if page.is_closed():
            return False, "page_closed"
        url = page.url
        if "accounts.google.com" in url:
            return False, "login_required"
        if "signin" in url.lower() or "login" in url.lower():
            return False, "login_required"
        try:
            title = await page.title()
            if "just a moment" in title.lower() or "cloudflare" in title.lower():
                return False, "cloudflare_challenge"
        except Exception:
            return False, "page_unresponsive"
        return True, "ok"
