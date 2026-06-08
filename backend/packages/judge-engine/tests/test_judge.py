"""Tests for JudgeEngine."""

import asyncio
from omnicounci1l_judge import JudgeEngine, JudgeVerdict
from omnicounci1l_core.types import (
    AiResult,
    ComparisonContext,
    NormalizedResponse,
    ResultStatus,
    RoundContext,
    RoundContextSummary,
)


def _make_round_context():
    return RoundContext(
        task_id="task_1",
        round_number=1,
        query="test query",
        execution_mode="parallel",
        results=[
            AiResult(
                ai_id="deepseek", task_id="task_1", round_number=1,
                status=ResultStatus.SUCCESS,
                raw_text="Response from deepseek",
                normalized=NormalizedResponse(main_text="Response", paragraphs=["Response"], word_count=1),
            ),
        ],
        summary=RoundContextSummary(total_ais=1, success_count=1),
    )


def _make_comparison_context():
    return ComparisonContext(
        task_id="task_1", round_number=1, query="test query",
        source_context_id="task_1_r1",
    )


def _make_consensus_report():
    from omnicounci1l_consensus import ConsensusReport, ConsensusSummaryStats
    return ConsensusReport(
        task_id="task_1", query="test query", generated_at=0,
        conclusion="Test conclusion", confidence=0.8,
        consensus_points=[], disagreements=[], unique_insights=[],
        recommendations=[], participant_ais=["deepseek"],
        agreement_level="high",
        summary_stats=ConsensusSummaryStats(
            total_ais=1, successful_ais=1,
            total_consensus_points=0, total_disagreements=0,
            total_unique_insights=0, avg_pairwise_similarity=1.0,
            top_agreement_dimension="", top_disagreement_dimension="",
        ),
        degraded=None,
    )


class TestJudgeEngine:

    def test_no_api_key_returns_degraded(self):
        engine = JudgeEngine()
        round_ctx = _make_round_context()
        comp_ctx = _make_comparison_context()
        consensus = _make_consensus_report()
        verdict = asyncio.run(engine.judge(round_ctx, comp_ctx, consensus))
        assert isinstance(verdict, JudgeVerdict)
        assert verdict.confidence == 0.0
        assert "未配置" in verdict.verdict

    def test_has_api_key(self):
        engine = JudgeEngine(api_keys={"openai": "sk-test"})
        assert engine.has_api_key("openai") is True
        assert engine.has_api_key("gemini") is False

    def test_set_api_key(self):
        engine = JudgeEngine()
        engine.set_api_key("openai", "sk-test")
        assert engine.has_api_key("openai") is True

    def test_build_prompt(self):
        engine = JudgeEngine()
        round_ctx = _make_round_context()
        comp_ctx = _make_comparison_context()
        consensus = _make_consensus_report()
        prompt = engine._build_judge_prompt(round_ctx, comp_ctx, consensus, None)
        assert "test query" in prompt
        assert "deepseek" in prompt
