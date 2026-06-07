"""Judge result models — immutable dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class JudgeVerdict:
    """Final judgment from an AI judge."""
    judge_id: str
    query: str
    verdict: str = ""
    reasoning: str = ""
    confidence: float = 0.0
    agrees_with_consensus: bool = True
    additional_insights: list[str] = field(default_factory=list)
    generated_at: float = 0.0
