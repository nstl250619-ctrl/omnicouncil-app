"""ChatGPT provider implementation.

Note: ChatGPT has strong anti-bot detection. May require careful handling.
"""

from __future__ import annotations

import time
from typing import Any

from ..base import BaseProvider, ProviderConfig


class ChatGPTProvider(BaseProvider):

    def config(self) -> ProviderConfig:
        return ProviderConfig(
            provider_id="chatgpt",
            display_name="ChatGPT",
            login_url="https://chatgpt.com",
            chat_url="https://chatgpt.com",
            icon_color="#10A37F",
            icon_emoji="🤖",
        )

    async def check_login(self, page: Any) -> bool:
        url = page.url
        if "/auth/login" in url or "auth0.openai.com" in url:
            return False
        try:
            textarea = page.locator("#prompt-textarea, textarea")
            return await textarea.count() > 0 and await textarea.first.is_visible(timeout=2000)
        except Exception:
            return False

    async def send_message(self, page: Any, message: str) -> str:
        # Find input
        input_box = None
        for sel in ["#prompt-textarea", "textarea", "[contenteditable='true']"]:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=2000):
                    input_box = el
                    break
            except Exception:
                continue

        if not input_box:
            raise RuntimeError("Could not find input box for ChatGPT")

        await input_box.click()
        await page.wait_for_timeout(300)
        await input_box.fill(message)
        await page.wait_for_timeout(500)

        # Try send button first, then Enter
        send_btn = page.locator("button[data-testid='send-button']").first
        try:
            if await send_btn.is_visible(timeout=1000):
                await send_btn.click()
            else:
                await page.keyboard.press("Enter")
        except Exception:
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
                    if any(skip in candidate for skip in ["ChatGPT", "Regenerate", "Copy"]):
                        break
                    response_lines.append(candidate)
                response_text = "\n".join(response_lines) if response_lines else ""

                if response_text:
                    if response_text != last_response:
                        last_response = response_text
                        idle_start = time.time()
                    elif idle_start and (time.time() - idle_start) >= 5:
                        return response_text

            await page.wait_for_timeout(500)

        if last_response:
            return last_response
        raise TimeoutError("ChatGPT response timed out")
