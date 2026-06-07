"""Tests for ConflictEngine."""

import pytest
from omnicounci1l_conflict import ConflictEngine, ConflictResult
from omnicounci1l_core.types import (
    AiResult,
    ComparisonContext,
    DifferenceItem,
    NormalizedResponse,
    ResultStatus,
    RoundContext,
    RoundContextSummary,
)


def _make_round_context(ai_ids=None):
    ai_ids = ai_ids or ["deepseek", "gemini"]
    results = []
    for ai_id in ai_ids:
        results.append(AiResult(
            ai_id=ai_id,
            task_id="task_1",
            round_number=1,
            status=ResultStatus.SUCCESS,
            raw_text=f"Response from {ai_id} with enough text content",
            normalized=NormalizedResponse(
                main_text=f"Response from {ai_id}",
                paragraphs=[f"Response from {ai_id}"],
                word_count=10,
            ),
        ))
    return RoundContext(
        task_id="task_1",
        round_number=1,
        query="test query",
        execution_mode="parallel",
        results=results,
        summary=RoundContextSummary(
            total_ais=len(ai_ids),
            success_count=len(ai_ids),
        ),
    )


def _make_comparison_context(differences=None):
    return ComparisonContext(
        task_id="task_1",
        round_number=1,
        query="test query",
        source_context_id="task_1_r1",
        differences=differences or [],
    )


class TestConflictEngine:

    def test_no_conflicts(self):
        engine = ConflictEngine()
        round_ctx = _make_round_context()
        comp_ctx = _make_comparison_context()
        result = engine.analyze(round_ctx, comp_ctx)
        assert isinstance(result, ConflictResult)
        assert result.task_id == "task_1"
        assert result.overall_conflict_level == 0.0

    def test_with_differences(self):
        engine = ConflictEngine()
        round_ctx = _make_round_context()
        comp_ctx = _make_comparison_context(differences=[
            DifferenceItem(
                id="diff_1",
                dimension="methodology",
                involved_ais=[("deepseek", "I think approach A"), ("gemini", "I think approach B")],
                strength=0.6,
            ),
        ])
        result = engine.analyze(round_ctx, comp_ctx)
        assert len(result.conflicts) >= 1
        assert result.overall_conflict_level > 0.0

    def test_has_conflicts_property(self):
        engine = ConflictEngine()
        round_ctx = _make_round_context()
        comp_ctx = _make_comparison_context()
        result = engine.analyze(round_ctx, comp_ctx)
        assert isinstance(result.has_conflicts, bool)

    def test_summary_no_conflicts(self):
        engine = ConflictEngine()
        round_ctx = _make_round_context()
        comp_ctx = _make_comparison_context()
        result = engine.analyze(round_ctx, comp_ctx)
        assert "未发现" in result.summary or "一致" in result.summary

    def test_factual_difference_root_cause(self):
        engine = ConflictEngine()
        round_ctx = _make_round_context()
        comp_ctx = _make_comparison_context(differences=[
            DifferenceItem(
                id="diff_1",
                dimension="数据来源",
                involved_ais=[("deepseek", "根据数据统计"), ("gemini", "根据数据来源不同")],
                strength=0.5,
            ),
        ])
        result = engine.analyze(round_ctx, comp_ctx)
        assert len(result.conflicts) >= 1
        assert "事实性" in result.conflicts[0].root_cause or "数据" in result.conflicts[0].root_cause
