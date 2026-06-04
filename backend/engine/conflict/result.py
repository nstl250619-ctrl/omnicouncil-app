"""Conflict result models."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ConflictPoint:
    """A specific point of conflict between AIs."""
    topic: str
    positions: list[dict]  # [{provider_id, stance, reasoning}]
    root_cause: str = ""
    severity: float = 0.0  # 0-1
    resolvable: bool = True

    def to_dict(self) -> dict:
        return {
            "topic": self.topic,
            "positions": self.positions,
            "root_cause": self.root_cause,
            "severity": self.severity,
            "resolvable": self.resolvable,
        }


@dataclass
class ConflictResult:
    """Result of conflict analysis."""
    task_id: str
    query: str
    conflicts: list[ConflictPoint] = field(default_factory=list)
    summary: str = ""
    overall_conflict_level: float = 0.0  # 0-1

    @property
    def has_conflicts(self) -> bool:
        return len(self.conflicts) > 0

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "query": self.query,
            "conflicts": [c.to_dict() for c in self.conflicts],
            "summary": self.summary,
            "overall_conflict_level": self.overall_conflict_level,
        }
