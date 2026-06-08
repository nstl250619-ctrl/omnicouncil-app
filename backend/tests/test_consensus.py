"""Unit tests for engine/consensus/."""

from __future__ import annotations

import time


from omnicounci1l_consensus import ConsensusEngine
from omnicounci1l_consensus import (
    ConsensusReport,
)
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
    UniqueInsight,
)


def make_round_ctx(
    task_id="t1",
    query="test query",
    ai_results=None,
):
    if ai_results is None:
        ai_results = [
            AiResult(
                ai_id="deepseek", task_id=task_id, round_number=1,
                status=ResultStatus.SUCCESS, raw_text="量子计算是新型计算方式",
                normalized=NormalizedResponse(
                    main_text="量子计算是新型计算方式",
                    paragraphs=["量子计算是新型计算方式"],
                    word_count=8,
                ),
                duration=1.0,
            ),
            AiResult(
                ai_id="qianwen", task_id=task_id, round_number=1,
                status=ResultStatus.SUCCESS, raw_text="量子计算基于量子力学原理",
                normalized=NormalizedResponse(
                    main_text="量子计算基于量子力学原理",
                    paragraphs=["量子计算基于量子力学原理"],
                    word_count=7,
                ),
                duration=1.2,
            ),
        ]
    return RoundContext(
        task_id=task_id,
        round_number=1,
        query=query,
        execution_mode=TaskMode.PARALLEL,
        results=ai_results,
        summary=RoundContextSummary(
            total_ais=len(ai_results),
            success_count=sum(1 for r in ai_results if r.status == ResultStatus.SUCCESS),
        ),
        created_at=time.time(),
    )


def make_comparison_ctx(
    task_id="t1",
    query="test query",
    degraded=None,
    overall_divergence=0.2,
    differences=None,
    unique_insights=None,
):
    units = [
        SemanticUnit(unit_id="u1", source_ai_id="deepseek", content="量子计算是新型计算方式"),
        SemanticUnit(unit_id="u2", source_ai_id="qianwen", content="量子计算基于量子力学原理"),
    ]
    matrix = SimilarityMatrix(
        ai_ids=["deepseek", "qianwen"],
        pairwise_similarities=[[1.0, 0.8], [0.8, 1.0]],
        unit_matrix=[[1.0, 0.8], [0.8, 1.0]],
        unit_index=["u1", "u2"],
    )
    return ComparisonContext(
        task_id=task_id,
        round_number=1,
        query=query,
        source_context_id=f"{task_id}_r1",
        generated_at=time.time(),
        participant_ais=[("deepseek", 1), ("qianwen", 1)],
        semantic_units=units,
        similarity_matrix=matrix,
        differences=differences or [],
        unique_insights=unique_insights or [],
        metrics=ComparisonMetrics(
            total_units=2,
            overall_divergence=overall_divergence,
            pairwise_similarities=[("deepseek", "qianwen", 0.8)],
            top_difference_dimension="",
        ),
        degraded=degraded,
    )


class TestConsensusEngine:
    def test_basic_analysis(self):
        engine = ConsensusEngine()
        round_ctx = make_round_ctx()
        comp_ctx = make_comparison_ctx()

        report = engine.analyze(round_ctx, comp_ctx)

        assert isinstance(report, ConsensusReport)
        assert report.task_id == "t1"
        assert report.query == "test query"
        assert report.degraded is None
        assert report.agreement_level in ("high", "medium", "low", "divergent")

    def test_high_agreement(self):
        engine = ConsensusEngine()
        round_ctx = make_round_ctx()
        comp_ctx = make_comparison_ctx(overall_divergence=0.1)

        report = engine.analyze(round_ctx, comp_ctx)

        assert report.agreement_level == "high"
        assert report.confidence > 0.8

    def test_divergent(self):
        engine = ConsensusEngine()
        round_ctx = make_round_ctx()
        comp_ctx = make_comparison_ctx(overall_divergence=0.8)

        report = engine.analyze(round_ctx, comp_ctx)

        assert report.agreement_level == "divergent"
        assert report.confidence < 0.5

    def test_degraded_single_source(self):
        engine = ConsensusEngine()
        single_ai = [
            AiResult(
                ai_id="deepseek", task_id="t1", round_number=1,
                status=ResultStatus.SUCCESS, raw_text="response",
                normalized=NormalizedResponse(main_text="response"),
                duration=1.0,
            )
        ]
        round_ctx = make_round_ctx(ai_results=single_ai)
        comp_ctx = make_comparison_ctx()

        report = engine.analyze(round_ctx, comp_ctx)

        assert report.degraded == "single_source"
        assert report.agreement_level == "single"

    def test_degraded_no_results(self):
        engine = ConsensusEngine()
        round_ctx = make_round_ctx()
        comp_ctx = make_comparison_ctx(degraded="no_results")

        report = engine.analyze(round_ctx, comp_ctx)

        assert report.degraded == "no_results"

    def test_with_differences(self):
        engine = ConsensusEngine()
        round_ctx = make_round_ctx()
        differences = [
            DifferenceItem(
                id="d1",
                dimension="时间预期",
                involved_ais=[("deepseek", "10年"), ("qianwen", "5年")],
                strength=0.6,
                diff_type="evaluative",
            )
        ]
        comp_ctx = make_comparison_ctx(differences=differences, overall_divergence=0.4)

        report = engine.analyze(round_ctx, comp_ctx)

        assert len(report.disagreements) == 1
        assert report.disagreements[0].dimension == "时间预期"

    def test_with_unique_insights(self):
        engine = ConsensusEngine()
        round_ctx = make_round_ctx()
        insights = [
            UniqueInsight(
                unit_id="u1",
                ai_id="deepseek",
                content="独特观点",
                novelty_score=0.8,
                potential_importance="high",
            )
        ]
        comp_ctx = make_comparison_ctx(unique_insights=insights)

        report = engine.analyze(round_ctx, comp_ctx)

        assert len(report.recommendations) > 0

    def test_empty_differences(self):
        engine = ConsensusEngine()
        round_ctx = make_round_ctx()
        comp_ctx = make_comparison_ctx(differences=[], overall_divergence=0.1)

        report = engine.analyze(round_ctx, comp_ctx)

        assert len(report.disagreements) == 0
        assert report.agreement_level == "high"

    def test_report_has_recommendations(self):
        engine = ConsensusEngine()
        round_ctx = make_round_ctx()
        comp_ctx = make_comparison_ctx()

        report = engine.analyze(round_ctx, comp_ctx)

        assert len(report.recommendations) > 0

    def test_report_has_summary_stats(self):
        engine = ConsensusEngine()
        round_ctx = make_round_ctx()
        comp_ctx = make_comparison_ctx()

        report = engine.analyze(round_ctx, comp_ctx)

        assert report.summary_stats.total_ais == 2
        assert report.summary_stats.successful_ais == 2

    def test_participant_ais(self):
        engine = ConsensusEngine()
        round_ctx = make_round_ctx()
        comp_ctx = make_comparison_ctx()

        report = engine.analyze(round_ctx, comp_ctx)

        assert "deepseek" in report.participant_ais
        assert "qianwen" in report.participant_ais
