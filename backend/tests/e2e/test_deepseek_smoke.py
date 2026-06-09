"""DeepSeek Smoke Test — inherits base tests + DeepSeek-specific assertions."""

from __future__ import annotations

import pytest

from engine.contracts import (
    AuthConfig,
    AuthMethod,
    CookieAuthConfig,
    PageInteractionConfig,
    PlatformCapability,
    PlatformConfig,
)
from tests.e2e.smoke_base import ProviderSmokeTest


class TestDeepSeekSmoke(ProviderSmokeTest):
    """DeepSeek-specific smoke tests."""

    platform = "deepseek"
    config = PlatformConfig(
        name="deepseek",
        home_url="https://chat.deepseek.com",
        headless=True,
        heartbeat_interval_s=60,
        max_recovery_attempts=3,
        recovery_cooldown_s=30,
        session_check_mode="offline_then_online",
        auth=AuthConfig(
            method=AuthMethod.COOKIE,
            cookie=CookieAuthConfig(
                domains=["chat.deepseek.com"],
                names=["sessionid", "token", "auth"],
                match="prefix",
            ),
        ),
        page=PageInteractionConfig(
            input_selectors=["textarea", "div[contenteditable='true']"],
            response_selectors=["[data-role='assistant']", "[class*='response']"],
            stop_button_selectors=["button[aria-label='Stop generating']"],
            ui_elements=["DeepSeek", "New chat", "Settings", "Copy"],
            login_url_patterns=["signin", "sign-in", "login"],
            cloudflare_check=False,
        ),
        capabilities=PlatformCapability(
            supports_streaming=True,
            supports_file_upload=True,
            max_input_chars=10000,
            response_format="markdown",
        ),
    )

    async def get_test_prompt(self) -> str:
        return "What is 1+1? Reply with just the number."

    async def assert_response_valid(self, response: str) -> None:
        assert response is not None
        assert len(response) > 0
        # DeepSeek should include "2" in the response
        assert "2" in response
