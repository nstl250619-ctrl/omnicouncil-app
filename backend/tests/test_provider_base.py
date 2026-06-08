"""Unit tests for providers/base/provider.py — BaseProvider."""

from __future__ import annotations

import pytest

from providers.base.provider import BaseProvider, ProviderConfig
from shared.types import AIStatus, ProviderStatus


def make_provider(pid="test", name="Test"):
    class P(BaseProvider):
        def config(self):
            return ProviderConfig(
                provider_id=pid,
                display_name=name,
                login_url="https://example.com",
                chat_url="https://example.com",
            )

        async def _send_async(self, prompt, timeout_ms):
            return f"response: {prompt}"

    return P()


class TestProviderConfig:
    def test_defaults(self):
        cfg = ProviderConfig(provider_id="p1", display_name="P1", login_url="x", chat_url="x")
        assert cfg.enabled is True
        assert cfg.max_concurrent == 1
        assert cfg.timeout_ms == 120000

    def test_custom(self):
        cfg = ProviderConfig(
            provider_id="p1", display_name="P1", login_url="x", chat_url="x",
            icon_color="#FF0000", icon_emoji="🔴",
        )
        assert cfg.icon_color == "#FF0000"
        assert cfg.icon_emoji == "🔴"


class TestBaseProvider:
    def test_ai_id(self):
        p = make_provider("deepseek", "DeepSeek")
        assert p.ai_id == "deepseek"

    def test_ai_name(self):
        p = make_provider("deepseek", "DeepSeek")
        assert p.ai_name == "DeepSeek"

    def test_initial_status(self):
        p = make_provider()
        assert p._status == AIStatus.INITIALIZING

    @pytest.mark.asyncio
    async def test_initialize(self):
        p = make_provider()
        await p.initialize()
        assert p._status == AIStatus.READY

    @pytest.mark.asyncio
    async def test_destroy(self):
        p = make_provider()
        await p.initialize()
        await p.destroy()
        assert p._status == AIStatus.INITIALIZING

    def test_get_status(self):
        p = make_provider()
        ps = p.get_status()
        assert isinstance(ps, ProviderStatus)
        assert ps.ai_id == "test"
        assert ps.ai_name == "Test"

    def test_is_ready_false_initially(self):
        p = make_provider()
        assert p.is_ready() is False

    @pytest.mark.asyncio
    async def test_is_ready_after_initialize(self):
        p = make_provider()
        await p.initialize()
        assert p.is_ready() is True

    @pytest.mark.asyncio
    async def test_send_prompt_success(self):
        p = make_provider()
        await p.initialize()
        resp = await p.send_prompt("hello")
        assert resp.success is True
        assert "hello" in resp.content
        assert resp.ai_id == "test"

    @pytest.mark.asyncio
    async def test_send_prompt_stores_status(self):
        p = make_provider()
        await p.initialize()
        resp = await p.send_prompt("hello")
        assert p._status == AIStatus.READY
        assert p._consecutive_failures == 0

    @pytest.mark.asyncio
    async def test_send_prompt_failure(self):
        class FailProvider(BaseProvider):
            def config(self):
                return ProviderConfig(provider_id="f", display_name="F", login_url="x", chat_url="x")

            async def _send_async(self, prompt, timeout_ms):
                raise RuntimeError("boom")

        p = FailProvider()
        await p.initialize()
        resp = await p.send_prompt("hello")
        assert resp.success is False
        assert resp.error_code == "RuntimeError"
        assert p._consecutive_failures == 1

    @pytest.mark.asyncio
    async def test_health_check(self):
        p = make_provider()
        await p.initialize()
        health = await p.health_check()
        assert health["status"] == "healthy"
        assert health["login_valid"] is True

    @pytest.mark.asyncio
    async def test_health_check_login_required(self):
        p = make_provider()
        p._status = AIStatus.LOGIN_REQUIRED
        health = await p.health_check()
        assert health["status"] == "degraded"
        assert health["login_valid"] is False

    def test_is_authenticated_no_engine(self):
        p = make_provider()
        assert p.is_authenticated() is False

    @pytest.mark.asyncio
    async def test_login_no_engine(self):
        p = make_provider()
        success, error = await p.login()
        assert success is False
        assert "No browser engine" in error

    @pytest.mark.asyncio
    async def test_stop_generation(self):
        p = make_provider()
        await p.stop_generation()  # Should not raise

    @pytest.mark.asyncio
    async def test_new_conversation_no_engine(self):
        p = make_provider()
        await p.new_conversation()  # Should not raise

    def test_count_words(self):
        assert BaseProvider.count_words("hello world") == 2
        assert BaseProvider.count_words("") == 0
        assert BaseProvider.count_words("量子计算") == 4
