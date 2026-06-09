"""Provider Smoke Test Base Class.

New providers automatically inherit base smoke tests.
Only need to override platform-specific assertions.

Usage:
    class TestDeepSeekSmoke(ProviderSmokeTest):
        platform = "deepseek"

        async def get_test_prompt(self) -> str:
            return "What is 1+1?"

        async def assert_response_valid(self, response: str) -> None:
            assert "2" in response
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Any

import pytest

from engine.contracts import PlatformConfig
from runtime.engine import AIRuntimeEngine


class ProviderSmokeTest(ABC):
    """Base class for provider smoke tests.

    Subclasses must set:
        platform: str — platform identifier
        config: PlatformConfig — platform configuration

    Subclasses should override:
        get_test_prompt() — return a test prompt
        assert_response_valid(response) — assert response is valid
    """

    platform: str
    config: PlatformConfig

    @abstractmethod
    async def get_test_prompt(self) -> str:
        """Return a test prompt for this platform."""
        ...

    @abstractmethod
    async def assert_response_valid(self, response: str) -> None:
        """Assert that the response is valid for this platform."""
        ...

    async def _make_engine(self) -> AIRuntimeEngine:
        """Create an engine for testing."""
        return AIRuntimeEngine(config=self.config)

    @pytest.mark.asyncio
    async def test_session_detection(self):
        """Test that session detection works without crashing."""
        engine = await self._make_engine()
        try:
            from runtime.session_validator import SessionValidator
            validator = engine._session_validator
            state = await validator.validate_offline()
            # Should return a valid SessionState, not crash
            assert state is not None
        finally:
            await engine.shutdown()

    @pytest.mark.asyncio
    async def test_page_interaction_config(self):
        """Test that PageInteractionConfig is properly configured."""
        assert self.config.page is not None
        assert len(self.config.page.input_selectors) > 0
        assert len(self.config.page.response_selectors) > 0

    @pytest.mark.asyncio
    async def test_auth_config(self):
        """Test that AuthConfig is properly configured."""
        assert self.config.auth is not None
        assert self.config.auth.method is not None

    @pytest.mark.asyncio
    async def test_selector_health_checker(self):
        """Test that SelectorHealthChecker works with this config."""
        from providers.selector_health import SelectorHealthChecker

        checker = SelectorHealthChecker(self.config.page)
        assert not checker.is_degraded
        assert len(checker.degraded_selectors) == 0

        # Simulate failures
        for sel in self.config.page.input_selectors:
            for _ in range(6):
                checker.record_failure(sel, "test error")

        assert checker.is_degraded
        assert len(checker.degraded_selectors) > 0

        # Simulate recovery
        for sel in self.config.page.input_selectors:
            checker.record_success(sel)

        assert not checker.is_degraded
