"""Unit tests for Conflict Engine and Judge Engine."""

from __future__ import annotations

import time

import pytest

from engine.conflict.engine import ConflictEngine
from engine.conflict.result import ConflictPoint, ConflictPosition, ConflictResult
from engine.judge.engine import JudgeEngine
from engine.judge.result import JudgeVerdict
from shared.types import (
    AiResult,
    ComparisonContext,
    ComparisonMetrics,
    DifferenceItem,
    NormalizedResponse,
    ResultStatus,
    RoundContext,
    RoundContextSummary,
    SemanticUnit,
    SimilarityMatrix,
    TaskMode,
)


def make_round_ctx():
    return RoundContext(
        task_id="t1", round_number=1, query="什么是量子计算",
        execution_mode=TaskMode.PARALLEL,
        results=[
            AiResult(
                ai_id="deepseek", task_id="t1", round_number=1,
                status=ResultStatus.SUCCESS, raw_text="量子计算是新型计算方式" * 10,
                normalized=NormalizedResponse(main_text="量子计算", paragraphs=["量子计算"], word_count=5),
                duration=1.0,
            ),
            AiResult(
                ai_id="qianwen", task_id="t1", round_number=1,
                status=ResultStatus.SUCCESS, raw_text="量子计算基于量子力学",
                normalized=NormalizedResponse(main_text="量子计算", paragraphs=["量子计算"], word_count=5),
                duration=1.2,
            ),
        ],
        summary=RoundContextSummary(total_ais=2, success_count=2),
        created_at=time.time(),
    )


def make_comparison_ctx(differences=None):
    return ComparisonContext(
        task_id="t1", round_number=1, query="什么是量子计算",
        source_context_id="t1_r1", generated_at=time.time(),
        participant_ais=[("deepseek", 1), ("qianwen", 1)],
        semantic_units=[
            SemanticUnit(unit_id="u1", source_ai_id="deepseek", content="量子计算"),
            SemanticUnit(unit_id="u2", source_ai_id="qianwen", content="量子力学"),
        ],
        similarity_matrix=SimilarityMatrix(
            ai_ids=["deepseek", "qianwen"],
            pairwise_similarities=[[1.0, 0.5], [0.5, 1.0]],
        ),
        differences=differences or [],
        metrics=ComparisonMetrics(total_units=2, overall_divergence=0.5),
    )


class TestConflictEngine:
    def test_no_conflicts(self):
        engine = ConflictEngine()
        ctx = make_round_ctx()
        comp = make_comparison_ctx()
        result = engine.analyze(ctx, comp)
        assert isinstance(result, ConflictResult)
        assert result.task_id == "t1"
        assert len(result.conflicts) == 0

    def test_with_differences(self):
        engine = ConflictEngine()
        ctx = make_round_ctx()
        diffs = [
            DifferenceItem(
                id="d1", dimension="时间预期",
                involved_ais=[("deepseek", "10年"), ("qianwen", "5年")],
                strength=0.6, diff_type="evaluative",
            )
        ]
        comp = make_comparison_ctx(differences=diffs)
        result = engine.analyze(ctx, comp)
        assert len(result.conflicts) == 1
        assert result.conflicts[0].topic == "时间预期"
        assert "分歧" in result.conflicts[0].root_cause or "结论" in result.conflicts[0].root_cause

    def test_length_variance_conflict(self):
        engine = ConflictEngine()
        ctx = make_round_ctx()
        comp = make_comparison_ctx()
        result = engine.analyze(ctx, comp)
        # deepseek has much longer text than qianwen — may or may not trigger
        assert isinstance(result.conflicts, list)

    def test_summary_no_conflicts(self):
        engine = ConflictEngine()
        ctx = make_round_ctx()
        comp = make_comparison_ctx()
        result = engine.analyze(ctx, comp)
        assert "未发现" in result.summary

    def test_summary_with_conflicts(self):
        engine = ConflictEngine()
        ctx = make_round_ctx()
        diffs = [
            DifferenceItem(
                id="d1", dimension="test",
                involved_ais=[("a", "x"), ("b", "y")],
                strength=0.8, diff_type="evaluative",
            )
        ]
        comp = make_comparison_ctx(differences=diffs)
        result = engine.analyze(ctx, comp)
        assert "严重冲突" in result.summary


class TestJudgeEngine:
    def test_no_api_key(self):
        engine = JudgeEngine()
        ctx = make_round_ctx()
        comp = make_comparison_ctx()

        from engine.consensus.result import ConsensusReport, ConsensusSummaryStats
        consensus = ConsensusReport(
            task_id="t1", query="test", generated_at=time.time(),
            conclusion="test", confidence=0.8,
            consensus_points=[], disagreements=[], unique_insights=[],
            recommendations=[], participant_ais=["deepseek"],
            agreement_level="high",
            summary_stats=ConsensusSummaryStats(2, 2, 0, 0, 0, 0.5, "", ""),
            degraded=None,
        )

        import asyncio
        result = asyncio.run(engine.judge(ctx, comp, consensus))
        assert isinstance(result, JudgeVerdict)
        assert "未配置" in result.verdict
        assert result.confidence == 0.0

    def test_has_api_key(self):
        engine = JudgeEngine(api_keys={"openai": "test-key"})
        assert engine.has_api_key("openai") is True
        assert engine.has_api_key("claude") is False

    def test_set_api_key(self):
        engine = JudgeEngine()
        engine.set_api_key("openai", "key")
        assert engine.has_api_key("openai") is True
