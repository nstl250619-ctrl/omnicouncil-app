"""Qianwen (千问) provider implementation."""

from __future__ import annotations

import time
from typing import Any

from ..base import BaseProvider, ProviderConfig


class QianwenProvider(BaseProvider):

    def config(self) -> ProviderConfig:
        return ProviderConfig(
            provider_id="qianwen",
            display_name="千问",
            login_url="https://tongyi.aliyun.com/qianwen",
            chat_url="https://tongyi.aliyun.com/qianwen",
            icon_color="#F59E0B",
            icon_emoji="🟠",
        )

    async def check_login(self, page: Any) -> bool:
        url = page.url
        if "login" in url.lower() or "sign" in url.lower():
            return False
        try:
            textarea = page.locator("textarea, [contenteditable='true']")
            if await textarea.count() > 0 and await textarea.first.is_visible(timeout=1000):
                return True
        except Exception:
            pass
        return "login" not in url and "sign" not in url and ("qianwen" in url or "tongyi" in url)

    async def send_message(self, page: Any, message: str) -> str:
        input_box = None
        for sel in ["textarea", "[contenteditable='true']", "[role='textbox']"]:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=2000):
                    input_box = el
                    break
            except Exception:
                continue

        if not input_box:
            raise RuntimeError("Could not find input box for Qianwen")

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
            body = body.replace("\xa0", " ")
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
        raise TimeoutError("Qianwen response timed out")
