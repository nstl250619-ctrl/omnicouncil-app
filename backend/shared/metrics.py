"""Metrics Layer — lightweight runtime metrics.

Sidecar instrumentation. Does not modify existing pipeline.
Feature flag: AppConfig.metrics_enabled (default: False).
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

MAX_HISTOGRAM_SAMPLES = 1000


class MetricsCollector:
    """Lightweight metrics collector. All operations are O(1) increment."""

    _instance: MetricsCollector | None = None

    def __init__(self) -> None:
        self._counters: dict[str, int] = defaultdict(int)
        self._per_provider: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._latency: dict[str, list[float]] = defaultdict(list)
        self._per_provider_latency: dict[str, list[float]] = defaultdict(list)
        self._start_time: float = time.time()

    @classmethod
    def instance(cls) -> MetricsCollector:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        cls._instance = None

    # ========== Counters ==========

    def inc(self, name: str, value: int = 1) -> None:
        self._counters[name] += value

    def inc_provider(self, ai_id: str, name: str, value: int = 1) -> None:
        self._per_provider[ai_id][name] += value

    # ========== Histograms ==========

    def record_latency(self, name: str, duration_ms: float) -> None:
        buf = self._latency[name]
        if len(buf) >= MAX_HISTOGRAM_SAMPLES:
            buf.pop(0)
        buf.append(duration_ms)

    def record_provider_latency(self, ai_id: str, duration_ms: float) -> None:
        buf = self._per_provider_latency[ai_id]
        if len(buf) >= MAX_HISTOGRAM_SAMPLES:
            buf.pop(0)
        buf.append(duration_ms)

    # ========== Snapshot ==========

    def snapshot(self) -> dict[str, Any]:
        uptime = time.time() - self._start_time
        return {
            "uptime_seconds": round(uptime, 1),
            "counters": dict(self._counters),
            "per_provider": {
                ai_id: dict(counts) for ai_id, counts in self._per_provider.items()
            },
            "latency": {
                name: self._percentiles(samples)
                for name, samples in self._latency.items()
            },
            "per_provider_latency": {
                ai_id: self._percentiles(samples)
                for ai_id, samples in self._per_provider_latency.items()
            },
        }

    @staticmethod
    def _percentiles(samples: list[float]) -> dict[str, float]:
        if not samples:
            return {"p50": 0, "p95": 0, "p99": 0, "avg": 0, "count": 0}
        sorted_s = sorted(samples)
        n = len(sorted_s)
        return {
            "p50": round(sorted_s[int(n * 0.5)], 1),
            "p95": round(sorted_s[int(n * 0.95)], 1),
            "p99": round(sorted_s[min(int(n * 0.99), n - 1)], 1),
            "avg": round(sum(sorted_s) / n, 1),
            "count": n,
        }

    def reset_all(self) -> None:
        self._counters.clear()
        self._per_provider.clear()
        self._latency.clear()
        self._per_provider_latency.clear()
        self._start_time = time.time()
