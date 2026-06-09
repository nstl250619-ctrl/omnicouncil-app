"""Dashboard API — Provider health monitoring endpoints.

Provides REST endpoints for the frontend Dashboard component
to display real-time provider health, metrics, and alerts.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, HTTPException

from shared.app_state import AppState
from shared.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def _try_state() -> AppState | None:
    try:
        return AppState.instance()
    except RuntimeError:
        return None


@router.get("/health")
async def dashboard_health():
    """Return comprehensive health for all providers."""
    state = _try_state()
    registry = getattr(state, "runtime_registry", None) if state else None
    if registry is None:
        return {"providers": {}, "timestamp": time.time()}

    providers = {}
    for platform, engine in registry.get_all().items():
        try:
            health = await engine.check_health()
            lifecycle_state = "unknown"
            if hasattr(engine, "_session_lifecycle") and engine._session_lifecycle is not None:
                lifecycle_state = engine._session_lifecycle.state.value

            providers[platform] = {
                "state": health.state.value,
                "browser_alive": health.browser_alive,
                "page_alive": health.page_alive,
                "session_valid": health.session_valid,
                "last_heartbeat": health.last_heartbeat,
                "recovery_attempts": health.recovery_attempts,
                "uptime_seconds": health.uptime_seconds,
                "lifecycle_state": lifecycle_state,
            }
        except Exception as e:
            providers[platform] = {
                "state": "error",
                "error": str(e),
            }

    return {"providers": providers, "timestamp": time.time()}


@router.get("/metrics")
async def dashboard_metrics():
    """Return runtime metrics for all providers."""
    from engine.contracts import RuntimeMetrics

    state = _try_state()
    registry = getattr(state, "runtime_registry", None) if state else None
    if registry is None:
        return {"providers": {}, "timestamp": time.time()}

    providers = {}
    for platform, engine in registry.get_all().items():
        try:
            metrics = engine.metrics()
            if isinstance(metrics, RuntimeMetrics):
                providers[platform] = metrics.snapshot()
        except Exception:
            continue

    return {"providers": providers, "timestamp": time.time()}


@router.get("/selector-health")
async def dashboard_selector_health():
    """Return selector health for all providers."""
    state = _try_state()
    registry = getattr(state, "runtime_registry", None) if state else None
    if registry is None:
        return {"providers": {}, "timestamp": time.time()}

    providers = {}
    for platform, engine in registry.get_all().items():
        try:
            config = engine.get_platform_config()
            if config.page is not None:
                from providers.selector_health import SelectorHealthChecker
                checker = SelectorHealthChecker(config.page)
                providers[platform] = {
                    "degraded": checker.is_degraded,
                    "degraded_selectors": checker.degraded_selectors,
                    "report": checker.get_health_report(),
                }
        except Exception:
            continue

    return {"providers": providers, "timestamp": time.time()}
