"""ProviderHealthMonitor — health check and monitoring."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from providers.base.provider import BaseProvider

logger = logging.getLogger(__name__)


class HealthStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass
class HealthReport:
    provider_id: str
    status: HealthStatus = HealthStatus.UNKNOWN
    latency_ms: float = 0.0
    login_valid: bool = False
    error: str | None = None
    checked_at: float = 0.0
    consecutive_failures: int = 0


class ProviderHealthMonitor:
    """Monitors health of all registered providers."""

    def __init__(self, max_consecutive_failures: int = 5) -> None:
        self._reports: dict[str, HealthReport] = {}
        self._max_failures = max_consecutive_failures

    async def check(self, provider: BaseProvider) -> HealthReport:
        """Run health check on a single provider."""
        pid = provider.ai_id
        start = time.time()

        try:
            # Check provider status
            ps = provider.get_status()
            latency = (time.time() - start) * 1000

            login_valid = ps.status.value not in ("login_required", "error")

            if ps.status.value == "ready":
                status = HealthStatus.HEALTHY
            elif ps.status.value == "busy":
                status = HealthStatus.HEALTHY
            elif ps.status.value == "login_required":
                status = HealthStatus.DEGRADED
            elif ps.status.value == "error":
                status = HealthStatus.FAILED
            else:
                status = HealthStatus.UNKNOWN

            report = HealthReport(
                provider_id=pid,
                status=status,
                latency_ms=round(latency, 1),
                login_valid=login_valid,
                checked_at=time.time(),
            )

            # Reset consecutive failures on success
            if pid in self._reports and report.status != HealthStatus.FAILED:
                report.consecutive_failures = 0

        except Exception as e:
            prev_failures = self._reports.get(pid, HealthReport(pid)).consecutive_failures
            report = HealthReport(
                provider_id=pid,
                status=HealthStatus.FAILED,
                error=str(e),
                checked_at=time.time(),
                consecutive_failures=prev_failures + 1,
            )

        self._reports[pid] = report
        return report

    async def check_all(self, providers: list[BaseProvider]) -> dict[str, HealthReport]:
        """Run health check on all providers."""
        for p in providers:
            await self.check(p)
        return dict(self._reports)

    def get_report(self, provider_id: str) -> HealthReport | None:
        return self._reports.get(provider_id)

    def get_all_reports(self) -> dict[str, HealthReport]:
        return dict(self._reports)

    def is_healthy(self, provider_id: str) -> bool:
        report = self._reports.get(provider_id)
        return report is not None and report.status == HealthStatus.HEALTHY

    def get_unhealthy_providers(self) -> list[str]:
        return [
            pid for pid, r in self._reports.items()
            if r.status in (HealthStatus.FAILED, HealthStatus.DEGRADED)
        ]
