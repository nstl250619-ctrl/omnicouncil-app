"""Consensus engine — synthesizes comparison and conflict results into a final report."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .result import ConsensusReport

if TYPE_CHECKING:
    from ..collector.response import AIResponse
    from ..comparison.result import ComparisonResult
    from ..conflict.result import ConflictResult

logger = logging.getLogger(__name__)


class ConsensusEngine:
    """Generates the final Council Report.

    Takes comparison and conflict results and produces:
    - A clear conclusion
    - Key points from all AIs
    - Recommendations
    - Minority opinions
    """

    def generate(
        self,
        task_id: str,
        query: str,
        responses: list[AIResponse],
        comparison: ComparisonResult,
        conflict: ConflictResult,
    ) -> ConsensusReport:
        """Generate the final consensus report."""

        # Extract key points from all responses
        key_points = []
        for resp in responses:
            # Get first meaningful sentence
            sentences = resp.content.split('。')
            if sentences and len(sentences[0]) > 10:
                key_points.append(f"{resp.provider_id}: {sentences[0].strip()}")

        # Generate conclusion based on agreement level
        conclusion = self._generate_conclusion(comparison, conflict, responses)

        # Calculate confidence
        confidence = comparison.overall_agreement

        # Generate recommendations
        recommendations = self._generate_recommendations(comparison, conflict)

        # Extract minority opinions
        minority = []
        if conflict.has_conflicts:
            for c in conflict.conflicts:
                if len(c.positions) >= 2:
                    # The minority position
                    minority.append({
                        "provider_id": c.positions[-1].get("provider_id", "unknown"),
                        "opinion": c.positions[-1].get("stance", ""),
                    })

        return ConsensusReport(
            task_id=task_id,
            query=query,
            conclusion=conclusion,
            confidence=confidence,
            key_points=key_points[:5],
            recommendations=recommendations,
            minority_opinions=minority,
            metadata={
                "total_providers": len(responses),
                "agreement_count": len(comparison.agreements),
                "disagreement_count": len(comparison.disagreements),
                "conflict_count": len(conflict.conflicts),
            },
        )

    def _generate_conclusion(
        self,
        comparison: ComparisonResult,
        conflict: ConflictResult,
        responses: list[AIResponse],
    ) -> str:
        if comparison.overall_agreement >= 0.8:
            return f"所有AI高度一致。{comparison.summary}"
        elif comparison.overall_agreement >= 0.5:
            return f"多数AI观点相近，存在少量分歧。{comparison.summary}"
        elif conflict.has_conflicts:
            return f"AI之间存在显著分歧。{conflict.summary}"
        else:
            return comparison.summary

    def _generate_recommendations(
        self,
        comparison: ComparisonResult,
        conflict: ConflictResult,
    ) -> list[str]:
        recs = []

        if comparison.has_agreements:
            recs.append("综合考虑所有AI的共同观点作为基础判断")

        if conflict.has_conflicts:
            severe = [c for c in conflict.conflicts if c.severity >= 0.7]
            if severe:
                recs.append("重点关注严重冲突点，可能需要进一步调研")
            recs.append("对于分歧点，建议结合实际情况做最终判断")

        if not recs:
            recs.append("各AI观点一致，可作为可靠参考")

        return recs
