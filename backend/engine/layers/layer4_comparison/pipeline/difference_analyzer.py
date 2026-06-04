"""Stage 4: DifferenceAnalyzer — detect differences between AIs."""

from __future__ import annotations

import re
from collections import Counter

from shared.types import DifferenceItem, SemanticUnit, SimilarityMatrix, generate_id
from shared.config import ComparisonConfig

from ..clustering.union_find import UnionFind


# Keyword patterns for difference type classification
_TYPE_PATTERNS = {
    "factual": ["数据", "事实", "根据", "统计", "研究", "source", "data", "fact"],
    "methodological": ["方法", "策略", "步骤", "流程", "架构", "approach", "method", "strategy"],
    "evaluative": ["好", "坏", "优", "劣", "风险", "优势", "pros", "cons", "risk"],
    "recommendational": ["建议", "应该", "推荐", "最好", "首选", "recommend", "suggest", "should"],
}


class DifferenceAnalyzer:
    """Detect differences between AI responses.

    Uses Union-Find clustering on similarity matrix, then identifies
    cross-AI stance divergence within clusters.
    """

    def __init__(self, config: ComparisonConfig) -> None:
        self._similarity_threshold = config.similarity_threshold
        self._difference_trigger = config.difference_trigger

    def detect(
        self, units: list[SemanticUnit], matrix: SimilarityMatrix
    ) -> list[DifferenceItem]:
        """Detect differences between AI responses."""
        if len(units) < 2:
            return []

        # Step 1: Cluster similar units using Union-Find
        n = len(units)
        uf = UnionFind(n)

        for i in range(n):
            for j in range(i + 1, n):
                if matrix.unit_matrix[i][j] >= self._similarity_threshold:
                    uf.union(i, j)

        # Step 2: Analyze each cluster for cross-AI differences
        differences: list[DifferenceItem] = []
        components = uf.components()

        for root, members in components.items():
            if len(members) < 2:
                continue

            # Group members by AI
            ai_groups: dict[str, list[int]] = {}
            for idx in members:
                ai_id = units[idx].source_ai_id
                if ai_id not in ai_groups:
                    ai_groups[ai_id] = []
                ai_groups[ai_id].append(idx)

            # Only look at clusters with multiple AIs
            if len(ai_groups) < 2:
                continue

            # Check cross-AI similarity within cluster
            ai_ids = list(ai_groups.keys())
            for i_ai in range(len(ai_ids)):
                for j_ai in range(i_ai + 1, len(ai_ids)):
                    ai_a = ai_ids[i_ai]
                    ai_b = ai_ids[j_ai]

                    # Average similarity between these two AIs in this cluster
                    cross_sims = []
                    for idx_a in ai_groups[ai_a]:
                        for idx_b in ai_groups[ai_b]:
                            cross_sims.append(matrix.unit_matrix[idx_a][idx_b])

                    if not cross_sims:
                        continue

                    avg_sim = sum(cross_sims) / len(cross_sims)

                    # If similarity is below difference trigger, it's a difference
                    if avg_sim < self._difference_trigger:
                        # Extract dimension from keyword frequency
                        all_text = " ".join(units[idx].content for idx in members)
                        dimension = self._extract_dimension(all_text)

                        # Classify type
                        diff_type = self._classify_type(all_text)

                        # Get stance summaries
                        stance_a = units[ai_groups[ai_a][0]].content[:100]
                        stance_b = units[ai_groups[ai_b][0]].content[:100]

                        strength = 1.0 - avg_sim
                        related_ids = [units[idx].unit_id for idx in members]

                        differences.append(DifferenceItem(
                            id=generate_id("diff"),
                            dimension=dimension,
                            involved_ais=[(ai_a, stance_a), (ai_b, stance_b)],
                            strength=round(strength, 3),
                            diff_type=diff_type,
                            related_unit_ids=related_ids,
                        ))

        return differences

    def _extract_dimension(self, text: str) -> str:
        """Extract topic dimension from text using keyword frequency."""
        # Simple: use most frequent meaningful words
        words = re.findall(r"[\w一-鿿]{2,}", text)
        freq = Counter(words)
        # Filter stopwords
        stopwords = {"的", "是", "在", "了", "和", "也", "就", "都", "而", "及", "与", "或", "the", "is", "and", "to", "of", "a", "in", "that", "for", "it"}
        meaningful = [(w, c) for w, c in freq.most_common(10) if w.lower() not in stopwords]
        if meaningful:
            return meaningful[0][0]
        return "未分类"

    def _classify_type(self, text: str) -> str:
        """Classify difference type using keyword patterns."""
        scores = {}
        text_lower = text.lower()
        for dtype, keywords in _TYPE_PATTERNS.items():
            scores[dtype] = sum(1 for kw in keywords if kw in text_lower)

        if not scores or max(scores.values()) == 0:
            return "evaluative"

        return max(scores, key=scores.get)
