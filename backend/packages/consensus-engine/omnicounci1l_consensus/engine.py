"""ConsensusEngine — generates consensus reports from comparison results.

Stateless. Pure function: RoundContext + ComparisonContext → ConsensusReport.
No internal cache. No EventBus dependency.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from omnicounci1l_core.types import generate_id

from .result import (
    ConsensusPoint,
    ConsensusRecommendation,
    ConsensusReport,
    ConsensusSummaryStats,
    DisagreementPoint,
    DisagreementPosition,
)

if TYPE_CHECKING:
    from omnicounci1l_core.config import ComparisonConfig
    from omnicounci1l_core.types import ComparisonContext, RoundContext

logger = logging.getLogger(__name__)


class ConsensusEngine:
    """Consensus analysis engine.

    Input: RoundContext + ComparisonContext
    Output: ConsensusReport

    Sub-modules:
    - ConsensusDetector: find agreement points
    - DisagreementDetector: find disagreement points
    - ConclusionGenerator: generate conclusion text
    - RecommendationEngine: generate recommendations
    - ConsensusAssembler: assemble final report
    """

    def __init__(self, config: ComparisonConfig | None = None) -> None:
        self._consensus_threshold = 0.7
        self._disagreement_threshold = 0.4
        self._severe_disagreement = 0.7
        self._max_consensus_points = 10
        self._max_disagreements = 10
        self._max_recommendations = 5

        if config:
            self._consensus_threshold = getattr(config, "consensus_threshold", 0.7)
            self._disagreement_threshold = getattr(config, "disagreement_threshold", 0.4)

    def analyze(
        self,
        round_ctx: RoundContext,
        comparison_ctx: ComparisonContext,
    ) -> ConsensusReport:
        """Generate consensus report from round + comparison context."""
        start = time.time()

        # Degraded handling
        if comparison_ctx.degraded:
            return self._degraded_report(
                round_ctx, comparison_ctx, comparison_ctx.degraded
            )

        successful = [r for r in round_ctx.results if r.status.value == "success"]
        if len(successful) < 2:
            return self._degraded_report(round_ctx, comparison_ctx, "single_source")

        # Step 1: Detect consensus points
        consensus_points = self._detect_consensus(comparison_ctx)

        # Step 2: Detect disagreements
        disagreements = self._detect_disagreements(comparison_ctx)

        # Step 3: Generate conclusion
        conclusion, confidence, agreement_level = self._generate_conclusion(
            comparison_ctx, consensus_points, disagreements
        )

        # Step 4: Generate recommendations
        recommendations = self._generate_recommendations(
            consensus_points, disagreements, comparison_ctx.unique_insights
        )

        # Step 5: Compute summary stats
        summary_stats = self._compute_stats(
            round_ctx, comparison_ctx, consensus_points, disagreements
        )

        # Step 6: Assemble report
        report = ConsensusReport(
            task_id=round_ctx.task_id,
            query=round_ctx.query,
            generated_at=time.time(),
            conclusion=conclusion,
            confidence=confidence,
            consensus_points=consensus_points[:self._max_consensus_points],
            disagreements=disagreements[:self._max_disagreements],
            unique_insights=comparison_ctx.unique_insights,
            recommendations=recommendations[:self._max_recommendations],
            participant_ais=[ai_id for ai_id, _ in comparison_ctx.participant_ais],
            agreement_level=agreement_level,
            summary_stats=summary_stats,
            degraded=None,
        )

        elapsed = time.time() - start
        logger.info(
            "Consensus for task %s in %.2fs: %d consensus, %d disagreements, level=%s",
            round_ctx.task_id, elapsed,
            len(consensus_points), len(disagreements), agreement_level,
        )

        return report

    # ========== Consensus Detector ==========

    def _detect_consensus(self, ctx: ComparisonContext) -> list[ConsensusPoint]:
        """Find consensus points from high-similarity clusters."""
        points = []
        matrix = ctx.similarity_matrix
        units = ctx.semantic_units

        if not matrix.pairwise_similarities or len(units) < 2:
            return points

        # Group units by AI
        ai_units: dict[str, list[int]] = {}
        for i, unit in enumerate(units):
            ai_units.setdefault(unit.source_ai_id, []).append(i)

        ai_ids = list(ai_units.keys())

        # Find high-similarity cross-AI pairs
        for i in range(len(ai_ids)):
            for j in range(i + 1, len(ai_ids)):
                ai_a, ai_b = ai_ids[i], ai_ids[j]
                if i < len(matrix.pairwise_similarities) and j < len(matrix.pairwise_similarities[i]):
                    sim = matrix.pairwise_similarities[i][j]
                else:
                    continue

                if sim >= self._consensus_threshold:
                    # Extract shared evidence
                    evidence = []
                    for idx_a in ai_units[ai_a][:3]:
                        if idx_a < len(units):
                            evidence.append(units[idx_a].content[:100])

                    # Generate statement from most representative unit
                    statement = self._extract_statement(units, ai_units[ai_a] + ai_units[ai_b])

                    points.append(ConsensusPoint(
                        point_id=generate_id("cp"),
                        statement=statement,
                        supporting_ais=[ai_a, ai_b],
                        agreement_ratio=round(sim, 3),
                        evidence=evidence[:3],
                        confidence=round(sim, 3),
                    ))

        return points

    def _extract_statement(self, units, indices: list[int]) -> str:
        """Extract a representative statement from units."""
        if not indices:
            return "共识观点"
        # Use the longest unit as representative
        best = max(
            (units[i] for i in indices if i < len(units)),
            key=lambda u: len(u.content),
            default=None,
        )
        if best:
            text = best.content
            if len(text) > 100:
                return text[:97] + "..."
            return text
        return "共识观点"

    # ========== Disagreement Detector ==========

    def _detect_disagreements(self, ctx: ComparisonContext) -> list[DisagreementPoint]:
        """Find disagreements from differences and low similarity."""
        disagreements = []

        for diff in ctx.differences:
            positions = []
            for ai_id, stance in diff.involved_ais:
                positions.append(DisagreementPosition(
                    ai_id=ai_id,
                    stance=stance[:100],
                    evidence="",
                ))

            # Determine severity
            severity = diff.strength
            if severity >= self._severe_disagreement:
                resolvable = False
            else:
                resolvable = True

            disagreements.append(DisagreementPoint(
                point_id=generate_id("dp"),
                dimension=diff.dimension,
                positions=positions,
                severity=round(severity, 3),
                diff_type=diff.diff_type,
                resolvable=resolvable,
            ))

        return disagreements

    # ========== Conclusion Generator ==========

    def _generate_conclusion(
        self,
        ctx: ComparisonContext,
        consensus_points: list[ConsensusPoint],
        disagreements: list[DisagreementPoint],
    ) -> tuple[str, float, str]:
        """Generate conclusion text, confidence, and agreement level."""
        divergence = ctx.metrics.overall_divergence

        if divergence < 0.2:
            level = "high"
            confidence = round(1.0 - divergence, 3)
            if consensus_points:
                summary = consensus_points[0].statement
                conclusion = f"所有 AI 观点高度一致。{summary}"
            else:
                conclusion = "所有 AI 观点高度一致，无显著分歧。"
        elif divergence < 0.4:
            level = "medium"
            confidence = round(1.0 - divergence, 3)
            if disagreements:
                dim = disagreements[0].dimension
                conclusion = f"多数 AI 观点相近，存在少量分歧（{dim}）。"
            else:
                conclusion = "多数 AI 观点相近，存在少量差异。"
        elif divergence < 0.6:
            level = "low"
            confidence = round(1.0 - divergence, 3)
            if disagreements:
                dims = [d.dimension for d in disagreements[:2]]
                conclusion = f"AI 之间存在显著分歧：{'、'.join(dims)}。"
            else:
                conclusion = "AI 之间存在显著分歧。"
        else:
            level = "divergent"
            confidence = round(max(0.1, 1.0 - divergence), 3)
            conclusion = "AI 观点分歧严重，建议综合多方信息独立判断。"

        return conclusion, confidence, level

    # ========== Recommendation Engine ==========

    def _generate_recommendations(
        self,
        consensus_points: list[ConsensusPoint],
        disagreements: list[DisagreementPoint],
        unique_insights: list,
    ) -> list[ConsensusRecommendation]:
        """Generate recommendations based on analysis."""
        recs = []

        if consensus_points:
            recs.append(ConsensusRecommendation(
                recommendation_id=generate_id("cr"),
                text="综合考虑所有 AI 的共同观点作为基础判断",
                basis="consensus",
                priority="high",
            ))

        severe = [d for d in disagreements if d.severity >= self._severe_disagreement]
        if severe:
            recs.append(ConsensusRecommendation(
                recommendation_id=generate_id("cr"),
                text=f"重点关注 {len(severe)} 个严重分歧点，可能需要进一步调研",
                basis="disagreement",
                priority="high",
            ))

        moderate = [d for d in disagreements if 0.3 < d.severity < self._severe_disagreement]
        if moderate:
            recs.append(ConsensusRecommendation(
                recommendation_id=generate_id("cr"),
                text="对于分歧点，建议结合实际情况做最终判断",
                basis="disagreement",
                priority="medium",
            ))

        high_insights = [
            i for i in unique_insights
            if hasattr(i, "novelty_score") and i.novelty_score > 0.7
            and hasattr(i, "potential_importance") and i.potential_importance == "high"
        ]
        if high_insights:
            insight = high_insights[0]
            text = f"关注 {insight.ai_id} 提出的独特观点"
            if hasattr(insight, "content"):
                text += f": {insight.content[:50]}"
            recs.append(ConsensusRecommendation(
                recommendation_id=generate_id("cr"),
                text=text,
                basis="unique_insight",
                priority="medium",
            ))

        if not recs:
            recs.append(ConsensusRecommendation(
                recommendation_id=generate_id("cr"),
                text="各 AI 观点一致，可作为可靠参考",
                basis="consensus",
                priority="low",
            ))

        return recs

    # ========== Summary Stats ==========

    def _compute_stats(
        self,
        round_ctx: RoundContext,
        comparison_ctx: ComparisonContext,
        consensus_points: list[ConsensusPoint],
        disagreements: list[DisagreementPoint],
    ) -> ConsensusSummaryStats:
        """Compute summary statistics."""
        successful = [r for r in round_ctx.results if r.status.value == "success"]

        # Average pairwise similarity
        pairwise = comparison_ctx.similarity_matrix.pairwise_similarities
        if pairwise and len(pairwise) > 1:
            sims = []
            for i in range(len(pairwise)):
                for j in range(i + 1, len(pairwise[i])):
                    sims.append(pairwise[i][j])
            avg_sim = sum(sims) / len(sims) if sims else 0.0
        else:
            avg_sim = 0.0

        # Top dimensions
        top_agreement = consensus_points[0].statement[:20] if consensus_points else ""
        top_disagreement = disagreements[0].dimension if disagreements else ""

        return ConsensusSummaryStats(
            total_ais=len(round_ctx.results),
            successful_ais=len(successful),
            total_consensus_points=len(consensus_points),
            total_disagreements=len(disagreements),
            total_unique_insights=len(comparison_ctx.unique_insights),
            avg_pairwise_similarity=round(avg_sim, 3),
            top_agreement_dimension=top_agreement,
            top_disagreement_dimension=top_disagreement,
        )

    # ========== Degraded Report ==========

    def _degraded_report(
        self,
        round_ctx: RoundContext,
        comparison_ctx: ComparisonContext,
        reason: str,
    ) -> ConsensusReport:
        """Generate a degraded report when insufficient data."""
        successful = [r for r in round_ctx.results if r.status.value == "success"]

        if reason == "single_source" and successful:
            conclusion = f"仅有一个 AI ({successful[0].ai_id}) 成功响应，无法进行共识分析。"
            confidence = 0.5
            level = "single"
        else:
            conclusion = "无法生成共识报告：数据不足。"
            confidence = 0.0
            level = "none"

        return ConsensusReport(
            task_id=round_ctx.task_id,
            query=round_ctx.query,
            generated_at=time.time(),
            conclusion=conclusion,
            confidence=confidence,
            consensus_points=[],
            disagreements=[],
            unique_insights=[],
            recommendations=[ConsensusRecommendation(
                recommendation_id=generate_id("cr"),
                text="需要更多 AI 参与才能生成共识报告",
                basis="consensus",
                priority="low",
            )],
            participant_ais=[r.ai_id for r in successful],
            agreement_level=level,
            summary_stats=ConsensusSummaryStats(
                total_ais=len(round_ctx.results),
                successful_ais=len(successful),
                total_consensus_points=0,
                total_disagreements=0,
                total_unique_insights=0,
                avg_pairwise_similarity=0.0,
                top_agreement_dimension="",
                top_disagreement_dimension="",
            ),
            degraded=reason,
        )
