"""Stage 5: UniqueInsightExtractor — find unique viewpoints from individual AIs."""

from __future__ import annotations

from typing import TYPE_CHECKING

from omnicounci1l_core.types import SemanticUnit, SimilarityMatrix, UniqueInsight

if TYPE_CHECKING:
    from omnicounci1l_core.config import ComparisonConfig


class UniqueInsightExtractor:
    """Extract unique viewpoints that only one AI mentioned.

    A unit is "unique" if its max similarity to all other-AI units is below threshold.
    """

    def __init__(self, config: ComparisonConfig) -> None:
        self._uniqueness_threshold = config.uniqueness_threshold

    def extract(
        self, units: list[SemanticUnit], matrix: SimilarityMatrix
    ) -> list[UniqueInsight]:
        """Find unique insights from each AI."""
        insights: list[UniqueInsight] = []

        for i, unit in enumerate(units):
            # Find max similarity to any unit from a different AI
            max_sim = 0.0
            for j, other in enumerate(units):
                if i == j:
                    continue
                if other.source_ai_id == unit.source_ai_id:
                    continue
                max_sim = max(max_sim, matrix.unit_matrix[i][j])

            # If below threshold, it's a unique insight
            if max_sim < self._uniqueness_threshold:
                novelty_score = 1.0 - max_sim

                # Determine importance based on content length and keywords
                importance = self._assess_importance(unit.content)

                insights.append(UniqueInsight(
                    unit_id=unit.unit_id,
                    ai_id=unit.source_ai_id,
                    content=unit.content[:200],
                    novelty_score=round(novelty_score, 3),
                    potential_importance=importance,
                ))

        return insights

    def _assess_importance(self, content: str) -> str:
        """Heuristic importance assessment based on length and keywords."""
        high_keywords = ["创新", "独特", "关键", "重要", "核心", "critical", "key", "innovative", "unique"]
        length = len(content)

        has_keyword = any(kw in content.lower() for kw in high_keywords)

        if length > 100 or has_keyword:
            return "high"
        elif length > 50:
            return "medium"
        return "low"
