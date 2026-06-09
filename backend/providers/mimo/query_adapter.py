"""MiMo query adapter — send/wait/extract for xiaomimimo.com."""

from __future__ import annotations

import logging
import time
from typing import Any

from providers.base.query_adapter import BaseQueryAdapter, QueryAdapterConfig

logger = logging.getLogger(__name__)


class MiMoQueryAdapter(BaseQueryAdapter):

    def config(self) -> QueryAdapterConfig:
        return QueryAdapterConfig(
            platform="mimo",
            display_name="MiMo",
            home_url="https://aistudio.xiaomimimo.com/#/",
            icon_color="#FF6900",
            icon_emoji="🟠",
        )

    async def send_prompt(self, page: Any, prompt: str) -> None:
        """MiMo-specific send with chat mode activation."""
        await self._activate_chat_mode(page)
        await super().send_prompt(page, prompt)

    async def _activate_chat_mode(self, page: Any) -> None:
        mimo_chat_labels = ["mimo chat", "MiMo Chat", "MIMO Chat", "聊天", "对话"]
        activated = False
        for label in mimo_chat_labels:
            try:
                btn = page.locator(
                    f"button:has-text('{label}'), a:has-text('{label}'), "
                    f"[class*='tab']:has-text('{label}'), [role='tab']:has-text('{label}')"
                ).first
                if await btn.is_visible(timeout=1000):
                    logger.info("MiMo: clicking '%s' to activate chat mode", label)
                    await btn.click()
                    await page.wait_for_timeout(2000)
                    activated = True
                    return
            except Exception:
                continue
        if not activated:
            # Silent fallback here is the root cause of "MiMo first responses
            # don't match the question" — the prompt gets typed into whatever
            # mode is currently active (image / docs / etc.). Surface it loudly
            # so we can see in the log when this branch fires, and capture a
            # debug snapshot to inspect the current page state.
            logger.warning(
                "MiMo: chat mode label not found, fallback to current mode "
                "(prompt may be typed into a non-chat input)"
            )
            try:
                await page.screenshot(path="/tmp/mimo_chat_mode_miss.png")
                logger.info("MiMo: debug screenshot saved to /tmp/mimo_chat_mode_miss.png")
            except Exception as exc:
                logger.debug("MiMo: failed to capture debug screenshot (%s)", exc)

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

    def _is_ui_element(self, text: str) -> bool:
        ui_elements = {
            "MiMo", "New chat", "Settings", "Sign in", "Send", "Copy",
            "Regenerate", "Help", "History",
        }
        # Filter out landing page footer/disclaimer text
        footer_patterns = [
            "Developer demo platform",
            "Not a formal AI assistant",
            "AI-generated content only",
            "Citation sources",
        ]
        if any(p in text for p in footer_patterns):
            return True
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
        if page.is_closed():
            return False, "page_closed"
        url = page.url
        if "login" in url.lower() or "signin" in url.lower() or "sign-in" in url.lower():
            return False, "login_required"

        # Check if textarea has "Sign in to continue chatting" placeholder
        try:
            textarea = page.locator("textarea").first
            if await textarea.is_visible(timeout=1000):
                placeholder = await textarea.get_attribute("placeholder") or ""
                if "sign in" in placeholder.lower():
                    return False, "login_required"
        except Exception:
            pass

        return True, "ok"
