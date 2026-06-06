"""Unit tests for Provider Runtime components."""

from __future__ import annotations

import asyncio

import pytest

from providers.runtime import ProviderRuntime
from providers.registry_v2 import ProviderRegistryV2
from providers.session_manager import ProviderSessionManager
from providers.health_monitor import HealthStatus, ProviderHealthMonitor
from providers.event_bus import ProviderEventBus, PROVIDER_REGISTERED, PROVIDER_UNREGISTERED
from providers.errors import (
    ProviderError,
    LoginRequiredError,
    ProviderTimeoutError,
    ExtractionFailedError,
    SessionInvalidError,
    ProviderDisabledError,
)
from providers.base.provider import BaseProvider, ProviderConfig
from shared.types import AIStatus


def make_provider(pid="test", name="Test"):
    class P(BaseProvider):
        def __init__(self):
            super().__init__()
            self._pid = pid
            self._name = name

        def config(self):
            return ProviderConfig(
                provider_id=self._pid,
                display_name=self._name,
                login_url="https://example.com",
                chat_url="https://example.com",
            )

        async def _send_async(self, prompt, timeout_ms):
            return f"response to: {prompt}"

    return P()


class TestProviderErrors:
    def test_provider_error(self):
        e = ProviderError("CODE", "msg", "ai1", True)
        assert e.code == "CODE"
        assert e.provider_id == "ai1"
        assert e.recoverable is True

    def test_login_required_error(self):
        e = LoginRequiredError("deepseek")
        assert e.code == "LOGIN_REQUIRED"
        assert e.recoverable is True

    def test_timeout_error(self):
        e = ProviderTimeoutError("deepseek", 5000)
        assert e.code == "TIMEOUT"

    def test_extraction_failed_error(self):
        e = ExtractionFailedError("deepseek", "no content")
        assert e.code == "EXTRACTION_FAILED"

    def test_session_invalid_error(self):
        e = SessionInvalidError("deepseek")
        assert e.code == "SESSION_INVALID"

    def test_provider_disabled_error(self):
        e = ProviderDisabledError("deepseek")
        assert e.code == "PROVIDER_DISABLED"
        assert e.recoverable is False


class TestProviderRegistryV2:
    def test_register_and_get(self):
        reg = ProviderRegistryV2()
        p = make_provider()
        reg.register(p)
        assert reg.get("test") is p

    def test_unregister(self):
        reg = ProviderRegistryV2()
        reg.register(make_provider())
        assert reg.unregister("test") is True
        assert reg.get("test") is None

    def test_unregister_nonexistent(self):
        reg = ProviderRegistryV2()
        assert reg.unregister("nonexistent") is False

    def test_get_all(self):
        reg = ProviderRegistryV2()
        reg.register(make_provider("a", "A"))
        reg.register(make_provider("b", "B"))
        assert len(reg.get_all()) == 2

    def test_get_ids(self):
        reg = ProviderRegistryV2()
        reg.register(make_provider("a", "A"))
        reg.register(make_provider("b", "B"))
        assert set(reg.get_ids()) == {"a", "b"}

    def test_status_management(self):
        reg = ProviderRegistryV2()
        reg.register(make_provider())
        reg.set_status("test", AIStatus.READY)
        assert reg.get_status("test") == AIStatus.READY

    def test_get_configs(self):
        reg = ProviderRegistryV2()
        reg.register(make_provider())
        configs = reg.get_configs()
        assert len(configs) == 1
        assert configs[0]["provider_id"] == "test"


class TestProviderSessionManager:
    def test_has_session_false_for_nonexistent(self):
        sm = ProviderSessionManager(base_dir="/tmp/omnicouncil_test_sm")
        assert sm.has_session("nonexistent") is False

    def test_get_profile_dir(self):
        sm = ProviderSessionManager(base_dir="/tmp/omnicouncil_test_sm")
        path = sm.get_profile_dir("test")
        assert "test_profile" in path

    def test_save_and_load_meta(self):
        sm = ProviderSessionManager(base_dir="/tmp/omnicouncil_test_sm")
        sm.save_session_meta("test", {"key": "value"})
        meta = sm.load_session_meta("test")
        assert meta is not None
        assert meta["key"] == "value"

    def test_load_nonexistent_meta(self):
        sm = ProviderSessionManager(base_dir="/tmp/omnicouncil_test_sm")
        assert sm.load_session_meta("nonexistent") is None

    def test_invalidate_session(self):
        sm = ProviderSessionManager(base_dir="/tmp/omnicouncil_test_sm")
        sm.save_session_meta("test", {"key": "value"})
        sm.invalidate_session("test")
        assert sm.load_session_meta("test") is None

    def test_list_sessions(self):
        sm = ProviderSessionManager(base_dir="/tmp/omnicouncil_test_sm")
        sm.save_session_meta("a", {"a": 1})
        sm.save_session_meta("b", {"b": 2})
        sessions = sm.list_sessions()
        assert len(sessions) >= 2


