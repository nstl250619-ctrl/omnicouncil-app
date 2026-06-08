"""Integration tests for V2 architecture — RuntimeRegistry + AIAccessManager.

Tests verify the new call chain:
    Scheduler → AIAccessManager → RuntimeRegistry → AIRuntimeEngine → QueryAdapter

Uses mock engines and adapters to avoid real browser operations.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from engine.contracts import QueryResult, QueryState, RuntimeState
from engine.layers.layer1_ai_access.manager import AIAccessManager
from providers.base.query_adapter import QueryAdapterConfig
from runtime.registry import RuntimeRegistry
from shared.types import AIStatus, SubmitOptions

# ============================================================
#  Helpers
# ============================================================


def _mock_engine(state: RuntimeState = RuntimeState.READY):
    """Build a mock AIRuntimeEngine that supports async ``acquire_page``.

    The V2 manager now calls ``async with engine.acquire_page() as page``
    instead of ``engine.get_page()``.  We expose a real async context
    manager that yields a MagicMock Page.
    """
    from contextlib import asynccontextmanager

    engine = MagicMock()
    engine.state = state
    engine.ensure_ready = AsyncMock(return_value=state)
    page = MagicMock()
    page.is_closed.return_value = False
    engine._mock_page = page

    @asynccontextmanager
    async def acquire_page(*, timeout: float = 30.0):
        yield page

    engine.acquire_page = acquire_page
    return engine


def _mock_adapter(success: bool = True):
    adapter = MagicMock()
    adapter.config.return_value = QueryAdapterConfig(
        platform="test", display_name="Test", home_url="https://test.com"
    )
    if success:
        adapter.execute = AsyncMock(return_value=QueryResult(
            request=MagicMock(), state=QueryState.DONE, content="response",
        ))
    else:
        adapter.execute = AsyncMock(return_value=QueryResult(
            request=MagicMock(), state=QueryState.FAILED, error="failed",
        ))
    return adapter


# ============================================================
#  1. RuntimeRegistry
# ============================================================


class TestRuntimeRegistry:

    def test_register_and_get(self):
        registry = RuntimeRegistry()
        engine = _mock_engine()
        registry.register("deepseek", engine)
        assert registry.get("deepseek") is engine

    def test_get_unknown_returns_none(self):
        registry = RuntimeRegistry()
        assert registry.get("nonexistent") is None

    def test_unregister(self):
        registry = RuntimeRegistry()
        engine = _mock_engine()
        registry.register("deepseek", engine)
        registry.unregister("deepseek")
        assert registry.get("deepseek") is None

    def test_get_all(self):
        registry = RuntimeRegistry()
        registry.register("deepseek", _mock_engine())
        registry.register("gemini", _mock_engine())
        all_engines = registry.get_all()
        assert len(all_engines) == 2

    def test_get_platforms(self):
        registry = RuntimeRegistry()
        registry.register("deepseek", _mock_engine())
        registry.register("gemini", _mock_engine())
        platforms = registry.get_platforms()
        assert set(platforms) == {"deepseek", "gemini"}

    def test_ensure_all_ready(self):
        registry = RuntimeRegistry()
        registry.register("deepseek", _mock_engine(RuntimeState.READY))
        registry.register("gemini", _mock_engine(RuntimeState.READY))
        results = asyncio.run(registry.ensure_all_ready())
        assert results["deepseek"] == RuntimeState.READY
        assert results["gemini"] == RuntimeState.READY

    def test_ensure_all_ready_with_failure(self):
        registry = RuntimeRegistry()
        good = _mock_engine(RuntimeState.READY)
        bad = _mock_engine()
        bad.ensure_ready = AsyncMock(side_effect=RuntimeError("crash"))
        registry.register("deepseek", good)
        registry.register("gemini", bad)
        results = asyncio.run(registry.ensure_all_ready())
        assert results["deepseek"] == RuntimeState.READY
        assert results["gemini"] == RuntimeState.UNAVAILABLE

    def test_shutdown_all(self):
        registry = RuntimeRegistry()
        e1 = _mock_engine()
        e2 = _mock_engine()
        registry.register("deepseek", e1)
        registry.register("gemini", e2)
        asyncio.run(registry.shutdown_all())
        e1.shutdown.assert_called_once()
        e2.shutdown.assert_called_once()
        assert len(registry) == 0

    def test_len_and_contains(self):
        registry = RuntimeRegistry()
        registry.register("deepseek", _mock_engine())
        assert len(registry) == 1
        assert "deepseek" in registry
        assert "gemini" not in registry


# ============================================================
#  2. AIAccessManager
# ============================================================


class TestAIAccessManager:

    def test_send_to_ai_success(self):
        registry = RuntimeRegistry()
        engine = _mock_engine(RuntimeState.READY)
        registry.register("deepseek", engine)
        adapter = _mock_adapter(success=True)
        manager = AIAccessManager(
            runtime_registry=registry,
            query_adapters={"deepseek": adapter},
        )

        response = asyncio.run(manager.send_to_ai("deepseek", "hello"))
        assert response.success is True
        assert response.content == "response"

    def test_send_to_ai_runtime_not_found(self):
        registry = RuntimeRegistry()
        manager = AIAccessManager(
            runtime_registry=registry,
            query_adapters={},
        )
        response = asyncio.run(manager.send_to_ai("nonexistent", "hello"))
        assert response.success is False
        assert response.error_code == "RUNTIME_NOT_FOUND"

    def test_send_to_ai_adapter_not_found(self):
        registry = RuntimeRegistry()
        registry.register("deepseek", _mock_engine())
        manager = AIAccessManager(
            runtime_registry=registry,
            query_adapters={},
        )
        response = asyncio.run(manager.send_to_ai("deepseek", "hello"))
        assert response.success is False
        assert response.error_code == "ADAPTER_NOT_FOUND"

    def test_send_to_ai_runtime_not_ready(self):
        registry = RuntimeRegistry()
        engine = _mock_engine(RuntimeState.UNAVAILABLE)
        engine.ensure_ready = AsyncMock(return_value=RuntimeState.UNAVAILABLE)
        registry.register("deepseek", engine)
        adapter = _mock_adapter()
        manager = AIAccessManager(
            runtime_registry=registry,
            query_adapters={"deepseek": adapter},
        )
        response = asyncio.run(manager.send_to_ai("deepseek", "hello"))
        assert response.success is False
        assert response.error_code == "RUNTIME_NOT_READY"

    def test_send_to_ai_query_failure(self):
        registry = RuntimeRegistry()
        registry.register("deepseek", _mock_engine())
        adapter = _mock_adapter(success=False)
        manager = AIAccessManager(
            runtime_registry=registry,
            query_adapters={"deepseek": adapter},
        )
        response = asyncio.run(manager.send_to_ai("deepseek", "hello"))
        assert response.success is False

    def test_get_ready_ais(self):
        registry = RuntimeRegistry()
        registry.register("deepseek", _mock_engine(RuntimeState.READY))
        registry.register("gemini", _mock_engine(RuntimeState.UNAVAILABLE))
        adapter = MagicMock()
        adapter.config.return_value = QueryAdapterConfig(
            platform="test", display_name="Test", home_url="https://test.com"
        )
        manager = AIAccessManager(
            runtime_registry=registry,
            query_adapters={"deepseek": adapter, "gemini": adapter},
        )
        statuses = manager.get_ready_ais()
        assert len(statuses) == 2
        ready = [s for s in statuses if s.status == AIStatus.READY]
        assert len(ready) == 1

    def test_circuit_breaker(self):
        registry = RuntimeRegistry()
        engine = _mock_engine()
        registry.register("deepseek", engine)
        adapter = _mock_adapter(success=False)
        manager = AIAccessManager(
            runtime_registry=registry,
            query_adapters={"deepseek": adapter},
        )
        # Trip the circuit breaker by failing multiple times
        for _ in range(10):
            asyncio.run(manager.send_to_ai("deepseek", "hello"))

        # Should eventually get CIRCUIT_OPEN
        response = asyncio.run(manager.send_to_ai("deepseek", "hello"))
        assert response.error_code in ("CIRCUIT_OPEN", "FAILED")


# ============================================================
#  3. End-to-end: Scheduler → AIAccessManager → Runtime → Query
# ============================================================


class TestEndToEnd:

    def test_full_chain_mock(self):
        """Verify the full call chain with mocked components."""
        registry = RuntimeRegistry()
        engine = _mock_engine(RuntimeState.READY)
        registry.register("deepseek", engine)

        adapter = _mock_adapter(success=True)
        manager = AIAccessManager(
            runtime_registry=registry,
            query_adapters={"deepseek": adapter},
        )

        # Simulate what Scheduler does
        response = asyncio.run(manager.send_to_ai(
            "deepseek", "explain quantum computing",
            options=SubmitOptions(timeout_ms=90000),
            task_id="task_test",
        ))

        assert response.success is True
        assert response.content == "response"
        engine.ensure_ready.assert_called_once()
        adapter.execute.assert_called_once()
