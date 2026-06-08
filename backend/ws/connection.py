"""WebSocket connection manager and message handlers.

Extracted from main.py — ConnectionManager, websocket_endpoint, and all handle_* functions.
"""
from __future__ import annotations

import asyncio
import contextlib
import sys
import traceback
import uuid

from fastapi import WebSocket, WebSocketDisconnect

from shared.app_state import AppState
from shared.logger import get_logger
from shared.types import QueryRequest, TaskMode

logger = get_logger(__name__)


# ========== Connection Manager ==========

class ConnectionManager:
    """Manages WebSocket connections with task-scoped event routing."""

    def __init__(self):
        self.active_connections: list[WebSocket] = []
        # Maps task_id to the set of WebSocket connections that initiated it.
        # Used by send_task_event to route events only to the originating client.
        self._task_owners: dict[str, set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info("WebSocket connected. Total: %d", len(self.active_connections))

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        # Clean up task ownership for this connection
        for task_id in list(self._task_owners.keys()):
            owners = self._task_owners.get(task_id)
            if owners:
                owners.discard(websocket)
                if not owners:
                    del self._task_owners[task_id]
        logger.info("WebSocket disconnected. Total: %d", len(self.active_connections))

    def register_task(self, websocket: WebSocket, task_id: str) -> None:
        """Associate a task_id with the WebSocket connection that created it."""
        if task_id not in self._task_owners:
            self._task_owners[task_id] = set()
        self._task_owners[task_id].add(websocket)

    async def broadcast(self, message: dict):
        """Send message to all connected clients (system-wide events only)."""
        dead = []
        for connection in self.active_connections[:]:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.warning("Failed to send to WebSocket: %s", e)
                dead.append(connection)
        for conn in dead:
            self.disconnect(conn)

    async def send_task_event(self, message: dict, task_id: str | None = None):
        """Send an event to the connection(s) that own the given task_id.

        If the owning connection is gone (e.g. frontend HMR / tab switch),
        falls back to a full ``broadcast()`` so events are never silently lost.
        """
        if task_id is None:
            return await self.broadcast(message)
        owners = self._task_owners.get(task_id)
        if not owners:
            # No registered owner — broadcast as safety net so browser clients
            # that reconnected (HMR / tab switch) still receive the event.
            logger.debug("Task %s: no registered owner, falling back to broadcast", task_id)
            return await self.broadcast(message)
        dead = []
        for connection in list(owners):
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.warning("Failed to send task event to WebSocket: %s", e)
                dead.append(connection)
        for conn in dead:
            self.disconnect(conn)
            owners.discard(conn)

    async def send_personal(self, websocket: WebSocket, message: dict):
        """Send message to a specific client."""
        with contextlib.suppress(Exception):
            await websocket.send_json(message)


# Module-level singleton
ws_manager = ConnectionManager()


# ========== Global Exception Handler ==========

class GlobalExceptionHandler:
    """Catches unhandled exceptions and pushes them to frontend via WebSocket."""

    def __init__(self, ws: ConnectionManager):
        self.ws = ws

    def install(self):
        sys.excepthook = self._sync_hook

    def _sync_hook(self, exc_type, exc_value, exc_tb):
        error_info = self._format(exc_type, exc_value)
        logger.error("Unhandled exception: %s - %s", exc_type.__name__, exc_value)
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.call_soon_threadsafe(
                    lambda: asyncio.ensure_future(
                        self.ws.broadcast({"type": "error", "data": error_info})
                    )
                )
        except RuntimeError:
            pass

    def _format(self, exc_type, exc_value) -> dict:
        error_map = {
            "ConnectionError": {"error": "网络连接失败", "recoverable": True, "suggestion": "请检查网络连接后重试", "code": "NETWORK_ERROR"},
            "TimeoutError": {"error": "请求超时", "recoverable": True, "suggestion": "AI 响应时间过长，请稍后重试", "code": "TIMEOUT"},
            "TargetClosedError": {"error": "浏览器连接断开", "recoverable": True, "suggestion": "正在自动重连...", "code": "BROWSER_CLOSED"},
            "AuthenticationError": {"error": "登录已过期", "recoverable": False, "suggestion": "请重新登录 AI 账号", "code": "AUTH_EXPIRED"},
        }
        exc_name = exc_type.__name__ if exc_type else "Unknown"
        return error_map.get(exc_name, {"error": str(exc_value), "recoverable": False, "suggestion": "请重启应用", "code": "UNKNOWN"})


# ========== WebSocket Endpoint ==========

def _try_state() -> AppState | None:
    """Try to get AppState — returns None if lifespan hasn't run."""
    try:
        return AppState.instance()
    except RuntimeError:
        return None


async def websocket_endpoint(websocket: WebSocket):
    """Main WebSocket endpoint — receives and routes all messages."""
    await ws_manager.connect(websocket)

    # Send initial status
    state = _try_state()
    ai_status = []
    if state and state.ai_manager:
        for s in state.ai_manager.get_ready_ais():
            ai_status.append({"ai_id": s.ai_id, "ai_name": s.ai_name, "status": s.status.value})

    await ws_manager.send_personal(websocket, {
        "type": "engine_status",
        "data": {"connected": True, "ais": ai_status}
    })

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            logger.debug("WS recv: type=%s data=%s", msg_type, data.get("data", {}))

            if msg_type == "submit_query":
                payload = data.get("data", {})
                if not isinstance(payload.get("query", ""), str):
                    await ws_manager.send_personal(websocket, {
                        "type": "error", "data": {"error": "Invalid query", "recoverable": True}
                    })
                    continue
                if not isinstance(payload.get("ai_ids", []), list):
                    await ws_manager.send_personal(websocket, {
                        "type": "error", "data": {"error": "Invalid ai_ids", "recoverable": True}
                    })
                    continue
                await handle_submit_query(payload, websocket)
            elif msg_type == "cancel_task":
                await handle_cancel_task(data.get("data", {}))
            elif msg_type == "get_status":
                await handle_get_status(websocket)
            elif msg_type == "get_ais":
                await handle_get_ais(websocket)
            elif msg_type == "check_sessions":
                await handle_check_sessions(websocket)
            elif msg_type == "reauth":
                await handle_reauth(data.get("data", {}))
            elif msg_type == "ping":
                await ws_manager.send_personal(websocket, {"type": "pong", "data": {}})

    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception:
        logger.exception("WebSocket error")
        ws_manager.disconnect(websocket)


# ========== Message Handlers ==========

async def handle_submit_query(data: dict, websocket: WebSocket | None = None):
    """Handle query submission from frontend with task-scoped routing."""
    state = _try_state()
    scheduler = state.scheduler if state else None
    collector = state.collector if state else None

    query = data.get("query", "")
    ai_ids = data.get("ai_ids", ["deepseek"])
    mode = data.get("mode", "parallel")

    if not query.strip():
        await ws_manager.broadcast({
            "type": "error",
            "data": {"error": "问题不能为空", "recoverable": True, "code": "EMPTY_QUERY"}
        })
        return

    if not scheduler:
        await ws_manager.broadcast({
            "type": "error",
            "data": {"error": "服务未就绪", "recoverable": False, "code": "NOT_READY"}
        })
        return

    task_id = f"task_{uuid.uuid4().hex[:12]}"

    # Register this connection as the task owner
    if websocket:
        ws_manager.register_task(websocket, task_id)

    logger.info("Task %s: submitting query to %s", task_id, ai_ids)

    if collector:
        collector.set_query(task_id, query, TaskMode.PARALLEL)

    await ws_manager.send_task_event({
        "type": "progress",
        "data": {"task_id": task_id, "completed": 0, "total": len(ai_ids), "current_ai": ""}
    }, task_id=task_id)

    try:
        request = QueryRequest(
            query=query,
            selected_ai_ids=ai_ids,
            mode=TaskMode(mode) if mode in ("parallel", "sequential") else TaskMode.PARALLEL,
        )
        handle = await scheduler.submit_query(request)

        await ws_manager.send_task_event({
            "type": "task_created",
            "data": {"task_id": handle.task_id, "status": handle.status.value}
        }, task_id=task_id)

    except Exception as e:
        logger.exception("Failed to submit query")
        await ws_manager.send_task_event({
            "type": "error",
            "data": {"task_id": task_id, "error": str(e), "recoverable": True, "code": "SUBMIT_FAILED"}
        }, task_id=task_id)


async def handle_cancel_task(data: dict):
    """Handle task cancellation."""
    state = _try_state()
    scheduler = state.scheduler if state else None
    task_id = data.get("task_id")
    if scheduler and task_id:
        scheduler.cancel_task(task_id)
        logger.info("Task %s: cancelled", task_id)
        await ws_manager.broadcast({
            "type": "task_cancelled",
            "data": {"task_id": task_id}
        })


async def handle_get_status(websocket: WebSocket):
    """Handle status request."""
    state = _try_state()
    ai_status = []
    if state and state.ai_manager:
        for s in state.ai_manager.get_ready_ais():
            ai_status.append({"ai_id": s.ai_id, "ai_name": s.ai_name, "status": s.status.value})

    await ws_manager.send_personal(websocket, {
        "type": "status",
        "data": {"connected": True, "ais": ai_status}
    })


async def handle_get_ais(websocket: WebSocket):
    """Get list of all registered providers via RuntimeRegistry."""
    state = _try_state()
    registry = getattr(state, "runtime_registry", None) if state else None
    if not registry:
        await ws_manager.send_personal(websocket, {"type": "ai_list", "data": []})
        return

    ais = []
    for platform in registry.get_platforms():
        engine = registry.get(platform)
        if engine:
            ais.append({
                "ai_id": platform,
                "display_name": platform,
                "state": engine.state.value if hasattr(engine, "state") else "unknown",
            })
    await ws_manager.send_personal(websocket, {"type": "ai_list", "data": ais})


async def handle_check_sessions(websocket: WebSocket):
    """Check which AIs have valid sessions via RuntimeRegistry."""
    state = _try_state()
    registry = getattr(state, "runtime_registry", None) if state else None
    if not registry:
        await ws_manager.send_personal(websocket, {
            "type": "sessions_status",
            "data": {"sessions": {}}
        })
        return

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

    await ws_manager.send_personal(websocket, {
        "type": "sessions_status",
        "data": {
            "sessions": sessions,
            "authenticated": authenticated,
        }
    })
    logger.info("Sessions check: authenticated=%s", authenticated)


async def handle_reauth(data: dict):
    """Handle re-authentication via RuntimeRegistry recovery."""
    ai_id = data.get("ai_id")
    if not ai_id:
        return

    logger.info("Reauth requested for %s", ai_id)

    state = _try_state()
    registry = getattr(state, "runtime_registry", None) if state else None

    engine = registry.get(ai_id) if registry else None
    if not engine:
        await ws_manager.broadcast({
            "type": "auth_status",
            "data": {"ai_id": ai_id, "status": "failed", "message": f"未知的 AI: {ai_id}"}
        })
        return

    await ws_manager.broadcast({
        "type": "auth_status",
        "data": {"ai_id": ai_id, "status": "connecting", "message": f"正在尝试恢复 {ai_id}..."}
    })

    asyncio.create_task(_do_recovery(ai_id, engine))


async def _do_recovery(ai_id: str, engine):
    """Run recovery in background. If recovery fails, open manual login.

    After successful login, restarts the engine so the main browser
    context picks up the new cookies from disk.
    """
    try:
        logger.info("Starting recovery for %s", ai_id)
        success = await engine.attempt_recovery()
        logger.info("Recovery result for %s: success=%s", ai_id, success)

        if success:
            await ws_manager.broadcast({
                "type": "auth_status",
                "data": {"ai_id": ai_id, "status": "authenticated", "message": "恢复成功"}
            })
            logger.info("Broadcasted authenticated for %s", ai_id)
            return

        # Recovery failed — try manual login
        logger.info("Recovery failed for %s, attempting manual login", ai_id)
    except Exception as e:
        logger.warning("Recovery exception for %s: %s, attempting manual login", ai_id, e)

    # Manual login fallback
    try:
        await ws_manager.broadcast({
            "type": "auth_status",
            "data": {"ai_id": ai_id, "status": "connecting", "message": "正在打开登录窗口..."}
        })

        success, error_msg = await engine.login(timeout_s=300)

        if success:
            # Login succeeded — restart engine to pick up new cookies
            logger.info("Login succeeded for %s, restarting engine to load new cookies", ai_id)
            try:
                await engine.shutdown()
                await engine.boot()
                logger.info("Engine restarted for %s, new state: %s", ai_id, engine.state.value)
            except Exception as restart_err:
                logger.warning("Engine restart failed for %s: %s", ai_id, restart_err)

            await ws_manager.broadcast({
                "type": "auth_status",
                "data": {"ai_id": ai_id, "status": "authenticated", "message": "登录成功"}
            })
            logger.info("Manual login succeeded for %s", ai_id)
        else:
            await ws_manager.broadcast({
                "type": "auth_status",
                "data": {"ai_id": ai_id, "status": "failed", "message": f"登录失败: {error_msg}"}
            })
            logger.warning("Manual login failed for %s: %s", ai_id, error_msg)
    except Exception as e:
        tb = traceback.format_exc()
        logger.error("LOGIN EXCEPTION for %s: %s\n%s", ai_id, e, tb)
        await ws_manager.broadcast({
            "type": "auth_status",
            "data": {"ai_id": ai_id, "status": "failed", "message": f"登录异常: {str(e)}"}
        })
