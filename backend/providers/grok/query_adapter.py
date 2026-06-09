"""Grok query adapter — send/wait/extract for grok.com.

Minimal adapter: inherits BaseQueryAdapter, only overrides config().
All page interaction is config-driven via PlatformConfig.page.
"""

from __future__ import annotations

from typing import Any

from providers.base.query_adapter import BaseQueryAdapter, QueryAdapterConfig


class GrokQueryAdapter(BaseQueryAdapter):

    def config(self) -> QueryAdapterConfig:
        return QueryAdapterConfig(
            platform="grok",
            display_name="Grok",
            home_url="https://grok.com",
            icon_color="#64748b",
            icon_emoji="🤖",
        )

    async def _find_input(self, page: Any) -> Any:
        """Find input element on Grok page."""
        selectors = ["textarea", "[contenteditable='true']", "[role='textbox']"]
        for sel in selectors:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=2000):
                    return el
            except Exception:
                continue
        return None

    async def _extract_response(self, page: Any, prompt: str, timeout_ms: int) -> str:
        """Extract Grok response with idle detection."""
        import time
        idle_ms = 3000
        last_response = ""
        idle_start = None
        deadline = time.time() + timeout_ms / 1000

        while time.time() < deadline:
            response_text = await self._try_selector_extraction(page, prompt)
            if response_text:
                if response_text != last_response:
                    last_response = response_text
                    idle_start = time.time()
                elif idle_start and (time.time() - idle_start) * 1000 >= idle_ms:
                    return response_text
            await page.wait_for_timeout(500)

        if last_response:
            return last_response
        raise TimeoutError("Grok response timed out")

    async def _try_selector_extraction(self, page: Any, prompt: str) -> str:
        """Extract response using CSS selectors."""
        selectors = [
            "[data-message-author-role='assistant']",
            "[class*='message']",
            "[class*='response']",
        ]
        for sel in selectors:
            try:
                elements = page.locator(sel)
                count = await elements.count()
                if count > 0:
                    text = await elements.nth(count - 1).inner_text(timeout=2000)
                    text = text.replace("\xa0", " ").strip()
                    if text and len(text) > 2 and prompt not in text:
                        return text
            except Exception:
                continue
        return ""
