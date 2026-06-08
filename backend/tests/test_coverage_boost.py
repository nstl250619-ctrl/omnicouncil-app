"""Coverage boost tests for remaining uncovered modules."""

from __future__ import annotations

import time

import pytest

from shared.event_bus import EventBus


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


# Phase 6 remediation: TestProviderRuntimeFull removed — V1
# ProviderRuntime / BaseProvider were deleted in the architecture
# consolidation.  V2 equivalents are covered by
# test_query_adapter.py and test_runtime_engine.py.
