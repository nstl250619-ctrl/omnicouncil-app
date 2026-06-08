"""HTTP route handlers for OmniCouncil API.

Extracted from main.py — all @app.get / @app.post / @app.delete routes.
"""
from __future__ import annotations

import asyncio
import time

from fastapi import HTTPException

from shared.app_state import AppState
from shared.logger import get_logger
from storage.local import LocalStorage
from ws.connection import ws_manager

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


# ========== Background reauth helper ==========


async def _do_reauth(ai_id: str, login_url: str, browser_engine) -> None:
    """Run reauth in background and broadcast result via WebSocket."""
    from shared.logger import get_logger as _gl
    _log = _gl(__name__)
    try:
        _log.info("Reauth starting for %s at %s", ai_id, login_url)
        success, error_msg = await browser_engine.login(ai_id, login_url)
        if success:
            await ws_manager.broadcast({
                "type": "recovery_success",
                "data": {"ai_id": ai_id, "message": f"{ai_id} 已自动恢复"},
            })
        else:
            await ws_manager.broadcast({
                "type": "session_expired",
                "data": {"ai_id": ai_id, "message": f"{ai_id} 重认证失败: {error_msg}"},
            })
    except Exception as e:
        await ws_manager.broadcast({
            "type": "ai_unavailable",
            "data": {"ai_id": ai_id, "message": f"{ai_id} 异常: {str(e)}"},
        })


def register_routes(app) -> None:
    """Register all HTTP routes on the FastAPI app."""

    @app.get("/health")
    async def health():
        ai_status = []
        state = _try_state()
        if state and state.ai_manager:
            for s in state.ai_manager.get_ready_ais():
                ai_status.append({"ai_id": s.ai_id, "status": s.status.value})
        return {"status": "ok", "version": "0.1.0", "timestamp": time.time(), "ais": ai_status}

    @app.get("/metrics")
    async def metrics():
        """Prometheus-style metrics endpoint."""
        from shared.metrics import MetricsCollector
        mc = MetricsCollector.instance()
        return mc.snapshot()

    @app.get("/health/detailed")
    async def health_detailed():
        """Detailed per-AI health status."""
        state = _try_state()
        result = {"status": "ok", "providers": []}
        if state and state.ai_manager:
            for s in state.ai_manager.get_ready_ais():
                provider_info = {
                    "ai_id": s.ai_id,
                    "ai_name": s.ai_name,
                    "status": s.status.value,
                    "consecutive_failures": s.consecutive_failures,
                }
                # Add session state from browser engine if available
                if state.browser_engine and hasattr(state.browser_engine, "get_session_state"):
                    provider_info["session_state"] = state.browser_engine.get_session_state(s.ai_id)
                result["providers"].append(provider_info)
        return result

    @app.get("/api/sessions/status")
    async def get_sessions_status():
        """Check which AIs have saved login sessions."""
        state = _try_state()
        if not state or not state.browser_engine:
            return {"sessions": {}, "authenticated": []}
        sessions = state.browser_engine.check_all_sessions()
        # Backward-compatible authenticated list: only truly valid sessions
        authenticated = [
            ai_id for ai_id, s in sessions.items()
            if s == "authenticated"
        ]
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
        """Return RuntimeHealth for all AI platforms.

        Returns a dict keyed by ai_id, each value with:
        { state, browser_alive, page_alive, session_valid, last_heartbeat }
        """
        state = _try_state()
        if not state or not state.ai_manager:
            return {}

        health_map: dict[str, dict] = {}
        now = time.time()

        for s in state.ai_manager.get_ready_ais():
            backend_status = s.status.value
            health_map[s.ai_id] = {
                "state": _map_state(backend_status),
                "browser_alive": backend_status not in ("error", "circuit_open", "unavailable", "shutdown"),
                "page_alive": backend_status not in ("error", "circuit_open", "unavailable", "shutdown"),
                "session_valid": backend_status in ("ready", "busy"),
                "last_heartbeat": s.last_check_at or now,
            }

        # Override with deeper provider_runtime health data when available
        if state.provider_runtime:
            try:
                reports = await state.provider_runtime.health_check_all()
                for pid, report in reports.items():
                    if pid not in health_map:
                        continue
                    entry = health_map[pid]
                    entry["session_valid"] = report.login_valid
                    entry["state"] = _map_state(report.status.value)
                    if report.checked_at:
                        entry["last_heartbeat"] = report.checked_at
                    # Derive browser/page aliveness from health status
                    if report.status.value in ("failed",):
                        entry["browser_alive"] = False
                        entry["page_alive"] = False
            except Exception as exc:
                logger.warning("Failed to get runtime health reports: %s", exc)

        return health_map

    # ========== Provider Management ==========

    @app.post("/api/providers/{name}/reauth")
    async def reauth_provider(name: str):
        """Trigger re-authentication / recovery for a provider."""
        state = _try_state()
        if not state:
            raise HTTPException(503, "Backend not initialized")

        browser_engine = state.browser_engine
        provider_registry = state.provider_registry

        if not browser_engine:
            raise HTTPException(503, "Browser engine not initialized")

        provider = provider_registry.get(name) if provider_registry else None
        if not provider:
            raise HTTPException(404, f"Provider '{name}' not found")

        cfg = provider.config()
        asyncio.create_task(_do_reauth(name, cfg.login_url, browser_engine))

        return {"status": "reauth_started", "provider": name}

    @app.delete("/api/providers/{name}")
    async def delete_provider(name: str):
        """Delete / unregister a provider."""
        state = _try_state()
        if not state or not state.provider_runtime:
            raise HTTPException(503, "Backend not initialized")

        try:
            await state.provider_runtime.unregister(name)
            logger.info("Provider %s: deleted", name)
            return {"status": "deleted", "provider": name}
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
