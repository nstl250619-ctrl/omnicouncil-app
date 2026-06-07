"""Unit tests for Layer 3: Collector + Layer 4: Comparison."""

from __future__ import annotations

import asyncio
import time

import pytest

from shared.event_bus import EventBus
from shared.types import (
    AiResult,
    NormalizedResponse,
    ResultStatus,
    RoundContext,
    RoundContextSummary,
    TaskMode,
)
from engine.layers.layer3_collector.result_collector import ResultCollector
from omnicounci1l_comparison import ComparisonEngine
from omnicounci1l_comparison.similarity.cosine_similarity import cosine_similarity
from omnicounci1l_comparison.similarity.lcs_calculator import lcs_ratio
from omnicounci1l_comparison.similarity.tfidf_calculator import TfidfCalculator
from omnicounci1l_comparison.clustering.union_find import UnionFind
from shared.config import ComparisonConfig


class TestResultCollector:
    def setup_method(self):
        EventBus.reset()
        self.bus = EventBus()
        self.collector = ResultCollector(event_bus=self.bus)
        self.collector._release_ttl_seconds = 0.001

    def teardown_method(self):
        EventBus.reset()

    def test_initial_state(self):
        assert len(self.collector._contexts) == 0
        assert len(self.collector._pending) == 0

    @pytest.mark.asyncio
    async def test_on_task_dispatched(self):
        await self.bus.emit(
            "scheduler:task:dispatched",
            task_id="t1",
            selected_ai_ids=["ai1", "ai2"],
            query="test",
            mode="parallel",
        )
        assert "t1" in self.collector._expected
        assert self.collector._expected["t1"] == 2

    @pytest.mark.asyncio
    async def test_assemble_context(self):
        # Setup
        self.collector._pending["t1"] = {}
        self.collector._expected["t1"] = 1
        self.collector._queries["t1"] = "test"
        self.collector._modes["t1"] = TaskMode.PARALLEL

        result = AiResult(
            ai_id="ai1",
            task_id="t1",
            round_number=1,
            status=ResultStatus.SUCCESS,
            raw_text="response",
            normalized=NormalizedResponse(main_text="response", paragraphs=["response"], word_count=1),
        )
        self.collector._pending["t1"]["ai1"] = result

        # Trigger check
        await self.collector._check_completion("t1")

        # Should have assembled context
        ctx = self.collector.get_round_context("t1")
        assert ctx is not None
        assert ctx.task_id == "t1"
        assert len(ctx.results) == 1

    @pytest.mark.asyncio
    async def test_ttl_cleanup(self):
        # Add a context
        self.collector._contexts["t1"] = RoundContext(
            task_id="t1", round_number=1, query="q",
            execution_mode=TaskMode.PARALLEL, results=[],
            summary=RoundContextSummary(), created_at=time.time(),
        )
        self.collector._completed_at["t1"] = time.time() - 1  # 1 second ago

        # Cleanup (TTL is 0.001)
        time.sleep(0.002)
        self.collector._cleanup_completed_contexts()
        assert len(self.collector._contexts) == 0

    def test_set_query(self):
        self.collector.set_query("t1", "test query", TaskMode.PARALLEL)
        assert self.collector._queries["t1"] == "test query"


class TestCosineSimilarity:
    def test_identical_vectors(self):
        vec = {"a": 1.0, "b": 2.0}
        assert cosine_similarity(vec, vec) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        vec_a = {"a": 1.0}
        vec_b = {"b": 1.0}
        assert cosine_similarity(vec_a, vec_b) == 0.0

    def test_empty_vectors(self):
        assert cosine_similarity({}, {}) == 0.0

    def test_partial_overlap(self):
        vec_a = {"a": 1.0, "b": 1.0}
        vec_b = {"a": 1.0, "c": 1.0}
        sim = cosine_similarity(vec_a, vec_b)
        assert 0 < sim < 1


class TestLcsCalculator:
    def test_identical(self):
        assert lcs_ratio("hello", "hello") == 1.0

    def test_empty(self):
        assert lcs_ratio("", "") == 0.0

    def test_no_common(self):
        assert lcs_ratio("abc", "xyz") == 0.0

    def test_partial(self):
        ratio = lcs_ratio("abc", "ab")
        assert 0 < ratio < 1

    def test_long_text_fallback(self):
        a = "x" * 600
        b = "x" * 600
        ratio = lcs_ratio(a, b)
        assert ratio > 0  # Uses word overlap fallback


class TestTfidfCalculator:
    def test_basic(self):
        calc = TfidfCalculator()
        vectors = calc.fit_transform(["hello world", "hello there"])
        assert len(vectors) == 2
        assert len(vectors[0]) > 0

    def test_empty_docs(self):
        calc = TfidfCalculator()
        vectors = calc.fit_transform(["", ""])
        assert len(vectors) == 2

    def test_cjk_tokenization(self):
        calc = TfidfCalculator()
        vectors = calc.fit_transform(["量子计算", "量子力学"])
        assert len(vectors) == 2


class TestUnionFind:
    def test_basic(self):
        uf = UnionFind(5)
        assert uf.count == 5
        uf.union(0, 1)
        assert uf.connected(0, 1)
        assert not uf.connected(0, 2)
        assert uf.count == 4

    def test_components(self):
        uf = UnionFind(4)
        uf.union(0, 1)
        uf.union(2, 3)
        comps = uf.components()
        assert len(comps) == 2

    def test_path_compression(self):
        uf = UnionFind(5)
        uf.union(0, 1)
        uf.union(1, 2)
        assert uf.connected(0, 2)
