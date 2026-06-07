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
            from shared.types import SessionState
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


def _get_storage() -> LocalStorage:
    state = _try_state()
    if state and state.storage is not None:
        return state.storage
    # Fallback: create a local instance (lifespan not running or storage not set)
    return LocalStorage()
