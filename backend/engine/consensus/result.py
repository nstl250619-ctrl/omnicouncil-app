"""Consensus report model."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ConsensusReport:
    """Final council report synthesizing all analysis."""
    task_id: str
    query: str
    conclusion: str = ""
    confidence: float = 0.0  # 0-1
    key_points: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    minority_opinions: list[dict] = field(default_factory=list)  # [{provider_id, opinion}]
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "query": self.query,
            "conclusion": self.conclusion,
            "confidence": self.confidence,
            "key_points": self.key_points,
            "recommendations": self.recommendations,
            "minority_opinions": self.minority_opinions,
            "metadata": self.metadata,
        }
