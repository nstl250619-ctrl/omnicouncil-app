"""Coverage boost tests for remaining uncovered modules."""

from __future__ import annotations

import asyncio
import time

import pytest

from shared.event_bus import EventBus
from shared.types import AIStatus, ProviderStatus


class TestAIAccessManager:
    """Tests for engine/layers/layer1_ai_access/manager.py."""

    @pytest.mark.asyncio
    async def test_register_adapter(self):
        from engine.layers.layer1_ai_access.manager import AIAccessManager

        EventBus.reset()
        bus = EventBus()
        manager = AIAccessManager(event_bus=bus)

        class FakeAdapter:
            ai_id = "fake"
            ai_name = "Fake"
            _status = AIStatus.INITIALIZING

            def get_status(self):
                return ProviderStatus(ai_id="fake", ai_name="Fake", status=self._status)

            async def initialize(self):
                self._status = AIStatus.READY

            async def destroy(self):
                self._status = AIStatus.INITIALIZING

            async def send_prompt(self, prompt, options=None):
                from shared.types import AIResponse
                return AIResponse(
                    success=True, ai_id="fake", task_id="t1",
                    content="response", model="fake",
                    timestamp=time.time(), duration=1.0, word_count=1,
                )

            async def stop_generation(self):
                pass

        adapter = FakeAdapter()
        manager.register_adapter(adapter)

        assert manager._provider_manager.get("fake") is not None

        await manager.initialize()
        ais = manager.get_ready_ais()
        assert len(ais) == 1

        # send_to_ai
        resp = await manager.send_to_ai("fake", "hello", task_id="t1")
        assert resp.success is True

        # send_to_nonexistent
        resp = await manager.send_to_ai("nonexistent", "hello")
        assert resp.success is False
        assert resp.error_code == "ADAPTER_NOT_FOUND"

        # stop_generation
        await manager.stop_generation("fake")

        await manager.destroy()
        EventBus.reset()


class TestInstrumentationFull:
    """Tests for shared/instrumentation.py — full event flow."""

    def setup_method(self):
        EventBus.reset()
        from shared.trace import TraceStore
        from shared.metrics import MetricsCollector
        TraceStore.reset()
        MetricsCollector.reset()

    def teardown_method(self):
        EventBus.reset()
        from shared.trace import TraceStore
        from shared.metrics import MetricsCollector
        TraceStore.reset()
        MetricsCollector.reset()

    @pytest.mark.asyncio
    async def test_full_event_flow(self):
        from shared.instrumentation import Instrumentation
        from shared.trace import TraceStore
        from shared.metrics import MetricsCollector
        from shared.types import AIResponse

        bus = EventBus()
        inst = Instrumentation(bus, tracing_enabled=True, metrics_enabled=True)
        inst.install()

        # Simulate task lifecycle
        await bus.emit("scheduler:task:created",
            task_id="t1", selected_ai_ids=["deepseek"], mode="parallel", query="test")
        await bus.emit("scheduler:task:dispatched",
            task_id="t1", selected_ai_ids=["deepseek"], query="test", mode="parallel")

        resp = AIResponse(
            success=True, ai_id="deepseek", task_id="t1",
            content="response", model="deepseek",
            timestamp=time.time(), duration=1.0, word_count=1,
        )
        await bus.emit("ai:task:completed", task_id="t1", ai_id="deepseek", response=resp)

        # Check trace
        trace = TraceStore.instance().get("t1")
        assert trace is not None
        assert len(trace.events) >= 2

        # Check metrics
        metrics = MetricsCollector.instance()
        assert metrics._counters.get("requests_total", 0) >= 1
        assert metrics._counters.get("requests_success", 0) >= 1


