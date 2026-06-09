"""HTTP route handlers for OmniCouncil API.

Extracted from main.py — all @app.get / @app.post / @app.delete routes.
"""
from __future__ import annotations

import time

from fastapi import HTTPException

from shared.app_state import AppState
from shared.logger import get_logger
from storage.local import LocalStorage

logger = get_logger(__name__)


def _try_state() -> AppState | None:
    """Try to get AppState — returns None if lifespan hasn't run."""
    try:
        return AppState.instance()
    except RuntimeError:
        return None


# ========== Health state mapping ==========

_HEALTH_STATE_MAP = {
    "ready": "healthy",
    "busy": "healthy",
    "login_required": "login_required",
    "captcha_required": "login_required",
    "error": "unavailable",
    "rate_limited": "degraded",
    "circuit_open": "unavailable",
    "initializing": "degraded",
    "unknown": "unavailable",
    "shutdown": "unavailable",
    "recovering": "degraded",
    "unavailable": "unavailable",
    "degraded": "degraded",
    "healthy": "healthy",
    "failed": "unavailable",
}


def _map_state(status: str) -> str:
    return _HEALTH_STATE_MAP.get(status, "unavailable")


def register_routes(app) -> None:
    """Register all HTTP routes on the FastAPI app."""

    @app.get("/health")
    async def health():
        ai_status = []
        state = _try_state()
        if state and state.ai_manager:
            for s in state.ai_manager.get_ready_ais():
                ai_status.append({"ai_id": s.ai_id, "status": s.status.value})
        return {"status": "ok", "version": "0.2.0", "timestamp": time.time(), "ais": ai_status}

    @app.get("/metrics")
    async def metrics():
        """Prometheus-style metrics endpoint."""
        from shared.metrics import MetricsCollector
        mc = MetricsCollector.instance()
        return mc.snapshot()

    @app.get("/metrics/runtime")
    async def metrics_runtime():
        """Per-platform RuntimeMetrics.

        Aggregates ``RuntimeMetrics`` from every ``AIRuntimeEngine``
        held by the active ``RuntimeRegistry``.
        """
        from engine.contracts import RuntimeMetrics

        state = _try_state()
        result: dict[str, dict[str, int]] = {}
        if state is None:
            return {"platforms": result, "timestamp": time.time()}

        registry = getattr(state, "runtime_registry", None)
        if registry is None:
            return {"platforms": result, "timestamp": time.time()}

        try:
            engines = registry.all()
        except Exception:
            engines = list(getattr(registry, "_engines", {}).values())

        for engine in engines:
            try:
                metrics_obj = engine.metrics()
                if isinstance(metrics_obj, RuntimeMetrics):
                    result[engine.platform] = metrics_obj.snapshot()
            except Exception:
                continue

        return {"platforms": result, "timestamp": time.time()}

    @app.get("/health/detailed")
    async def health_detailed():
        """Detailed per-AI health status using RuntimeRegistry."""
        state = _try_state()
        result = {"status": "ok", "providers": []}

        registry = getattr(state, "runtime_registry", None) if state else None
        if registry is None:
            return result

        for platform, engine in registry.get_all().items():
            try:
                health = await engine.check_health()
                provider_info = {
                    "ai_id": platform,
                    "ai_name": platform,
                    "state": health.state.value,
                    "browser_alive": health.browser_alive,
                    "page_alive": health.page_alive,
                    "session_valid": health.session_valid,
                    "last_heartbeat": health.last_heartbeat,
                }
                result["providers"].append(provider_info)
            except Exception as exc:
                logger.debug("health_detailed: %s failed: %s", platform, exc)
                result["providers"].append({
                    "ai_id": platform,
                    "ai_name": platform,
                    "state": "unavailable",
                    "error": str(exc),
                })

        return result

    @app.get("/api/sessions/status")
    async def get_sessions_status():
        """Check which AIs have valid sessions via RuntimeRegistry."""
        state = _try_state()
        registry = getattr(state, "runtime_registry", None) if state else None
        if registry is None:
            return {"sessions": {}, "authenticated": []}

        sessions: dict[str, str] = {}
        authenticated: list[str] = []

        for platform, engine in registry.get_all().items():
            try:
                health = await engine.check_health()
                if health.session_valid:
                    sessions[platform] = "authenticated"
                    authenticated.append(platform)
                else:
                    sessions[platform] = health.state.value
            except Exception:
                sessions[platform] = "unknown"

        return {"sessions": sessions, "authenticated": authenticated}

    @app.get("/api/sessions")
    async def list_sessions(limit: int = 50):
        """List recent sessions."""
        storage = _get_storage()
        return {"sessions": storage.list_sessions(limit=limit)}

    @app.get("/api/sessions/{session_id}")
    async def get_session(session_id: str):
        """Get a specific session."""
        storage = _get_storage()
        session = storage.load_session(session_id)
        if not session:
            raise HTTPException(404, "Session not found")
        return session

    @app.delete("/api/sessions/{session_id}")
    async def delete_session(session_id: str):
        """Delete a session."""
        storage = _get_storage()
        if storage.delete_session(session_id):
            return {"status": "deleted"}
        raise HTTPException(404, "Session not found")

    @app.delete("/api/sessions")
    async def clear_sessions():
        """Clear all sessions."""
        storage = _get_storage()
        count = storage.clear_all()
        return {"status": "cleared", "count": count}


    # ========== Runtime Health ==========

    @app.get("/api/runtime/health")
    async def runtime_health():
        """Return RuntimeHealth for all AI platforms via RuntimeRegistry.

        Returns a dict keyed by ai_id, each value with:
        { state, browser_alive, page_alive, session_valid, last_heartbeat }
        """
        state = _try_state()
        registry = getattr(state, "runtime_registry", None) if state else None
        if registry is None:
            return {}

        health_map: dict[str, dict] = {}

        for platform, engine in registry.get_all().items():
            try:
                health = await engine.check_health()
                health_map[platform] = {
                    "state": _map_state(health.state.value),
                    "browser_alive": health.browser_alive,
                    "page_alive": health.page_alive,
                    "session_valid": health.session_valid,
                    "last_heartbeat": health.last_heartbeat,
                    "recovery_attempts": health.recovery_attempts,
                    "uptime_seconds": health.uptime_seconds,
                }
            except Exception as exc:
                logger.debug("runtime_health: %s failed: %s", platform, exc)
                health_map[platform] = {
                    "state": "unavailable",
                    "browser_alive": False,
                    "page_alive": False,
                    "session_valid": False,
                    "last_heartbeat": 0,
                    "error": str(exc),
                }

        return health_map

    # ========== Provider Management ==========

    @app.post("/api/providers/{name}/reauth")
    async def reauth_provider(name: str):
        """Trigger recovery for a provider. Falls back to manual login."""
        import asyncio

        state = _try_state()
        if not state:
            raise HTTPException(503, "Backend not initialized")

        registry = getattr(state, "runtime_registry", None)
        if registry is None:
            raise HTTPException(503, "Runtime registry not initialized")

        engine = registry.get(name)
        if engine is None:
            raise HTTPException(404, f"Provider '{name}' not found")

        # Try recovery first
        try:
            success = await engine.attempt_recovery()
            if success:
                return {"status": "recovery_succeeded", "provider": name}
        except Exception:
            pass

        # Recovery failed — open manual login in background
        async def _do_login():
            try:
                # Shutdown engine first to release the profile directory
                logger.info("Shutting down engine for %s before login", name)
                await engine.shutdown()

                success, error_msg = await engine.login(timeout_s=300)
                if success:
                    # Restart engine to pick up new cookies
                    await engine.boot()
                    logger.info("Manual login succeeded for %s, state: %s", name, engine.state.value)
                else:
                    # Still restart engine even if login failed
                    await engine.boot()
                    logger.warning("Manual login failed for %s: %s", name, error_msg)
            except Exception as e:
                logger.error("Login exception for %s: %s", name, e)
                try:
                    await engine.boot()
                except Exception:
                    pass

        asyncio.create_task(_do_login())
        return {"status": "login_started", "provider": name, "message": "正在打开登录窗口..."}

    @app.delete("/api/providers/{name}")
    async def delete_provider(name: str):
        """Unregister a provider via RuntimeRegistry."""
        state = _try_state()
        if not state:
            raise HTTPException(503, "Backend not initialized")

        registry = getattr(state, "runtime_registry", None)
        if registry is None:
            raise HTTPException(503, "Runtime registry not initialized")

        try:
            engine = registry.get(name)
            if engine is None:
                raise HTTPException(404, f"Provider '{name}' not found")
            await engine.shutdown()
            registry.unregister(name)
            logger.info("Provider %s: deleted", name)
            return {"status": "deleted", "provider": name}
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(500, f"Failed to delete provider '{name}': {exc}")

    @app.post("/api/providers")
    async def add_provider(data: dict):
        """Register a new provider (stub — full impl requires provider class)."""
        state = _try_state()
        if not state:
            raise HTTPException(503, "Backend not initialized")

        name = data.get("name", "")
        url = data.get("url", "")

        if not name or not url:
            raise HTTPException(400, "name and url are required")

        logger.info("Add provider requested: %s (%s)", name, data.get("home_url", url))

        # TODO(v2.1): implement dynamic provider registration — currently returns stub response
        return {"status": "added", "provider": {"name": name, "url": url, "home_url": data.get("home_url", "")}}


def _get_storage() -> LocalStorage:
    state = _try_state()
    if state and state.storage is not None:
        return state.storage
    # Fallback: create a local instance (lifespan not running or storage not set)
    return LocalStorage()
