"""Stage 6: ComparisonAssembler — assemble final ComparisonContext."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from omnicounci1l_core.types import (
    ComparisonContext,
    ComparisonMetrics,
    DifferenceItem,
    RoundContext,
    SemanticUnit,
    SimilarityMatrix,
    UniqueInsight,
)

if TYPE_CHECKING:
    from omnicounci1l_core.config import ComparisonConfig


class ComparisonAssembler:
    """Assemble all pipeline outputs into a ComparisonContext."""

    def assemble(
        self,
        round_ctx: RoundContext,
        units: list[SemanticUnit],
        matrix: SimilarityMatrix,
        differences: list[DifferenceItem],
        unique_insights: list[UniqueInsight],
        config: ComparisonConfig,
    ) -> ComparisonContext:
        """Build the final ComparisonContext."""
        # Compute metrics
        metrics = self._compute_metrics(units, matrix, differences)

        # Participant AI info
        ai_unit_counts: dict[str, int] = {}
        for u in units:
            ai_unit_counts[u.source_ai_id] = ai_unit_counts.get(u.source_ai_id, 0) + 1
        participant_ais = [(ai_id, count) for ai_id, count in ai_unit_counts.items()]

        return ComparisonContext(
            task_id=round_ctx.task_id,
            round_number=round_ctx.round_number,
            query=round_ctx.query,
            source_context_id=f"{round_ctx.task_id}_r{round_ctx.round_number}",
            generated_at=time.time(),
            participant_ais=participant_ais,
            semantic_units=units,
            similarity_matrix=matrix,
            differences=differences,
            unique_insights=unique_insights,
            metrics=metrics,
        )

    def _compute_metrics(
        self,
        units: list[SemanticUnit],
        matrix: SimilarityMatrix,
        differences: list[DifferenceItem],
    ) -> ComparisonMetrics:
        """Compute global comparison metrics."""
        # Overall divergence = 1 - mean(all pairwise similarities)
        all_sims = []
        n = len(units)
        for i in range(n):
            for j in range(i + 1, n):
                all_sims.append(matrix.unit_matrix[i][j])

        overall_divergence = 1.0 - (sum(all_sims) / len(all_sims)) if all_sims else 0.0

        # Top difference dimension
        top_dimension = ""
        if differences:
            top = max(differences, key=lambda d: d.strength)
            top_dimension = top.dimension

        # Pairwise AI similarities
        pairwise = []
        for i, ai_a in enumerate(matrix.ai_ids):
            for j, ai_b in enumerate(matrix.ai_ids):
                if i < j:
                    pairwise.append((ai_a, ai_b, round(matrix.pairwise_similarities[i][j], 3)))

        return ComparisonMetrics(
            total_units=len(units),
            overall_divergence=round(overall_divergence, 3),
            pairwise_similarities=pairwise,
            top_difference_dimension=top_dimension,
        )
