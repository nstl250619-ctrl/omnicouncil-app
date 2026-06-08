"""Instrumentation — sidecar wiring for trace + metrics via EventBus.

Registers EventBus handlers that record trace events and metrics.
Does NOT modify any existing handler or pipeline logic.
Feature flags: tracing_enabled, metrics_enabled (default: False).
"""

from __future__ import annotations

import logging
from typing import Any

from shared.event_bus import EventBus
from shared.metrics import MetricsCollector
from shared.trace import TraceStore

logger = logging.getLogger(__name__)


class Instrumentation:
    """Sidecar instrumentation. Call install() to register EventBus hooks."""

    def __init__(
        self,
        event_bus: EventBus,
        tracing_enabled: bool = False,
        metrics_enabled: bool = False,
    ) -> None:
        self._event_bus = event_bus
        self._tracing_enabled = tracing_enabled
        self._metrics_enabled = metrics_enabled
        self._trace_store = TraceStore.instance() if tracing_enabled else None
        self._metrics = MetricsCollector.instance() if metrics_enabled else None

    def install(self) -> None:
        """Register all sidecar event handlers."""
        if not self._tracing_enabled and not self._metrics_enabled:
            logger.info("Instrumentation disabled (tracing=%s, metrics=%s)",
                        self._tracing_enabled, self._metrics_enabled)
            return

        self._event_bus.on("scheduler:task:created", self._on_task_created)
        self._event_bus.on("scheduler:task:dispatched", self._on_task_dispatched)
        self._event_bus.on("ai:task:completed", self._on_ai_completed)
        self._event_bus.on("ai:task:failed", self._on_ai_failed)
        self._event_bus.on("collector:context:ready", self._on_context_ready)

        logger.info("Instrumentation installed (tracing=%s, metrics=%s)",
                     self._tracing_enabled, self._metrics_enabled)

    # ========== Trace hooks ==========

    def _on_task_created(self, task_id: str, selected_ai_ids: list[str] | None = None,
                         mode: str = "parallel", query: str = "", **kwargs: Any) -> None:
        if self._tracing_enabled and self._trace_store:
            trace = self._trace_store.create(task_id, query=query, ai_ids=selected_ai_ids)
            trace.record("scheduler", "task_created", {
                "ai_ids": selected_ai_ids, "mode": mode,
            })

        if self._metrics_enabled and self._metrics:
            self._metrics.inc("requests_total")

    def _on_task_dispatched(self, task_id: str, **kwargs: Any) -> None:
        if self._tracing_enabled and self._trace_store:
            trace = self._trace_store.get(task_id)
            if trace:
                trace.record("scheduler", "task_dispatched")

    def _on_ai_completed(self, task_id: str, ai_id: str, response: Any = None, **kwargs: Any) -> None:
        if self._tracing_enabled and self._trace_store:
            trace = self._trace_store.get(task_id)
            if trace:
                trace.record("provider", "send_prompt_end", {
                    "ai_id": ai_id,
                    "success": True,
                    "duration": getattr(response, "duration", 0),
                    "word_count": getattr(response, "word_count", 0),
                    "raw_text": getattr(response, "content", "")[:2000],
                })

        if self._metrics_enabled and self._metrics:
            self._metrics.inc("requests_success")
            self._metrics.inc_provider(ai_id, "success")
            duration_ms = getattr(response, "duration", 0) * 1000
            self._metrics.record_provider_latency(ai_id, duration_ms)

    def _on_ai_failed(self, task_id: str, ai_id: str, error: str = "", **kwargs: Any) -> None:
        if self._tracing_enabled and self._trace_store:
            trace = self._trace_store.get(task_id)
            if trace:
                trace.record("provider", "send_prompt_end", {
                    "ai_id": ai_id, "success": False, "error": error,
                })

        if self._metrics_enabled and self._metrics:
            self._metrics.inc("requests_failure")
            self._metrics.inc_provider(ai_id, "failure")

    def _on_context_ready(self, context: Any = None, **kwargs: Any) -> None:
        task_id = getattr(context, "task_id", "")
        if self._tracing_enabled and self._trace_store:
            trace = self._trace_store.get(task_id)
            if trace:
                trace.record("collector", "context_ready", {
                    "result_count": len(getattr(context, "results", [])),
                })
                trace.complete("completed")

        if self._metrics_enabled and self._metrics:
            if context and hasattr(context, "results"):
                for r in context.results:
                    if hasattr(r, "duration"):
                        self._metrics.record_latency("latency_collector_ms", r.duration * 1000)
