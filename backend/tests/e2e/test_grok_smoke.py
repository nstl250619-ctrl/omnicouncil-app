"""Grok Smoke Test — inherits base tests + Grok-specific assertions."""

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


class TestGrokSmoke(ProviderSmokeTest):
    """Grok-specific smoke tests."""

    platform = "grok"
    config = PlatformConfig(
        name="grok",
        home_url="https://grok.com",
        headless=True,
        heartbeat_interval_s=60,
        max_recovery_attempts=3,
        recovery_cooldown_s=30,
        session_check_mode="offline_then_online",
        auth=AuthConfig(
            method=AuthMethod.COOKIE,
            cookie=CookieAuthConfig(
                domains=["x.com", "grok.com"],
                names=["_twitter_sess", "ct0", "auth_token"],
                match="contains",
            ),
        ),
        page=PageInteractionConfig(
            input_selectors=["textarea", "[contenteditable='true']"],
            response_selectors=["[class*='message']", "[class*='response']"],
            stop_button_selectors=["button[aria-label='Stop']"],
            ui_elements=["Grok", "New chat", "Settings", "Copy"],
            login_url_patterns=["login", "signin", "x.com/oauth"],
            cloudflare_check=True,
        ),
        capabilities=PlatformCapability(
            supports_streaming=True,
            supports_image=True,
            max_input_chars=10000,
            response_format="markdown",
        ),
    )

    async def get_test_prompt(self) -> str:
        return "What is 1+1? Reply with just the number."

    async def assert_response_valid(self, response: str) -> None:
        assert response is not None
        assert len(response) > 0
