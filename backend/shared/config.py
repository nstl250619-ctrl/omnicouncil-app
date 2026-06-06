"""Global configuration loader."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class RateLimitConfig:
    max_per_minute: int = 10
    min_interval_ms: int = 3000
    cooldown_after_n: int = 15
    cooldown_duration_ms: int = 30000


@dataclass(frozen=True)
class RetryConfig:
    max_retries: int = 2
    retry_delay_ms: int = 3000
    backoff_multiplier: float = 1.5


@dataclass(frozen=True)
class SchedulerConfig:
    max_concurrent_tasks: int = 2
    ai_min_interval_ms: int = 2000
    default_timeout_ms: int = 120000
    soft_timeout_ms: int = 60000
    hard_timeout_ms: int = 180000
    retry: RetryConfig = field(default_factory=RetryConfig)


@dataclass(frozen=True)
class ComparisonConfig:
    similarity_method: str = "tfidf"
    tfidf_weight: float = 0.5
    lcs_weight: float = 0.5
    similarity_threshold: float = 0.6
    high_similarity: float = 0.85
    difference_trigger: float = 0.4
    uniqueness_threshold: float = 0.3
    min_paragraph_length: int = 10
    max_units_per_ai: int = 100


@dataclass(frozen=True)
class AppConfig:
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)
    comparison: ComparisonConfig = field(default_factory=ComparisonConfig)
    rate_limits: dict[str, RateLimitConfig] = field(default_factory=dict)
    tracing_enabled: bool = False
    metrics_enabled: bool = False


def load_config(config_path: str | Path | None = None) -> AppConfig:
    """Load configuration from YAML file, falling back to defaults."""
    if config_path is None:
        config_path = Path(__file__).parent.parent / "config" / "default.yaml"

    config_path = Path(config_path)
    if not config_path.exists():
        return AppConfig()

    with open(config_path, encoding="utf-8") as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}

    scheduler_raw = raw.get("scheduler", {})
    scheduler = SchedulerConfig(
        max_concurrent_tasks=scheduler_raw.get("max_concurrent_tasks", 2),
        ai_min_interval_ms=scheduler_raw.get("ai_min_interval_ms", 2000),
        default_timeout_ms=scheduler_raw.get("default_timeout_ms", 120000),
        soft_timeout_ms=scheduler_raw.get("soft_timeout_ms", 60000),
        hard_timeout_ms=scheduler_raw.get("hard_timeout_ms", 180000),
        retry=RetryConfig(**scheduler_raw.get("retry", {})),
    )

    comparison_raw = raw.get("comparison", {})
    comparison = ComparisonConfig(**comparison_raw) if comparison_raw else ComparisonConfig()

    rate_limits: dict[str, RateLimitConfig] = {}
    for ai_id, rl_raw in raw.get("rate_limits", {}).items():
        rate_limits[ai_id] = RateLimitConfig(**rl_raw)

    return AppConfig(scheduler=scheduler, comparison=comparison, rate_limits=rate_limits)
