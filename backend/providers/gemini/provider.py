"""Gemini provider implementation.

Note: Gemini requires Google account login and may be region-restricted.
"""

from __future__ import annotations

import time
from typing import Any

from ..base import BaseProvider, ProviderConfig


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

    async def check_login(self, page: Any) -> bool:
        url = page.url
        if "accounts.google.com" in url:
            return False
        try:
            textarea = page.locator("[contenteditable='true'], textarea")
            return await textarea.count() > 0 and await textarea.first.is_visible(timeout=2000)
        except Exception:
            return False

    async def send_message(self, page: Any, message: str) -> str:
        # Find input
        input_box = None
        for sel in ["div[contenteditable='true']", "textarea"]:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=2000):
                    input_box = el
                    break
            except Exception:
                continue

        if not input_box:
            raise RuntimeError("Could not find input box for Gemini")

        await input_box.click()
        await page.wait_for_timeout(300)
        await input_box.fill(message)
        await page.wait_for_timeout(500)
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(2000)

        # Wait for response
        last_response = ""
        idle_start = None
        deadline = time.time() + 120

        while time.time() < deadline:
            body = await page.locator("body").inner_text(timeout=3000)
            lines = [l.strip() for l in body.split("\n") if l.strip()]

            prompt_idx = None
            for i, line in enumerate(lines):
                if message in line:
                    prompt_idx = i
                    break

            if prompt_idx is not None:
                response_lines = []
                for j in range(prompt_idx + 1, len(lines)):
                    candidate = lines[j]
                    if len(candidate) < 2:
                        continue
                    if any(skip in candidate for skip in ["New chat", "Gemini", "Google"]):
                        break
                    response_lines.append(candidate)
                response_text = "\n".join(response_lines) if response_lines else ""

                if response_text:
                    if response_text != last_response:
                        last_response = response_text
                        idle_start = time.time()
                    elif idle_start and (time.time() - idle_start) >= 3:
                        return response_text

            await page.wait_for_timeout(500)

        if last_response:
            return last_response
        raise TimeoutError("Gemini response timed out")
