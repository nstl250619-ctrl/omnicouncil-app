"""Replay Layer — replay task execution from trace for debugging.

Sidecar instrumentation. Does not modify existing pipeline.
Read-only: no external API calls, no browser automation.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from shared.trace import Trace, TraceStore

logger = logging.getLogger(__name__)


@dataclass
class ReplayStep:
    layer: str
    event: str
    timestamp: float
    data: dict[str, Any] = field(default_factory=dict)
    replay_result: dict[str, Any] = field(default_factory=dict)


@dataclass
class ReplayResult:
    trace_id: str
    task_id: str
    query: str
    steps: list[ReplayStep] = field(default_factory=list)
    reconstructed_results: dict[str, str] = field(default_factory=dict)
    comparison_snapshot: dict[str, Any] = field(default_factory=dict)
    total_duration_ms: float = 0.0


class ReplayEngine:
    """Replay a task execution from its trace.

    Uses stored raw responses (no external calls).
    Re-runs ResponseNormalizer and ComparisonEngine on stored data.
    """

    def __init__(self, trace_store: TraceStore | None = None) -> None:
        self._trace_store = trace_store or TraceStore.instance()

    def replay(self, task_id: str) -> ReplayResult | None:
        """Replay a task from its trace. Returns None if trace not found."""
        trace = self._trace_store.get(task_id)
        if trace is None:
            return None
        return self._replay_trace(trace)

    def replay_by_trace_id(self, trace_id: str) -> ReplayResult | None:
        """Replay by trace_id."""
        trace = self._trace_store.get_by_trace_id(trace_id)
        if trace is None:
            return None
        return self._replay_trace(trace)

    def _replay_trace(self, trace: Trace) -> ReplayResult:
        """Reconstruct execution from trace events."""
        start = time.time()

        result = ReplayResult(
            trace_id=trace.trace_id,
            task_id=trace.task_id,
            query=trace.snapshot.get("query", ""),
        )

        # Replay each event
        for event in trace.events:
            step = ReplayStep(
                layer=event.layer,
                event=event.event,
                timestamp=event.timestamp,
                data=event.data,
            )

            if event.event == "send_prompt_end" and event.data.get("success"):
                # Replay: normalize stored raw response
                raw_text = event.data.get("raw_text", "")
                if raw_text:
                    from engine.layers.layer1_ai_access.response_normalizer import ResponseNormalizer
                    normalizer = ResponseNormalizer()
                    normalized = normalizer.normalize(raw_text)
                    ai_id = event.data.get("ai_id", "unknown")
                    result.reconstructed_results[ai_id] = raw_text
                    step.replay_result = {
                        "word_count": normalized.word_count,
                        "paragraphs": len(normalized.paragraphs),
                        "code_blocks": len(normalized.code_blocks),
                        "language": normalized.detected_language,
                    }

            if event.event == "analysis_end":
                # Store comparison snapshot from trace
                result.comparison_snapshot = event.data

            result.steps.append(step)

        result.total_duration_ms = (time.time() - start) * 1000
        return result
