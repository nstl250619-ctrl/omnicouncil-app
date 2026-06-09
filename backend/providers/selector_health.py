"""Selector Health Checker — detects selector degradation at runtime.

Monitors consecutive failures of CSS selectors and provides fallback
selectors when the primary ones fail.

Usage:
    checker = SelectorHealthChecker(config.page, failure_threshold=5)
    ok, fallback = await checker.check_input_selector(page)
    if not ok:
        # selector degraded, use fallback or trigger recovery
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from engine.contracts import PageInteractionConfig

logger = logging.getLogger(__name__)


@dataclass
class SelectorHealthRecord:
    """Health record for a single selector."""
    selector: str
    consecutive_failures: int = 0
    last_success: float = 0.0
    last_failure: float = 0.0
    last_error: str | None = None


class SelectorHealthChecker:
    """Monitors selector health and provides fallbacks.

    Tracks consecutive failures per selector. When a selector exceeds
    the failure threshold, reports degradation and suggests fallbacks.
    """

    def __init__(
        self,
        config: PageInteractionConfig,
        failure_threshold: int = 5,
    ) -> None:
        self._config = config
        self._threshold = failure_threshold
        self._records: dict[str, SelectorHealthRecord] = {}

    @property
    def is_degraded(self) -> bool:
        """True if any selector has exceeded the failure threshold."""
        return any(
            r.consecutive_failures >= self._threshold
            for r in self._records.values()
        )

    @property
    def degraded_selectors(self) -> list[str]:
        """List of selectors that have exceeded the failure threshold."""
        return [
            r.selector for r in self._records.values()
            if r.consecutive_failures >= self._threshold
        ]

    def record_success(self, selector: str) -> None:
        """Record a successful selector use."""
        if selector not in self._records:
            self._records[selector] = SelectorHealthRecord(selector=selector)
        rec = self._records[selector]
        rec.consecutive_failures = 0
        rec.last_success = time.time()
        rec.last_error = None

    def record_failure(self, selector: str, error: str = "") -> None:
        """Record a selector failure."""
        if selector not in self._records:
            self._records[selector] = SelectorHealthRecord(selector=selector)
        rec = self._records[selector]
        rec.consecutive_failures += 1
        rec.last_failure = time.time()
        rec.last_error = error

        if rec.consecutive_failures >= self._threshold:
            logger.warning(
                "SelectorHealth: '%s' exceeded threshold (%d failures)",
                selector, rec.consecutive_failures,
            )

    def get_health_report(self) -> dict[str, dict]:
        """Return health report for all tracked selectors."""
        return {
            sel: {
                "consecutive_failures": r.consecutive_failures,
                "last_success": r.last_success,
                "last_failure": r.last_failure,
                "last_error": r.last_error,
                "degraded": r.consecutive_failures >= self._threshold,
            }
            for sel, r in self._records.items()
        }

    async def check_input_selector(self, page: Any) -> tuple[bool, str | None]:
        """Check if any input selector works, with fallback support.

        Returns:
            (ok, working_selector): True if a selector works, with the selector string.
        """
        # Try primary selectors
        for sel in self._config.input_selectors:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=1000):
                    self.record_success(sel)
                    return True, sel
            except Exception as e:
                self.record_failure(sel, str(e))

        # Try fallback selectors
        for sel in self._config.fallback_input_selectors:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=1000):
                    self.record_success(sel)
                    return True, sel
            except Exception as e:
                self.record_failure(sel, str(e))

        return False, None

    async def check_response_selector(self, page: Any) -> tuple[bool, str | None]:
        """Check if any response selector matches content, with fallback support."""
        # Try primary selectors
        for sel in self._config.response_selectors:
            try:
                elements = page.locator(sel)
                count = await elements.count()
                if count > 0:
                    self.record_success(sel)
                    return True, sel
            except Exception as e:
                self.record_failure(sel, str(e))

        # Try fallback selectors
        for sel in self._config.fallback_response_selectors:
            try:
                elements = page.locator(sel)
                count = await elements.count()
                if count > 0:
                    self.record_success(sel)
                    return True, sel
            except Exception as e:
                self.record_failure(sel, str(e))

        return False, None
