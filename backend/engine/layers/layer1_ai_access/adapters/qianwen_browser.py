"""Qianwen (千问) adapter — uses BrowserEngine for page automation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..browser_adapter import BrowserAIAdapter
from browser.engine import BrowserEngine

CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "qianwen.json"


class QianwenBrowserAdapter(BrowserAIAdapter):
    """Qianwen adapter using BrowserEngine.

    Handles Qianwen-specific:
    - Input detection (contenteditable div)
    - Response extraction (body text parsing with non-breaking space handling)
    - Login detection
    """

    def __init__(self, engine: BrowserEngine):
        config = self._load_config()
        super().__init__(engine, config)

    @staticmethod
    def _load_config() -> dict:
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH) as f:
                return json.load(f)
        return {
            "aiId": "qianwen",
            "aiName": "千问",
            "url": "https://tongyi.aliyun.com/qianwen",
            "selectors": {
                "inputBox": ["textarea", "[contenteditable]", "[role=textbox]"],
                "sendButton": [],
            },
            "detection": {"idleTimeoutMs": 3000, "responseMinLength": 1},
            "timing": {"afterSendWaitMs": 2000},
        }

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
        # Qianwen uses \xa0 (non-breaking space) in text
        idle_ms = self._config.get("detection", {}).get("idleTimeoutMs", 3000)
        last_response = ""
        idle_start = None
        deadline = time.time() + timeout_ms / 1000

        while time.time() < deadline:
            body = await page.locator("body").inner_text(timeout=3000)
            # Qianwen uses non-breaking spaces
            body = body.replace("\xa0", " ")
            lines = [l.strip() for l in body.split("\n") if l.strip()]

            # Find the user's prompt
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
        if len(text) < 2:
            return True
        return False
