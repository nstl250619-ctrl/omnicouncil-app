"""DeepSeek query adapter — send/wait/extract for chat.deepseek.com."""

from __future__ import annotations

import time
from typing import Any

from providers.base.query_adapter import BaseQueryAdapter, QueryAdapterConfig


class DeepSeekQueryAdapter(BaseQueryAdapter):

    def config(self) -> QueryAdapterConfig:
        return QueryAdapterConfig(
            platform="deepseek",
            display_name="DeepSeek",
            home_url="https://chat.deepseek.com",
            icon_color="#4F8FFF",
            icon_emoji="🔮",
        )

    async def _find_input(self, page: Any) -> Any:
        selectors = ["textarea", "div[contenteditable='true']"]
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
            "DeepThink", "Search", "AI-generated, for reference only",
            "Instant", "New chat", "Today", "深度思考", "联网搜索",
        }
        if text in ui_elements:
            return True
        if text.startswith("New chat") or text.startswith("Today"):
            return True
        return len(text) < 3

    async def _extract_response(self, page: Any, prompt: str, timeout_ms: int) -> str:
        idle_ms = 3000
        last_response = ""
        idle_start = None
        deadline = time.time() + timeout_ms / 1000

        while time.time() < deadline:
            # Check stop button first
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
        raise TimeoutError("DeepSeek response timed out")

    async def _try_selector_extraction(self, page: Any, prompt: str) -> str:
        selectors = [
            '[data-message-author-role="assistant"]',
            '[class*="ds-message"]',
            '[class*="assistant"]',
            '[class*="message"]:not([class*="user"]):not([class*="input"])',
            '[class*="response"]',
            '[class*="markdown"]',
        ]
        for sel in selectors:
            try:
                elements = page.locator(sel)
                count = await elements.count()
                if count > 0:
                    last_el = elements.nth(count - 1)
                    text = await last_el.inner_text(timeout=2000)
                    text = text.replace("\xa0", " ").strip()
                    if text and len(text) > 2 and prompt not in text:
                        clean = "\n".join(
                            ln for ln in text.split("\n")
                            if not self._is_ui_element(ln.strip())
                        )
                        if clean:
                            return clean
            except Exception:
                continue
        return ""

    async def _try_body_extraction(self, page: Any, prompt: str) -> str:
        try:
            body = await page.locator("body").inner_text(timeout=3000)
            body = body.replace("\xa0", " ")
            lines = [line.strip() for line in body.split("\n") if line.strip()]

            prompt_idx = None
            for i in range(len(lines) - 1, -1, -1):
                if prompt in lines[i]:
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
