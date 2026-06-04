"""DeepSeek adapter."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from .base import AIAdapter, AIConfig


class DeepSeekAdapter(AIAdapter):

    def config(self) -> AIConfig:
        return AIConfig(
            ai_id="deepseek",
            display_name="DeepSeek",
            login_url="https://chat.deepseek.com",
            chat_url="https://chat.deepseek.com",
            icon_color="#4F8FFF",
        )

    async def check_login(self, page: Any) -> bool:
        url = page.url
        if "/sign_in" in url:
            return False
        try:
            textarea = page.locator("textarea")
            return await textarea.count() > 0 and await textarea.first.is_visible(timeout=2000)
        except Exception:
            return False

    async def send_message(self, page: Any, message: str) -> str:
        # Find input
        input_box = page.locator("textarea").first
        await input_box.click()
        await page.wait_for_timeout(300)
        await input_box.fill(message)
        await page.wait_for_timeout(500)
        await page.keyboard.press("Enter")

        # Wait for response
        await page.wait_for_timeout(2000)

        # Extract response via body text parsing
        last_response = ""
        idle_start = None
        deadline = time.time() + 120
        ui_skip = {"DeepThink", "Search", "AI-generated, for reference only", "Instant", "New chat", "Today"}

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
                    if candidate in ui_skip:
                        continue
                    if candidate in ("DeepThink", "Search"):
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
        raise TimeoutError("DeepSeek response timed out")

    def get_input_selector(self) -> str:
        return "textarea"
