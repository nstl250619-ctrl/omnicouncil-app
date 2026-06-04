"""RateLimiter — per-AI rate limiting with cooldown."""

from __future__ import annotations

import time
from collections import defaultdict

from shared.config import RateLimitConfig


class RateLimiter:
    """Per-AI rate limiter with cooldown support.

    Default limits are used for AIs without explicit config.
    """

    DEFAULT_CONFIG = RateLimitConfig()

    def __init__(self, configs: dict[str, RateLimitConfig] | None = None) -> None:
        self._configs = configs or {}
        self._timestamps: dict[str, list[float]] = defaultdict(list)
        self._cooldown_until: dict[str, float] = defaultdict(float)
        self._request_count: dict[str, int] = defaultdict(int)

    def _get_config(self, ai_id: str) -> RateLimitConfig:
        return self._configs.get(ai_id, self.DEFAULT_CONFIG)

    def allow(self, ai_id: str) -> bool:
        """Check if a request is allowed for this AI."""
        config = self._get_config(ai_id)
        now = time.time()

        # Check cooldown
        if now < self._cooldown_until[ai_id]:
            return False

        # Clean old timestamps (older than 60s)
        cutoff = now - 60
        self._timestamps[ai_id] = [t for t in self._timestamps[ai_id] if t > cutoff]

        # Check per-minute limit
        if len(self._timestamps[ai_id]) >= config.max_per_minute:
            return False

        # Check minimum interval
        if self._timestamps[ai_id]:
            last = self._timestamps[ai_id][-1]
            if (now - last) * 1000 < config.min_interval_ms:
                return False

        return True

    def record(self, ai_id: str) -> None:
        """Record a successful request."""
        config = self._get_config(ai_id)
        now = time.time()

        self._timestamps[ai_id].append(now)
        self._request_count[ai_id] += 1

        # Check if cooldown should trigger
        if self._request_count[ai_id] >= config.cooldown_after_n:
            self._cooldown_until[ai_id] = now + config.cooldown_duration_ms / 1000
            self._request_count[ai_id] = 0

    def reset(self, ai_id: str) -> None:
        """Reset rate limiter for a specific AI."""
        self._timestamps.pop(ai_id, None)
        self._cooldown_until.pop(ai_id, None)
        self._request_count.pop(ai_id, None)

    def reset_all(self) -> None:
        """Reset all rate limiters."""
        self._timestamps.clear()
        self._cooldown_until.clear()
        self._request_count.clear()
