"""DeepSeek adapter — uses BrowserEngine for page automation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..browser_adapter import BrowserAIAdapter
from browser.engine import BrowserEngine

CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "deepseek.json"


class DeepSeekBrowserAdapter(BrowserAIAdapter):
    """DeepSeek adapter using BrowserEngine.

    Handles DeepSeek-specific:
    - Input detection (textarea)
    - Response extraction (body text parsing with DeepSeek UI elements)
    - Login detection (/sign_in redirect)
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
            "aiId": "deepseek",
            "aiName": "DeepSeek",
            "url": "https://chat.deepseek.com",
            "selectors": {
                "inputBox": ["textarea"],
                "sendButton": [],
            },
            "detection": {"idleTimeoutMs": 3000, "responseMinLength": 1},
            "timing": {"afterSendWaitMs": 1500},
        }

    async def _find_input(self, page: Any) -> Any:
        """DeepSeek uses textarea for input."""
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
        """DeepSeek-specific UI elements to skip."""
        ui_elements = {
            "DeepThink", "Search", "AI-generated, for reference only",
            "Instant", "New chat", "Today", "深度思考", "联网搜索",
        }
        if text in ui_elements:
            return True
        if text.startswith("New chat") or text.startswith("Today"):
            return True
        # Skip sidebar items
        if len(text) < 3:
            return True
        return False
