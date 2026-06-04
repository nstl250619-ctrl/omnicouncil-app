"""Judge verdict model."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class JudgeVerdict:
    """Final judgment from an AI judge."""
    judge_id: str  # e.g., "openai", "claude"
    query: str
    verdict: str = ""
    reasoning: str = ""
    confidence: float = 0.0
    agrees_with_consensus: bool = True
    additional_insights: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "judge_id": self.judge_id,
            "query": self.query,
            "verdict": self.verdict,
            "reasoning": self.reasoning,
            "confidence": self.confidence,
            "agrees_with_consensus": self.agrees_with_consensus,
            "additional_insights": self.additional_insights,
        }
