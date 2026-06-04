"""Council task model."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TaskStatus(str, Enum):
    PENDING = "pending"
    DISPATCHED = "dispatched"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class CouncilTask:
    """A task representing a query sent to multiple AI providers."""
    task_id: str = field(default_factory=lambda: f"task_{uuid.uuid4().hex[:12]}")
    query: str = ""
    provider_ids: list[str] = field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    created_at: float = field(default_factory=lambda: __import__('time').time())
    updated_at: float = field(default_factory=lambda: __import__('time').time())
    timeout_ms: int = 120000
    priority: int = 0

    # Results
    results: dict[str, Any] = field(default_factory=dict)  # provider_id -> AIResponse
    errors: dict[str, str] = field(default_factory=dict)    # provider_id -> error message

    @property
    def completed_count(self) -> int:
        return len(self.results)

    @property
    def failed_count(self) -> int:
        return len(self.errors)

    @property
    def total_count(self) -> int:
        return len(self.provider_ids)

    @property
    def is_complete(self) -> bool:
        return self.completed_count + self.failed_count >= self.total_count

    def mark_completed(self, provider_id: str, result: Any) -> None:
        self.results[provider_id] = result
        self.updated_at = __import__('time').time()
        if self.is_complete:
            self.status = TaskStatus.COMPLETED if self.failed_count == 0 else TaskStatus.PARTIAL

    def mark_failed(self, provider_id: str, error: str) -> None:
        self.errors[provider_id] = error
        self.updated_at = __import__('time').time()
        if self.is_complete:
            self.status = TaskStatus.COMPLETED if self.completed_count > 0 else TaskStatus.FAILED

    def cancel(self) -> None:
        self.status = TaskStatus.CANCELLED
        self.updated_at = __import__('time').time()