class TestDifferenceAnalyzerFull:
    """Tests for engine/layers/layer4_comparison/pipeline/difference_analyzer.py."""

    def test_detect_with_clusters(self):
        from omnicounci1l_comparison.pipeline.difference_analyzer import DifferenceAnalyzer
        from shared.config import ComparisonConfig
        from shared.types import SemanticUnit, SimilarityMatrix

        config = ComparisonConfig(similarity_threshold=0.5, difference_trigger=0.3)
        analyzer = DifferenceAnalyzer(config)

        units = [
            SemanticUnit(unit_id="u1", source_ai_id="a", content="量子计算是好的技术"),
            SemanticUnit(unit_id="u2", source_ai_id="b", content="量子计算有风险"),
            SemanticUnit(unit_id="u3", source_ai_id="a", content="量子计算需要时间"),
            SemanticUnit(unit_id="u4", source_ai_id="b", content="量子计算很快"),
        ]
        matrix = SimilarityMatrix(
            ai_ids=["a", "b"],
            pairwise_similarities=[[1.0, 0.3], [0.3, 1.0]],
            unit_matrix=[
                [1.0, 0.8, 0.6, 0.2],
                [0.8, 1.0, 0.3, 0.7],
                [0.6, 0.3, 1.0, 0.4],
                [0.2, 0.7, 0.4, 1.0],
            ],
            unit_index=["u1", "u2", "u3", "u4"],
        )

        differences = analyzer.detect(units, matrix)
        assert isinstance(differences, list)

    def test_extract_dimension(self):
        from omnicounci1l_comparison.pipeline.difference_analyzer import DifferenceAnalyzer
        from shared.config import ComparisonConfig

        analyzer = DifferenceAnalyzer(ComparisonConfig())
        dim = analyzer._extract_dimension("量子计算是未来技术 量子计算很强大")
        assert isinstance(dim, str)
        assert len(dim) > 0

    def test_classify_type(self):
        from omnicounci1l_comparison.pipeline.difference_analyzer import DifferenceAnalyzer
        from shared.config import ComparisonConfig

        analyzer = DifferenceAnalyzer(ComparisonConfig())
        assert analyzer._classify_type("根据数据和统计") == "factual"
        assert analyzer._classify_type("方法策略步骤") == "methodological"
        assert analyzer._classify_type("优势风险好坏") == "evaluative"
        assert analyzer._classify_type("建议推荐应该") == "recommendational"


class TestProviderRuntimeFull:
    """Additional tests for providers/runtime.py."""

    @pytest.mark.asyncio
    async def test_send_with_login_fallback(self):
        from providers.runtime import ProviderRuntime
        from providers.base.provider import BaseProvider, ProviderConfig
        from shared.types import AIResponse

        runtime = ProviderRuntime()

        class P(BaseProvider):
            def config(self):
                return ProviderConfig(provider_id="p", display_name="P", login_url="x", chat_url="x")

            async def _send_async(self, prompt, timeout_ms):
                return "ok"

            def is_authenticated(self):
                return True

        p = P()
        await runtime.register(p)
        await runtime.initialize_all()

        result = await runtime.send("p", "hello")
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_send_error_provider(self):
        from providers.runtime import ProviderRuntime
        from providers.base.provider import BaseProvider, ProviderConfig

        runtime = ProviderRuntime()

        class P(BaseProvider):
            def config(self):
                return ProviderConfig(provider_id="p", display_name="P", login_url="x", chat_url="x")

            async def _send_async(self, prompt, timeout_ms):
                raise RuntimeError("boom")

        p = P()
        await runtime.register(p)
        await runtime.initialize_all()

        with pytest.raises(RuntimeError):
            await runtime.send("p", "hello")

    @pytest.mark.asyncio
    async def test_send_nonexistent_provider(self):
        from providers.runtime import ProviderRuntime

        runtime = ProviderRuntime()
        with pytest.raises(ValueError):
            await runtime.send("nonexistent", "hello")

    @pytest.mark.asyncio
    async def test_health_check_all(self):
        from providers.runtime import ProviderRuntime
        from providers.base.provider import BaseProvider, ProviderConfig

        runtime = ProviderRuntime()

        class P(BaseProvider):
            def __init__(self, pid, name):
                super().__init__()
                self._pid = pid
                self._name = name

            def config(self):
                return ProviderConfig(provider_id=self._pid, display_name=self._name, login_url="x", chat_url="x")

        await runtime.register(P("a", "A"))
        await runtime.register(P("b", "B"))
        await runtime.initialize_all()

        reports = await runtime.health_check_all()
        assert len(reports) == 2

    @pytest.mark.asyncio
    async def test_destroy_all(self):
        from providers.runtime import ProviderRuntime
        from providers.base.provider import BaseProvider, ProviderConfig

        runtime = ProviderRuntime()

        class P(BaseProvider):
            def config(self):
                return ProviderConfig(provider_id="p", display_name="P", login_url="x", chat_url="x")

        await runtime.register(P())
        await runtime.initialize_all()
        await runtime.destroy_all()
        assert len(runtime._initialized) == 0
