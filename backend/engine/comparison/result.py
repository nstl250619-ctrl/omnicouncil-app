"""Comparison result models."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Agreement:
    """A point of agreement between multiple AIs."""
    topic: str
    description: str
    supporting_providers: list[str] = field(default_factory=list)
    confidence: float = 0.0  # 0-1


@dataclass
class Disagreement:
    """A point of disagreement between AIs."""
    topic: str
    positions: list[dict] = field(default_factory=list)  # [{provider_id, stance, reasoning}]
    severity: float = 0.0  # 0-1


@dataclass
class ComparisonResult:
    """Result of comparing multiple AI responses."""
    task_id: str
    query: str
    agreements: list[Agreement] = field(default_factory=list)
    disagreements: list[Disagreement] = field(default_factory=list)
    summary: str = ""
    overall_agreement: float = 0.0  # 0-1

    @property
    def has_agreements(self) -> bool:
        return len(self.agreements) > 0

    @property
    def has_disagreements(self) -> bool:
        return len(self.disagreements) > 0

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "query": self.query,
            "agreements": [
                {
                    "topic": a.topic,
                    "description": a.description,
                    "supporting_providers": a.supporting_providers,
                    "confidence": a.confidence,
                }
                for a in self.agreements
            ],
            "disagreements": [
                {
                    "topic": d.topic,
                    "positions": d.positions,
                    "severity": d.severity,
                }
                for d in self.disagreements
            ],
            "summary": self.summary,
            "overall_agreement": self.overall_agreement,
        }
