"""DeepSeek provider implementation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..base import BaseProvider, ProviderConfig

CONFIG_PATH = Path(__file__).parent.parent.parent / "engine" / "layers" / "layer1_ai_access" / "config" / "deepseek.json"


class DeepSeekProvider(BaseProvider):

    def config(self) -> ProviderConfig:
        return ProviderConfig(
            provider_id="deepseek",
            display_name="DeepSeek",
            login_url="https://chat.deepseek.com",
            chat_url="https://chat.deepseek.com",
            icon_color="#4F8FFF",
            icon_emoji="🔮",
        )

    async def _find_input(self, page: Any) -> Any:
        """DeepSeek uses textarea or contenteditable."""
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
        return len(text) < 3

    async def check_login(self, page: Any) -> bool:
        url = page.url
        if "/sign_in" in url:
            return False
        try:
            textarea = page.locator("textarea")
            return await textarea.count() > 0 and await textarea.first.is_visible(timeout=2000)
        except Exception:
            return False
