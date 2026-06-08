"""Conflict result models — immutable dataclasses."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ConflictPosition:
    """A position in a conflict."""
    ai_id: str
    stance: str
    evidence: str = ""


@dataclass(frozen=True)
class ConflictPoint:
    """A specific point of conflict between AIs."""
    conflict_id: str
    topic: str
    positions: list[ConflictPosition]
    root_cause: str = ""
    severity: float = 0.0  # 0-1
    resolvable: bool = True


@dataclass(frozen=True)
class ConflictResult:
    """Result of conflict analysis."""
    task_id: str
    query: str
    conflicts: list[ConflictPoint]
    summary: str = ""
    overall_conflict_level: float = 0.0  # 0-1
    generated_at: float = 0.0

    @property
    def has_conflicts(self) -> bool:
        return len(self.conflicts) > 0
