"""Trace Layer — full lifecycle tracing for tasks.

Sidecar instrumentation. Does not modify existing pipeline.
Feature flag: AppConfig.tracing_enabled (default: False).
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

MAX_TRACES = 100


@dataclass
class TraceEvent:
    layer: str
    event: str
    timestamp: float
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class Trace:
    trace_id: str
    task_id: str
    status: str = "running"
    started_at: float = 0.0
    finished_at: float = 0.0
    events: list[TraceEvent] = field(default_factory=list)
    snapshot: dict[str, Any] = field(default_factory=dict)

    def record(self, layer: str, event: str, data: dict[str, Any] | None = None) -> None:
        self.events.append(TraceEvent(
            layer=layer,
            event=event,
            timestamp=time.time(),
            data=data or {},
        ))

    def complete(self, status: str = "completed") -> None:
        self.status = status
        self.finished_at = time.time()


class TraceStore:
    """In-memory trace buffer with FIFO eviction."""

    _instance: TraceStore | None = None

    def __init__(self) -> None:
        self._traces: dict[str, Trace] = {}  # task_id -> Trace
        self._order: list[str] = []  # FIFO order

    @classmethod
    def instance(cls) -> TraceStore:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        cls._instance = None

    def create(self, task_id: str, query: str = "", ai_ids: list[str] | None = None) -> Trace:
        trace_id = f"tr_{uuid.uuid4().hex[:12]}"
        trace = Trace(
            trace_id=trace_id,
            task_id=task_id,
            started_at=time.time(),
            snapshot={"query": query, "ai_ids": ai_ids or []},
        )
        self._traces[task_id] = trace
        self._order.append(task_id)
        self._evict()
        return trace

    def get(self, task_id: str) -> Trace | None:
        return self._traces.get(task_id)

    def get_by_trace_id(self, trace_id: str) -> Trace | None:
        for trace in self._traces.values():
            if trace.trace_id == trace_id:
                return trace
        return None

    def all(self) -> list[Trace]:
        return [self._traces[tid] for tid in self._order if tid in self._traces]

    def _evict(self) -> None:
        while len(self._traces) > MAX_TRACES:
            old_id = self._order.pop(0)
            self._traces.pop(old_id, None)