class TestProviderHealthMonitor:
    @pytest.mark.asyncio
    async def test_check_healthy_provider(self):
        hm = ProviderHealthMonitor()
        p = make_provider()
        p._status = AIStatus.READY
        report = await hm.check(p)
        assert report.status == HealthStatus.HEALTHY
        assert report.login_valid is True

    @pytest.mark.asyncio
    async def test_check_login_required(self):
        hm = ProviderHealthMonitor()
        p = make_provider()
        p._status = AIStatus.LOGIN_REQUIRED
        report = await hm.check(p)
        assert report.status == HealthStatus.DEGRADED
        assert report.login_valid is False

    @pytest.mark.asyncio
    async def test_check_error_provider(self):
        hm = ProviderHealthMonitor()
        p = make_provider()
        p._status = AIStatus.ERROR
        report = await hm.check(p)
        assert report.status == HealthStatus.FAILED

    @pytest.mark.asyncio
    async def test_check_all(self):
        hm = ProviderHealthMonitor()
        p1 = make_provider("a", "A")
        p2 = make_provider("b", "B")
        p1._status = AIStatus.READY
        p2._status = AIStatus.READY
        reports = await hm.check_all([p1, p2])
        assert len(reports) == 2

    def test_is_healthy_unknown(self):
        hm = ProviderHealthMonitor()
        assert hm.is_healthy("nonexistent") is False


class TestProviderEventBus:
    @pytest.mark.asyncio
    async def test_emit_and_on(self):
        bus = ProviderEventBus()
        received = []

        async def handler(**kwargs):
            received.append(kwargs)

        bus.on(PROVIDER_REGISTERED, handler)
        await bus.emit(PROVIDER_REGISTERED, provider_id="test")
        assert len(received) == 1
        assert received[0]["provider_id"] == "test"

    @pytest.mark.asyncio
    async def test_off(self):
        bus = ProviderEventBus()
        count = [0]

        async def handler(**kwargs):
            count[0] += 1

        bus.on(PROVIDER_REGISTERED, handler)
        bus.off(PROVIDER_REGISTERED, handler)
        await bus.emit(PROVIDER_REGISTERED, provider_id="test")
        assert count[0] == 0

    @pytest.mark.asyncio
    async def test_handler_exception_does_not_propagate(self):
        bus = ProviderEventBus()

        async def bad_handler(**kwargs):
            raise RuntimeError("boom")

        bus.on(PROVIDER_REGISTERED, bad_handler)
        await bus.emit(PROVIDER_REGISTERED, provider_id="test")  # Should not raise


class TestProviderRuntime:
    @pytest.mark.asyncio
    async def test_register_and_get(self):
        runtime = ProviderRuntime()
        p = make_provider()
        await runtime.register(p)
        assert runtime.registry.get("test") is p

    @pytest.mark.asyncio
    async def test_initialize_all(self):
        runtime = ProviderRuntime()
        p = make_provider()
        await runtime.register(p)
        await runtime.initialize_all()
        assert runtime.registry.get_status("test") == AIStatus.READY

    @pytest.mark.asyncio
    async def test_unregister(self):
        runtime = ProviderRuntime()
        p = make_provider()
        await runtime.register(p)
        await runtime.unregister("test")
        assert runtime.registry.get("test") is None

    @pytest.mark.asyncio
    async def test_reload(self):
        runtime = ProviderRuntime()
        p1 = make_provider("test", "V1")
        await runtime.register(p1)
        await runtime.initialize_all()

        p2 = make_provider("test", "V2")
        ok = await runtime.reload("test", p2)
        assert ok is True
        assert runtime.registry.get("test").config().display_name == "V2"

    @pytest.mark.asyncio
    async def test_health_check(self):
        runtime = ProviderRuntime()
        p = make_provider()
        await runtime.register(p)
        await runtime.initialize_all()
        report = await runtime.health_check("test")
        assert report.status == HealthStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_get_configs(self):
        runtime = ProviderRuntime()
        await runtime.register(make_provider())
        configs = runtime.get_configs()
        assert len(configs) == 1
