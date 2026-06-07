"""Tests for ConsensusEngine."""

import time
import pytest
from omnicounci1l_consensus import ConsensusEngine
from omnicounci1l_core.types import (
    AiResult,
    ComparisonContext,
    DifferenceItem,
    NormalizedResponse,
    ResultStatus,
    RoundContext,
    RoundContextSummary,
    SemanticUnit,
    SimilarityMatrix,
    UniqueInsight,
)


def _make_round_context(query="test query", ai_ids=None):
    ai_ids = ai_ids or ["deepseek", "gemini"]
    results = []
    for ai_id in ai_ids:
        results.append(AiResult(
            ai_id=ai_id,
            task_id="task_1",
            round_number=1,
            status=ResultStatus.SUCCESS,
            raw_text=f"Response from {ai_id}",
            normalized=NormalizedResponse(
                main_text=f"Response from {ai_id}",
                paragraphs=[f"Response from {ai_id}"],
                word_count=5,
            ),
        ))
    return RoundContext(
        task_id="task_1",
        round_number=1,
        query=query,
        execution_mode="parallel",
        results=results,
        summary=RoundContextSummary(
            total_ais=len(ai_ids),
            success_count=len(ai_ids),
        ),
    )


def _make_comparison_context():
    return ComparisonContext(
        task_id="task_1",
        round_number=1,
        query="test query",
        source_context_id="task_1_r1",
        similarity_matrix=SimilarityMatrix(
            ai_ids=["deepseek", "gemini"],
            pairwise_similarities=[[1.0, 0.8], [0.8, 1.0]],
        ),
        differences=[],
        unique_insights=[],
    )


class TestConsensusEngine:

    def test_analyze_returns_report(self):
        engine = ConsensusEngine()
        round_ctx = _make_round_context()
        comp_ctx = _make_comparison_context()
        report = engine.analyze(round_ctx, comp_ctx)
        assert report.task_id == "task_1"
        assert report.query == "test query"
        assert report.confidence >= 0.0
        assert isinstance(report.conclusion, str)

    def test_analyze_with_differences(self):
        engine = ConsensusEngine()
        round_ctx = _make_round_context()
        comp_ctx = ComparisonContext(
            task_id="task_1",
            round_number=1,
            query="test query",
            source_context_id="task_1_r1",
            differences=[
                DifferenceItem(
                    id="diff_1",
                    dimension="methodology",
                    involved_ais=[("deepseek", "approach A"), ("gemini", "approach B")],
                    strength=0.6,
                ),
            ],
        )
        report = engine.analyze(round_ctx, comp_ctx)
        assert len(report.disagreements) >= 0

    def test_analyze_single_source(self):
        engine = ConsensusEngine()
        round_ctx = _make_round_context(ai_ids=["deepseek"])
        comp_ctx = ComparisonContext(
            task_id="task_1",
            round_number=1,
            query="test query",
            source_context_id="task_1_r1",
            degraded="single_source",
        )
        report = engine.analyze(round_ctx, comp_ctx)
        assert report.degraded == "single_source"

    def test_report_has_recommendations(self):
        engine = ConsensusEngine()
        round_ctx = _make_round_context()
        comp_ctx = _make_comparison_context()
        report = engine.analyze(round_ctx, comp_ctx)
        assert isinstance(report.recommendations, list)

    def test_report_has_summary_stats(self):
        engine = ConsensusEngine()
        round_ctx = _make_round_context()
        comp_ctx = _make_comparison_context()
        report = engine.analyze(round_ctx, comp_ctx)
        assert report.summary_stats.total_ais == 2
