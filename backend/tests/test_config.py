"""Unit tests for shared/config.py."""

from __future__ import annotations

from shared.config import (
    AppConfig,
    ComparisonConfig,
    RateLimitConfig,
    RetryConfig,
    SchedulerConfig,
    load_config,
)


class TestSchedulerConfig:
    def test_defaults(self):
        cfg = SchedulerConfig()
        assert cfg.max_concurrent_tasks == 2
        assert cfg.ai_min_interval_ms == 2000
        assert cfg.default_timeout_ms == 120000
        assert cfg.soft_timeout_ms == 60000
        assert cfg.hard_timeout_ms == 180000

    def test_frozen(self):
        cfg = SchedulerConfig()
        try:
            cfg.max_concurrent_tasks = 999
            assert False, "Should be frozen"
        except AttributeError:
            pass


class TestComparisonConfig:
    def test_defaults(self):
        cfg = ComparisonConfig()
        assert cfg.similarity_method == "tfidf"
        assert cfg.similarity_threshold == 0.6
        assert cfg.high_similarity == 0.85
        assert cfg.min_paragraph_length == 10


class TestRateLimitConfig:
    def test_defaults(self):
        cfg = RateLimitConfig()
        assert cfg.max_per_minute == 10
        assert cfg.min_interval_ms == 3000


class TestRetryConfig:
    def test_defaults(self):
        cfg = RetryConfig()
        assert cfg.max_retries == 2
        assert cfg.backoff_multiplier == 1.5


class TestAppConfig:
    def test_defaults(self):
        cfg = AppConfig()
        assert isinstance(cfg.scheduler, SchedulerConfig)
        assert isinstance(cfg.comparison, ComparisonConfig)
        assert cfg.rate_limits == {}
        assert cfg.tracing_enabled is False
        assert cfg.metrics_enabled is False


class TestLoadConfig:
    def test_load_nonexistent_returns_defaults(self):
        cfg = load_config("/nonexistent/path.yaml")
        assert isinstance(cfg, AppConfig)
        assert cfg.scheduler.max_concurrent_tasks == 2

    def test_load_none_returns_defaults(self):
        cfg = load_config(None)
        assert isinstance(cfg, AppConfig)
