"""Claude provider implementation."""

from __future__ import annotations

import time
from typing import Any

from ..base import BaseProvider, ProviderConfig


class ClaudeProvider(BaseProvider):

    def config(self) -> ProviderConfig:
        return ProviderConfig(
            provider_id="claude",
            display_name="Claude",
            login_url="https://claude.ai",
            chat_url="https://claude.ai/new",
            icon_color="#D97706",
            icon_emoji="🧠",
        )

    async def check_login(self, page: Any) -> bool:
        url = page.url
        if "login" in url.lower() or "auth" in url.lower():
            return False
        try:
            textarea = page.locator("[contenteditable='true'], textarea")
            return await textarea.count() > 0 and await textarea.first.is_visible(timeout=2000)
        except Exception:
            return False

    async def send_message(self, page: Any, message: str) -> str:
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
            raise RuntimeError("Could not find input box for Claude")

        await input_box.click()
        await page.wait_for_timeout(300)
        await input_box.fill(message)
        await page.wait_for_timeout(500)
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(2000)

        last_response = ""
        idle_start = None
        deadline = time.time() + 120

        while time.time() < deadline:
            body = await page.locator("body").inner_text(timeout=3000)
            lines = [line.strip() for line in body.split("\n") if line.strip()]

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
                    if any(skip in candidate for skip in ["Claude", "Copy", "Retry"]):
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
        raise TimeoutError("Claude response timed out")
