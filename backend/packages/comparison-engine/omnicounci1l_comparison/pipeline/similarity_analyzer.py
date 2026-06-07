"""Stage 3: SimilarityAnalyzer — compute similarity matrix."""

from __future__ import annotations

from typing import TYPE_CHECKING

from omnicounci1l_core.types import SemanticUnit, SimilarityMatrix

from ..similarity.cosine_similarity import cosine_similarity
from ..similarity.lcs_calculator import lcs_ratio
from ..similarity.tfidf_calculator import TfidfCalculator

if TYPE_CHECKING:
    from omnicounci1l_core.config import ComparisonConfig


class SimilarityAnalyzer:
    """Compute unit-level and AI-level similarity matrices.

    Uses weighted combination: sim = tfidf_weight * cosine(tfidf) + lcs_weight * lcs_ratio
    """

    def __init__(self, config: ComparisonConfig) -> None:
        self._tfidf_weight = config.tfidf_weight
        self._lcs_weight = config.lcs_weight

    def analyze(self, units: list[SemanticUnit]) -> SimilarityMatrix:
        """Compute similarity matrices for all semantic units."""
        n = len(units)
        if n == 0:
            return SimilarityMatrix()

        # Compute TF-IDF vectors
        calculator = TfidfCalculator()
        documents = [u.content for u in units]
        tfidf_vectors = calculator.fit_transform(documents)

        # Build unit-level similarity matrix
        unit_matrix: list[list[float]] = [[0.0] * n for _ in range(n)]
        for i in range(n):
            unit_matrix[i][i] = 1.0
            for j in range(i + 1, n):
                # TF-IDF cosine similarity
                tfidf_sim = cosine_similarity(tfidf_vectors[i], tfidf_vectors[j])
                # LCS ratio
                lcs_sim = lcs_ratio(units[i].content, units[j].content)
                # Weighted combination
                sim = self._tfidf_weight * tfidf_sim + self._lcs_weight * lcs_sim
                unit_matrix[i][j] = sim
                unit_matrix[j][i] = sim

        # Build AI-level pairwise similarity
        ai_ids = list(dict.fromkeys(u.source_ai_id for u in units))
        ai_index = {ai_id: i for i, ai_id in enumerate(ai_ids)}
        ai_sims: dict[tuple[str, str], list[float]] = {}

        for i in range(n):
            for j in range(i + 1, n):
                ai_a = units[i].source_ai_id
                ai_b = units[j].source_ai_id
                if ai_a != ai_b:
                    key = (min(ai_a, ai_b), max(ai_a, ai_b))
                    if key not in ai_sims:
                        ai_sims[key] = []
                    ai_sims[key].append(unit_matrix[i][j])

        # Average pairwise similarities
        pairwise: list[list[float]] = [[0.0] * len(ai_ids) for _ in range(len(ai_ids))]
        for i in range(len(ai_ids)):
            pairwise[i][i] = 1.0

        for (ai_a, ai_b), sims in ai_sims.items():
            avg = sum(sims) / len(sims) if sims else 0.0
            idx_a = ai_index[ai_a]
            idx_b = ai_index[ai_b]
            pairwise[idx_a][idx_b] = avg
            pairwise[idx_b][idx_a] = avg

        return SimilarityMatrix(
            ai_ids=ai_ids,
            pairwise_similarities=pairwise,
            unit_matrix=unit_matrix,
            unit_index=[u.unit_id for u in units],
        )
