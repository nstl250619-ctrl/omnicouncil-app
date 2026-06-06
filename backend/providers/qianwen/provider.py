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

    async def _find_input(self, page: Any) -> Any:
        """Qianwen uses contenteditable div or textarea."""
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
        """Qianwen-specific response extraction with non-breaking space handling."""
        idle_ms = 3000
        last_response = ""
        idle_start = None
        deadline = time.time() + timeout_ms / 1000

        while time.time() < deadline:
            body = await page.locator("body").inner_text(timeout=3000)
            body = body.replace("\xa0", " ")
            lines = [line.strip() for line in body.split("\n") if line.strip()]

            prompt_idx = None
            for i, line in enumerate(lines):
                if prompt in line:
                    prompt_idx = i
                    break

            if prompt_idx is not None:
                response_lines = []
                for j in range(prompt_idx + 1, len(lines)):
                    candidate = lines[j]
                    if self._is_ui_element(candidate):
                        continue
                    response_lines.append(candidate)
                response_text = "\n".join(response_lines) if response_lines else ""

                if response_text:
                    if response_text != last_response:
                        last_response = response_text
                        idle_start = time.time()
                    elif idle_start and (time.time() - idle_start) * 1000 >= idle_ms:
                        return response_text

            await page.wait_for_timeout(500)

        if last_response:
            return last_response
        raise TimeoutError("千问 response timed out")

    def _is_ui_element(self, text: str) -> bool:
        """Qianwen-specific UI elements to skip."""
        ui_elements = {
            "你好，我是千问", "向千问提问", "任务助理", "思考", "研究",
            "千问高考", "PPT创作", "更多", "内测", "AI生图", "代码",
            "翻译", "AI写作", "录音纪要", "HappyHorse",
        }
        if text in ui_elements:
            return True
        return len(text) < 2

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
