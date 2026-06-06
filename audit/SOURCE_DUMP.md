# OmniCouncil Core Source Dump

Generated: Sat Jun  6 13:32:17 CST 2026

---

# FILE: backend/main.py

```
"""OmniCouncil FastAPI + WebSocket Backend with Engine Integration."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

# Ensure critical Windows env vars are present (Tauri may strip them)
if sys.platform == "win32":
    if "LOCALAPPDATA" not in os.environ:
        user_profile = os.path.expanduser("~")
        os.environ["LOCALAPPDATA"] = os.path.join(user_profile, "AppData", "Local")
        os.environ["USERPROFILE"] = user_profile

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

# Add backend to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from shared.event_bus import EventBus
from shared.config import load_config
from shared.types import TaskMode, QueryRequest
from engine.layers.layer1_ai_access.manager import AIAccessManager
from engine.layers.layer1_ai_access.adapters.deepseek_browser import DeepSeekBrowserAdapter
from engine.layers.layer1_ai_access.adapters.qianwen_browser import QianwenBrowserAdapter
from engine.layers.layer2_scheduler.scheduler_center import SchedulerCenter
from engine.layers.layer3_collector.result_collector import ResultCollector
from engine.layers.layer4_comparison.comparison_engine import ComparisonEngine
from browser.engine import EngineMode, AuthStatus
from browser.factory import create_engine
from providers.registry import ProviderRegistry, create_default_registry

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("omnicouncil")


# ========== WebSocket Manager ==========

class ConnectionManager:
    """Manages WebSocket connections."""

    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info("WebSocket connected. Total: %d", len(self.active_connections))

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info("WebSocket disconnected. Total: %d", len(self.active_connections))

    async def broadcast(self, message: dict):
        """Send message to all connected clients."""
        dead = []
        for connection in self.active_connections[:]:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.warning("Failed to send to WebSocket: %s", e)
                dead.append(connection)
        for conn in dead:
            self.disconnect(conn)

    async def send_personal(self, websocket: WebSocket, message: dict):
        """Send message to a specific client."""
        try:
            await websocket.send_json(message)
        except Exception:
            pass


ws_manager = ConnectionManager()


# ========== Global State ==========

event_bus: EventBus | None = None
ai_manager: AIAccessManager | None = None
scheduler: SchedulerCenter | None = None
collector: ResultCollector | None = None
comparison_engine: ComparisonEngine | None = None
browser_engine = None
provider_registry: ProviderRegistry | None = None


# ========== Event Handlers (Engine → WebSocket) ==========

async def on_ai_completed(task_id: str, ai_id: str, response, **kwargs):
    """Handle AI completion event from engine."""
    await ws_manager.broadcast({
        "type": "ai_completed",
        "data": {
            "task_id": task_id,
            "ai_id": ai_id,
            "full_text": response.content,
            "word_count": response.word_count,
            "elapsed_ms": int(response.duration * 1000),
        }
    })


async def on_ai_failed(task_id: str, ai_id: str, error: str, **kwargs):
    """Handle AI failure event from engine."""
    await ws_manager.broadcast({
        "type": "ai_failed",
        "data": {"task_id": task_id, "ai_id": ai_id, "error": error}
    })


async def on_context_ready(context, **kwargs):
    """Handle RoundContext ready event."""
    await ws_manager.broadcast({
        "type": "all_completed",
        "data": {
            "task_id": context.task_id,
            "summary": {
                "total_ais": context.summary.total_ais,
                "success_count": context.summary.success_count,
                "failure_count": context.summary.failure_count,
            }
        }
    })

    # Trigger comparison analysis
    asyncio.create_task(run_comparison(context.task_id))


async def run_comparison(task_id: str):
    """Run comparison analysis and broadcast result."""
    global comparison_engine, collector

    if not comparison_engine or not collector:
        return

    ctx = collector.get_round_context(task_id)
    if not ctx:
        return

    try:
        comparison = await asyncio.to_thread(comparison_engine.analyze, ctx)
        await ws_manager.broadcast({
            "type": "comparison_ready",
            "data": {
                "task_id": task_id,
                "comparison_context": {
                    "task_id": comparison.task_id,
                    "query": comparison.query,
                    "degraded": comparison.degraded,
                    "semantic_units_count": len(comparison.semantic_units),
                    "differences": [
                        {
                            "id": d.id,
                            "dimension": d.dimension,
                            "strength": d.strength,
                            "type": d.diff_type,
                            "involved_ais": [{"ai_id": a, "stance": s} for a, s in d.involved_ais],
                        }
                        for d in comparison.differences
                    ],
                    "unique_insights": [
                        {
                            "unit_id": u.unit_id,
                            "ai_id": u.ai_id,
                            "content": u.content,
                            "novelty_score": u.novelty_score,
                        }
                        for u in comparison.unique_insights
                    ],
                    "metrics": {
                        "total_units": comparison.metrics.total_units,
                        "overall_divergence": comparison.metrics.overall_divergence,
                        "top_difference_dimension": comparison.metrics.top_difference_dimension,
                    }
                }
            }
        })
    except Exception as e:
        logger.exception("Comparison analysis failed for task %s", task_id)
        await ws_manager.broadcast({
            "type": "error",
            "data": {"task_id": task_id, "error": f"对比分析失败: {str(e)}", "recoverable": True}
        })


async def on_progress(task_id: str, completed_count: int, total_count: int, **kwargs):
    """Handle progress event from collector."""
    await ws_manager.broadcast({
        "type": "progress",
        "data": {
            "task_id": task_id,
            "completed": completed_count,
            "total": total_count,
            "current_ai": kwargs.get("latest_ai_id", ""),
        }
    })


# ========== Global Exception Handler ==========

class GlobalExceptionHandler:
    """Catches unhandled exceptions and pushes them to frontend via WebSocket."""

    def __init__(self, ws: ConnectionManager):
        self.ws = ws

    def install(self):
        sys.excepthook = self._sync_hook

    def _sync_hook(self, exc_type, exc_value, exc_tb):
        error_info = self._format(exc_type, exc_value)
        # Log to file since we can't safely use async from sync context
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
            pass  # No loop available

    def _format(self, exc_type, exc_value) -> dict:
        error_map = {
            "ConnectionError": {"error": "网络连接失败", "recoverable": True, "suggestion": "请检查网络连接后重试", "code": "NETWORK_ERROR"},
            "TimeoutError": {"error": "请求超时", "recoverable": True, "suggestion": "AI 响应时间过长，请稍后重试", "code": "TIMEOUT"},
            "TargetClosedError": {"error": "浏览器连接断开", "recoverable": True, "suggestion": "正在自动重连...", "code": "BROWSER_CLOSED"},
            "AuthenticationError": {"error": "登录已过期", "recoverable": False, "suggestion": "请重新登录 AI 账号", "code": "AUTH_EXPIRED"},
        }
        exc_name = exc_type.__name__ if exc_type else "Unknown"
        return error_map.get(exc_name, {"error": str(exc_value), "recoverable": False, "suggestion": "请重启应用", "code": "UNKNOWN"})


# ========== App Lifecycle ==========

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global event_bus, ai_manager, scheduler, collector, comparison_engine, browser_engine, provider_registry

    logger.info("Starting OmniCouncil backend...")

    # Initialize EventBus
    event_bus = EventBus()

    # Initialize config
    config = load_config()

    # Initialize Provider Registry (auto-discovers providers)
    provider_registry = create_default_registry()
    logger.info("Providers: %s", [p.config().provider_id for p in provider_registry.get_all()])

    # Initialize Browser Engine
    browser_mode = "embedded"
    browser_engine = create_engine(browser_mode, headless=True)
    connected = await browser_engine.connect()
    logger.info("Browser engine: %s (connected=%s)", browser_mode, connected)

    # Initialize Layer 1: AI Access with BrowserEngine
    ai_manager = AIAccessManager(event_bus=event_bus)
    deepseek = DeepSeekBrowserAdapter(browser_engine)
    qianwen = QianwenBrowserAdapter(browser_engine)
    ai_manager.register_adapter(deepseek)
    ai_manager.register_adapter(qianwen)
    await ai_manager.initialize()

    # Initialize Layer 2: Scheduler
    scheduler = SchedulerCenter(
        ai_manager=ai_manager,
        event_bus=event_bus,
        max_concurrent=config.scheduler.max_concurrent_tasks,
        ai_min_interval_ms=config.scheduler.ai_min_interval_ms,
    )

    # Initialize Layer 3: Collector
    collector = ResultCollector(event_bus=event_bus)

    # Initialize Layer 4: Comparison
    comparison_engine = ComparisonEngine(config=config.comparison, event_bus=event_bus)

    # Register event handlers (Engine → WebSocket)
    event_bus.on("ai:task:completed", on_ai_completed)
    event_bus.on("ai:task:failed", on_ai_failed)
    event_bus.on("collector:context:ready", on_context_ready)
    event_bus.on("collector:progress", on_progress)

    # Register auto-save handler for session history
    async def _on_context_ready(context, **kwargs):
        asyncio.create_task(on_all_completed(context.task_id))
    event_bus.on("collector:context:ready", _on_context_ready)

    # Install global exception handler
    exception_handler = GlobalExceptionHandler(ws_manager)
    exception_handler.install()

    logger.info("OmniCouncil backend started. AIs: %s", [a.ai_id for a in ai_manager.get_ready_ais()])

    yield

    # Cleanup
    logger.info("Shutting down OmniCouncil backend...")
    if browser_engine:
        await browser_engine.disconnect()
    if ai_manager:
        await ai_manager.destroy()
    EventBus.reset()


app = FastAPI(title="OmniCouncil", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["tauri://localhost", "http://localhost:8765", "http://127.0.0.1:8765"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ========== Health Endpoint ==========

@app.get("/health")
async def health():
    ai_status = []
    if ai_manager:
        for s in ai_manager.get_ready_ais():
            ai_status.append({"ai_id": s.ai_id, "status": s.status.value})
    return {"status": "ok", "version": "0.1.0", "timestamp": time.time(), "ais": ai_status}


# ========== WebSocket Endpoint ==========

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)

    # Send initial status
    ai_status = []
    if ai_manager:
        for s in ai_manager.get_ready_ais():
            ai_status.append({"ai_id": s.ai_id, "ai_name": s.ai_name, "status": s.status.value})

    await ws_manager.send_personal(websocket, {
        "type": "engine_status",
        "data": {"connected": True, "ais": ai_status}
    })

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            # Debug: log every WS message to file (absolute path)
            if os.name == "nt":
                _debug_dir = os.path.join(os.environ.get("USERPROFILE", "C:\\Users\\green"), ".omnicouncil")
            else:
                _debug_dir = os.path.join(str(Path.home()), ".omnicouncil")
            os.makedirs(_debug_dir, exist_ok=True)
            with open(os.path.join(_debug_dir, "ws_messages.log"), "a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%H:%M:%S')}] type={msg_type} | data={data.get('data', {})}\n")

            if msg_type == "submit_query":
                payload = data.get("data", {})
                # Validate required fields
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
                await handle_submit_query(payload)
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
    except Exception as e:
        logger.exception("WebSocket error")
        ws_manager.disconnect(websocket)


# ========== Message Handlers ==========

async def handle_submit_query(data: dict):
    """Handle query submission from frontend."""
    global scheduler, collector

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

    logger.info("Task %s: submitting query to %s", task_id, ai_ids)

    # Store query info for collector
    if collector:
        collector.set_query(task_id, query, TaskMode.PARALLEL)

    # Notify frontend: task started
    await ws_manager.broadcast({
        "type": "progress",
        "data": {"task_id": task_id, "completed": 0, "total": len(ai_ids), "current_ai": ""}
    })

    # Create and submit query request
    try:
        request = QueryRequest(
            query=query,
            selected_ai_ids=ai_ids,
            mode=TaskMode(mode) if mode in ("parallel", "sequential") else TaskMode.PARALLEL,
        )
        handle = await scheduler.submit_query(request)

        await ws_manager.broadcast({
            "type": "task_created",
            "data": {"task_id": handle.task_id, "status": handle.status.value}
        })

    except Exception as e:
        logger.exception("Failed to submit query")
        await ws_manager.broadcast({
            "type": "error",
            "data": {"task_id": task_id, "error": str(e), "recoverable": True, "code": "SUBMIT_FAILED"}
        })


async def handle_cancel_task(data: dict):
    """Handle task cancellation."""
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
    ai_status = []
    if ai_manager:
        for s in ai_manager.get_ready_ais():
            ai_status.append({"ai_id": s.ai_id, "ai_name": s.ai_name, "status": s.status.value})

    await ws_manager.send_personal(websocket, {
        "type": "status",
        "data": {"connected": True, "ais": ai_status}
    })


async def handle_get_ais(websocket: WebSocket):
    """Get list of all registered providers."""
    if not provider_registry:
        await ws_manager.send_personal(websocket, {"type": "ai_list", "data": []})
        return

    ais = provider_registry.get_configs()
    await ws_manager.send_personal(websocket, {"type": "ai_list", "data": ais})


async def handle_check_sessions(websocket: WebSocket):
    """Check which AIs have saved login sessions."""
    if not browser_engine:
        await ws_manager.send_personal(websocket, {
            "type": "sessions_status",
            "data": {"sessions": {}}
        })
        return

    sessions = browser_engine.check_all_sessions()
    authenticated = browser_engine.get_authenticated_ais()

    await ws_manager.send_personal(websocket, {
        "type": "sessions_status",
        "data": {
            "sessions": sessions,
            "authenticated": authenticated,
        }
    })
    logger.info("Sessions check: authenticated=%s", authenticated)


async def handle_reauth(data: dict):
    """Handle re-authentication via the engine's login method."""
    ai_id = data.get("ai_id")
    if not ai_id:
        return

    logger.info("Reauth requested for %s", ai_id)

    # Get provider from registry
    provider = provider_registry.get(ai_id) if provider_registry else None
    if not provider:
        await ws_manager.broadcast({
            "type": "auth_status",
            "data": {"ai_id": ai_id, "status": "failed", "message": f"未知的 AI: {ai_id}"}
        })
        return

    cfg = provider.config()

    await ws_manager.broadcast({
        "type": "auth_status",
        "data": {"ai_id": ai_id, "status": "connecting", "message": f"正在打开 {cfg.display_name} 登录窗口..."}
    })

    if not browser_engine:
        await ws_manager.broadcast({
            "type": "auth_status",
            "data": {"ai_id": ai_id, "status": "failed", "message": "浏览器引擎未初始化"}
        })
        return

    # Run login in background
    asyncio.create_task(_do_login(ai_id, cfg.login_url))


async def _do_login(ai_id: str, login_url: str):
    """Run login in background and broadcast result."""
    import traceback
    debug_path = "C:\\Users\\green\\.omnicouncil\\login.log"
    os.makedirs(os.path.dirname(debug_path), exist_ok=True)

    def _debug(msg: str):
        logger.info(msg)
        try:
            with open(debug_path, "a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%H:%M:%S')}] [main] {msg}\n")
        except Exception:
            pass

    try:
        _debug(f"Starting login for {ai_id} at {login_url}")
        success, error_msg = await browser_engine.login(ai_id, login_url)
        _debug(f"Login result: success={success}, error={error_msg}")

        if success:
            await ws_manager.broadcast({
                "type": "auth_status",
                "data": {"ai_id": ai_id, "status": "authenticated", "message": "登录成功"}
            })
            _debug(f"Broadcasted authenticated for {ai_id}")
        else:
            await ws_manager.broadcast({
                "type": "auth_status",
                "data": {"ai_id": ai_id, "status": "failed", "message": f"登录失败: {error_msg}"}
            })
            _debug(f"Broadcasted failed for {ai_id}: {error_msg}")
    except Exception as e:
        tb = traceback.format_exc()
        _debug(f"LOGIN EXCEPTION for {ai_id}: {e}\n{tb}")
        await ws_manager.broadcast({
            "type": "auth_status",
            "data": {"ai_id": ai_id, "status": "failed", "message": f"登录异常: {str(e)}"}
        })

from storage.local import LocalStorage

storage = LocalStorage()


@app.get("/api/sessions/status")
async def get_sessions_status():
    """Check which AIs have saved login sessions."""
    if not browser_engine:
        return {"sessions": {}, "authenticated": []}

    sessions = browser_engine.check_all_sessions()
    authenticated = browser_engine.get_authenticated_ais()
    return {"sessions": sessions, "authenticated": authenticated}


@app.get("/api/sessions")
async def list_sessions(limit: int = 50):
    """List recent sessions."""
    return {"sessions": storage.list_sessions(limit=limit)}


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    """Get a specific session."""
    session = storage.load_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    return session


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    """Delete a session."""
    if storage.delete_session(session_id):
        return {"status": "deleted"}
    raise HTTPException(404, "Session not found")


@app.delete("/api/sessions")
async def clear_sessions():
    """Clear all sessions."""
    count = storage.clear_all()
    return {"status": "cleared", "count": count}


# Auto-save session when task completes
async def on_all_completed(task_id: str, **kwargs):
    """Save completed task to history."""
    if collector:
        ctx = collector.get_round_context(task_id)
        if ctx:
            session_data = {
                "task_id": ctx.task_id,
                "query": ctx.query,
                "ai_ids": [r.ai_id for r in ctx.results],
                "completed_at": time.time(),
                "summary": {
                    "total_ais": ctx.summary.total_ais,
                    "success_count": ctx.summary.success_count,
                    "failure_count": ctx.summary.failure_count,
                },
                "results": [
                    {
                        "ai_id": r.ai_id,
                        "content": r.raw_text[:500],  # Truncate for storage
                        "word_count": r.normalized.word_count,
                        "duration": r.duration,
                    }
                    for r in ctx.results
                ],
            }
            storage.save_session(session_data)


# ========== Entry Point ==========

if __name__ == "__main__":
    import uvicorn

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    logger.info("Starting on port %d", args.port)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")
```

---

# FILE: backend/browser/__init__.py

```
"""Browser engine abstraction layer."""
```

---

# FILE: backend/browser/engine.py

```
"""BrowserEngine — abstract base class for browser automation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable


class EngineMode(str, Enum):
    CDP = "cdp"
    EMBEDDED = "embedded"


class AuthStatus(str, Enum):
    AUTHENTICATED = "authenticated"
    EXPIRED = "expired"
    NOT_LOGGED_IN = "not_logged_in"
    CAPTCHA_REQUIRED = "captcha_required"
    UNKNOWN = "unknown"


@dataclass
class PageInfo:
    """Information about a browser page."""
    ai_id: str
    url: str
    title: str
    is_logged_in: bool
    auth_status: AuthStatus


@dataclass
class EngineStatus:
    """Status of the browser engine."""
    mode: EngineMode
    connected: bool
    browser_version: str
    active_pages: list[PageInfo]


class BrowserEngine(ABC):
    """Abstract browser engine interface.

    Implementations:
    - CDPEngine: Connects to local Chrome via CDP
    - EmbeddedEngine: Launches embedded Chromium
    """

    @property
    @abstractmethod
    def mode(self) -> EngineMode:
        """Engine mode identifier."""
        ...

    @abstractmethod
    async def connect(self) -> bool:
        """Connect to or launch the browser. Returns True on success."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect and cleanup."""
        ...

    @abstractmethod
    async def is_connected(self) -> bool:
        """Check if browser is connected."""
        ...

    @abstractmethod
    async def get_page(self, ai_id: str, url: str) -> Any:
        """Get or create a page for the given AI.

        Returns a Playwright Page object.
        """
        ...

    @abstractmethod
    async def close_page(self, ai_id: str) -> None:
        """Close a specific AI's page."""
        ...

    @abstractmethod
    async def check_auth(self, ai_id: str) -> AuthStatus:
        """Check if the user is logged in for the given AI."""
        ...

    @abstractmethod
    async def ensure_logged_in(self, ai_id: str, on_login_required: Callable | None = None) -> bool:
        """Ensure login is valid. If expired, trigger re-login flow.

        Returns True if logged in.
        """
        ...

    @abstractmethod
    async def get_status(self) -> EngineStatus:
        """Get current engine status."""
        ...

    @abstractmethod
    async def save_auth_state(self, ai_id: str) -> bool:
        """Save current auth state (cookies, localStorage) for persistence."""
        ...

    @abstractmethod
    async def load_auth_state(self, ai_id: str) -> bool:
        """Load saved auth state."""
        ...
```

---

# FILE: backend/browser/factory.py

```
"""Browser engine factory."""

from __future__ import annotations

import logging
from pathlib import Path

from .engine import BrowserEngine, EngineMode
from .cdp_engine import CDPEngine
from .embedded_engine import EmbeddedEngine

logger = logging.getLogger(__name__)


def create_engine(
    mode: EngineMode | str,
    auth_dir: str | None = None,
    cdp_url: str = "http://localhost:9222",
    headless: bool = True,
) -> BrowserEngine:
    """Create a browser engine based on the specified mode.

    Args:
        mode: Engine mode ('cdp' or 'embedded')
        auth_dir: Directory for storing auth state files
        cdp_url: CDP connection URL (for CDP mode)
        headless: Whether to run headless (for embedded mode)

    Returns:
        BrowserEngine instance
    """
    if isinstance(mode, str):
        mode = EngineMode(mode)

    auth_dir = auth_dir or str(Path.home() / ".omnicouncil" / "auth")

    if mode == EngineMode.CDP:
        logger.info("Creating CDP engine (url=%s)", cdp_url)
        return CDPEngine(cdp_url=cdp_url, auth_dir=auth_dir)
    else:
        logger.info("Creating embedded engine (headless=%s)", headless)
        return EmbeddedEngine(auth_dir=auth_dir, headless=headless)
```

---

# FILE: backend/browser/cdp_engine.py

```
"""CDPEngine — connects to local Chrome via Chrome DevTools Protocol."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable

from .engine import BrowserEngine, EngineMode, EngineStatus, AuthStatus, PageInfo

logger = logging.getLogger(__name__)


class CDPEngine(BrowserEngine):
    """Connects to a locally running Chrome instance via CDP.

    Chrome must be started with: chrome --remote-debugging-port=9222

    Benefits:
    - Zero login cost (reuses user's existing Chrome session)
    - Automatic Cloudflare bypass (real browser)
    - All cookies/extensions available
    """

    def __init__(self, cdp_url: str = "http://localhost:9222", auth_dir: str | None = None):
        self._cdp_url = cdp_url
        self._auth_dir = auth_dir or str(Path.home() / ".omnicouncil" / "auth")
        self._browser = None
        self._context = None
        self._pages: dict[str, Any] = {}  # ai_id -> page
        self._connected = False

    @property
    def mode(self) -> EngineMode:
        return EngineMode.CDP

    async def connect(self) -> bool:
        """Connect to local Chrome via CDP."""
        try:
            from patchright.async_api import async_playwright

            logger.info("CDP: Connecting to %s", self._cdp_url)
            pw = await async_playwright().start()
            self._browser = await pw.chromium.connect_over_cdp(self._cdp_url)
            self._connected = True

            # Get existing context or create new one
            contexts = self._browser.contexts
            if contexts:
                self._context = contexts[0]
            else:
                self._context = await self._browser.new_context()

            logger.info("CDP: Connected successfully. Contexts: %d", len(contexts))
            return True

        except Exception as e:
            logger.error("CDP: Connection failed: %s", e)
            self._connected = False
            return False

    async def disconnect(self) -> None:
        """Disconnect from Chrome (does NOT close Chrome)."""
        for ai_id in list(self._pages.keys()):
            await self.close_page(ai_id)

        if self._browser:
            try:
                # Don't close the browser - it's the user's Chrome
                pass
            except Exception:
                pass

        self._browser = None
        self._context = None
        self._connected = False
        logger.info("CDP: Disconnected")

    async def is_connected(self) -> bool:
        """Check if CDP connection is alive."""
        if not self._connected or not self._browser:
            return False
        try:
            # Try to access browser version
            _ = self._browser.version
            return True
        except Exception:
            self._connected = False
            return False

    async def get_page(self, ai_id: str, url: str) -> Any:
        """Get or create a page for the given AI."""
        if not self._connected:
            raise RuntimeError("Not connected to Chrome")

        # Return existing page if available
        if ai_id in self._pages:
            page = self._pages[ai_id]
            try:
                # Check if page is still alive
                _ = page.url
                return page
            except Exception:
                # Page was closed, remove it
                del self._pages[ai_id]

        # Create new page
        if not self._context:
            self._context = await self._browser.new_context()

        page = await self._context.new_page()

        # Navigate to AI website
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)
        except Exception as e:
            logger.warning("CDP: Failed to navigate to %s: %s", url, e)

        self._pages[ai_id] = page
        logger.info("CDP: Created page for %s at %s", ai_id, url)
        return page

    async def close_page(self, ai_id: str) -> None:
        """Close a specific AI's page."""
        if ai_id in self._pages:
            try:
                await self._pages[ai_id].close()
            except Exception:
                pass
            del self._pages[ai_id]
            logger.info("CDP: Closed page for %s", ai_id)

    async def check_auth(self, ai_id: str) -> AuthStatus:
        """Check if the user is logged in for the given AI."""
        if ai_id not in self._pages:
            return AuthStatus.UNKNOWN

        page = self._pages[ai_id]
        url = page.url

        # AI-specific auth checks
        if ai_id == "deepseek":
            if "/sign_in" in url:
                return AuthStatus.NOT_LOGGED_IN
            # Check for login elements
            try:
                body = await page.locator("body").inner_text(timeout=3000)
                if "登录" in body[:200] or "sign in" in body[:200].lower():
                    return AuthStatus.NOT_LOGGED_IN
            except Exception:
                pass

        elif ai_id == "qianwen":
            if "login" in url.lower():
                return AuthStatus.NOT_LOGGED_IN
            try:
                body = await page.locator("body").inner_text(timeout=3000)
                if "登录" in body[:200]:
                    return AuthStatus.NOT_LOGGED_IN
            except Exception:
                pass

        return AuthStatus.AUTHENTICATED

    async def ensure_logged_in(self, ai_id: str, on_login_required: Callable | None = None) -> bool:
        """Ensure login is valid."""
        status = await self.check_auth(ai_id)

        if status == AuthStatus.AUTHENTICATED:
            return True

        if status in (AuthStatus.NOT_LOGGED_IN, AuthStatus.EXPIRED):
            if on_login_required:
                on_login_required(ai_id, status)
            return False

        return True

    async def get_status(self) -> EngineStatus:
        """Get current engine status."""
        pages = []
        for ai_id, page in self._pages.items():
            try:
                auth = await self.check_auth(ai_id)
                pages.append(PageInfo(
                    ai_id=ai_id,
                    url=page.url,
                    title=await page.title(),
                    is_logged_in=auth == AuthStatus.AUTHENTICATED,
                    auth_status=auth,
                ))
            except Exception:
                pages.append(PageInfo(
                    ai_id=ai_id,
                    url="",
                    title="",
                    is_logged_in=False,
                    auth_status=AuthStatus.UNKNOWN,
                ))

        return EngineStatus(
            mode=EngineMode.CDP,
            connected=self._connected,
            browser_version=self._browser.version if self._browser else "unknown",
            active_pages=pages,
        )

    async def save_auth_state(self, ai_id: str) -> bool:
        """CDP mode doesn't need to save auth state - it uses Chrome's own cookies."""
        return True

    async def load_auth_state(self, ai_id: str) -> bool:
        """CDP mode doesn't need to load auth state - it uses Chrome's own cookies."""
        return True
```

---

# FILE: backend/browser/embedded_engine.py

```
"""EmbeddedEngine — per-AI persistent context browser engine."""

from __future__ import annotations

import asyncio
import logging
import os
import time
import traceback
from pathlib import Path
from typing import Any, Callable

from .engine import BrowserEngine, EngineMode, EngineStatus, AuthStatus, PageInfo

logger = logging.getLogger(__name__)

# Fixed debug log path (works regardless of Path.home() resolution)
DEBUG_LOG = "C:\\Users\\green\\.omnicouncil\\login.log"


def _debug(msg: str):
    """Write to both logger and fixed file path."""
    logger.info(msg)
    try:
        os.makedirs(os.path.dirname(DEBUG_LOG), exist_ok=True)
        with open(DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    except Exception:
        pass  # Never let logging crash the app


class EmbeddedEngine(BrowserEngine):
    """Browser engine with per-AI persistent contexts."""

    def __init__(self, auth_dir: str | None = None, headless: bool = True):
        self._auth_dir = auth_dir or "C:\\Users\\green\\.omnicouncil\\auth"
        self._headless = headless
        self._playwright = None
        self._contexts: dict[str, Any] = {}
        self._pages: dict[str, Any] = {}
        self._connected = False
        self._authenticated: set[str] = set()

    @property
    def mode(self) -> EngineMode:
        return EngineMode.EMBEDDED

    def _get_profile_dir(self, ai_id: str) -> str:
        return str(Path(self._auth_dir) / f"{ai_id}_profile")

    async def connect(self) -> bool:
        try:
            from patchright.async_api import async_playwright
            self._playwright = await async_playwright().start()
            self._connected = True
            _debug("Playwright connected")

            for ai_id in ["deepseek", "qianwen", "gemini", "chatgpt", "claude"]:
                if self._has_saved_cookies(ai_id):
                    self._authenticated.add(ai_id)
                    _debug(f"Found saved session for {ai_id}")

            return True
        except Exception as e:
            _debug(f"Failed to connect: {e}")
            self._connected = False
            return False

    async def disconnect(self) -> None:
        for ai_id in list(self._pages.keys()):
            await self.close_page(ai_id)
        for ctx in self._contexts.values():
            try:
                await ctx.close()
            except Exception:
                pass
        self._contexts.clear()
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None
        self._connected = False

    async def is_connected(self) -> bool:
        return self._connected and self._playwright is not None

    async def _get_context(self, ai_id: str) -> Any:
        if ai_id in self._contexts:
            return self._contexts[ai_id]
        profile_dir = self._get_profile_dir(ai_id)
        Path(profile_dir).mkdir(parents=True, exist_ok=True)
        ctx = await self._playwright.chromium.launch_persistent_context(
            profile_dir,
            headless=self._headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        self._contexts[ai_id] = ctx
        return ctx

    async def get_page(self, ai_id: str, url: str) -> Any:
        if not self._connected:
            raise RuntimeError("Browser not connected")
        if ai_id in self._pages:
            page = self._pages[ai_id]
            try:
                _ = page.url
                return page
            except Exception:
                del self._pages[ai_id]
        ctx = await self._get_context(ai_id)
        page = await ctx.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)
        except Exception as e:
            logger.warning("Failed to navigate to %s: %s", url, e)
        self._pages[ai_id] = page
        return page

    async def close_page(self, ai_id: str) -> None:
        if ai_id in self._pages:
            try:
                await self._pages[ai_id].close()
            except Exception:
                pass
            del self._pages[ai_id]

    async def check_auth(self, ai_id: str) -> AuthStatus:
        if ai_id not in self._pages:
            return AuthStatus.UNKNOWN
        page = self._pages[ai_id]
        try:
            url = page.url
            if ai_id == "deepseek" and "/sign_in" in url:
                return AuthStatus.NOT_LOGGED_IN
            if ai_id == "qianwen" and "login" in url.lower():
                return AuthStatus.NOT_LOGGED_IN
        except Exception:
            pass
        return AuthStatus.AUTHENTICATED

    async def login(self, ai_id: str, url: str) -> tuple[bool, str]:
        """Launch visible browser for manual login.

        Uses SAME profile as work engine. User closes browser → check cookies.
        """
        profile_dir = self._get_profile_dir(ai_id)
        Path(profile_dir).mkdir(parents=True, exist_ok=True)

        # Close existing context for this AI
        if ai_id in self._contexts:
            try:
                await self._contexts[ai_id].close()
            except Exception:
                pass
            del self._contexts[ai_id]
            self._pages.pop(ai_id, None)

        _debug(f"=== Login for {ai_id} at {url} ===")
        _debug(f"Profile: {profile_dir}")

        browser = None
        try:
            _debug("Launching visible browser...")
            browser = await self._playwright.chromium.launch_persistent_context(
                profile_dir,
                headless=False,
                no_viewport=True,  # Gemini: prevents small window
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
            _debug("Browser launched")

            page = browser.pages[0] if browser.pages else await browser.new_page()

            # Use page close event to detect user closing the window
            page_closed = asyncio.Event()
            def on_page_close(*args):
                _debug("Page close event fired")
                page_closed.set()
            page.on("close", on_page_close)

            _debug(f"Navigating to {url}...")
            await page.goto(url, wait_until="commit", timeout=45000)
            _debug("Navigation complete, checking if already logged in...")

            # Wait for page to stabilize
            await asyncio.sleep(3)

            # Check if already logged in (from previous session)
            already_logged_in = await self._quick_login_check(ai_id, page)
            if already_logged_in:
                _debug("Already logged in! Saving state...")
                auth_json = Path(self._auth_dir) / f"{ai_id}.json"
                try:
                    await browser.storage_state(path=str(auth_json))
                    _debug(f"Storage state saved to {auth_json}")
                except Exception as e:
                    _debug(f"Failed to save storage state: {e}")
                self._authenticated.add(ai_id)
                _debug(f"LOGIN SUCCESSFUL for {ai_id} (already logged in)")
                try:
                    await browser.close()
                except Exception:
                    pass
                return True, ""

            _debug("Not logged in, waiting for user to close browser...")

            # Wait for user to close browser (page close event or timeout)
            try:
                await asyncio.wait_for(page_closed.wait(), timeout=300)
                _debug("Page closed by user")
            except asyncio.TimeoutError:
                _debug("Login timeout (5 minutes)")
                return False, "登录超时（5分钟）"

            _debug("Browser closed, saving auth state...")

            # Gemini: explicitly save storage state (cookies + localStorage)
            auth_json = Path(self._auth_dir) / f"{ai_id}.json"
            try:
                await browser.storage_state(path=str(auth_json))
                _debug(f"Storage state saved to {auth_json}")
            except Exception as e:
                _debug(f"Failed to save storage state: {e}")

            # Wait for cookies to flush to disk
            await asyncio.sleep(2)

            # Check cookies
            has_cookies = self._has_saved_cookies(ai_id)
            _debug(f"Cookie check: {has_cookies}")

            if has_cookies:
                self._authenticated.add(ai_id)
                _debug(f"LOGIN SUCCESSFUL for {ai_id}")
                return True, ""

            # Retry
            _debug("Waiting 3 more seconds for cookies...")
            await asyncio.sleep(3)
            has_cookies = self._has_saved_cookies(ai_id)
            _debug(f"Cookie check (retry): {has_cookies}")

            if has_cookies:
                self._authenticated.add(ai_id)
                _debug(f"LOGIN SUCCESSFUL for {ai_id} (retry)")
                return True, ""

            _debug(f"LOGIN FAILED for {ai_id} - no cookies found")
            return False, "未检测到登录状态"

        except Exception as e:
            tb = traceback.format_exc()
            _debug(f"LOGIN ERROR: {e}")
            _debug(f"TRACEBACK:\n{tb}")
            return False, str(e)
        finally:
            if browser:
                try:
                    await browser.close()
                    _debug("Browser closed in finally")
                except Exception as e:
                    _debug(f"Error closing browser: {e}")

    def _has_saved_cookies(self, ai_id: str) -> bool:
        profile_dir = Path(self._get_profile_dir(ai_id))
        # Check both old and new Chromium cookie locations
        cookie_paths = [
            profile_dir / "Default" / "Cookies",
            profile_dir / "Default" / "Network" / "Cookies",
        ]
        for cookie_file in cookie_paths:
            if cookie_file.exists() and cookie_file.stat().st_size > 0:
                _debug(f"Cookie file found: {cookie_file}")
                return True
        _debug(f"No cookies found for {ai_id}")
        return False

    async def _quick_login_check(self, ai_id: str, page: Any) -> bool:
        """Quick check if user is already logged in (from previous session)."""
        try:
            url = page.url
            _debug(f"Quick login check for {ai_id}: {url}")

            if ai_id == "deepseek":
                # DeepSeek: if not on sign_in page, likely logged in
                if "/sign_in" not in url and "chat.deepseek.com" in url:
                    # Verify with textarea
                    textarea = page.locator("textarea")
                    if await textarea.count() > 0 and await textarea.first.is_visible(timeout=1000):
                        return True

            elif ai_id == "qianwen":
                # Qianwen: check for chat interface
                if "login" not in url.lower() and "sign" not in url.lower():
                    textarea = page.locator("textarea, [contenteditable='true']")
                    if await textarea.count() > 0 and await textarea.first.is_visible(timeout=1000):
                        return True

            return False
        except Exception as e:
            _debug(f"Quick login check error: {e}")
            return False

    def _is_on_ai_page(self, ai_id: str, url: str) -> bool:
        if ai_id == "deepseek":
            return "chat.deepseek.com" in url and "/sign_in" not in url
        elif ai_id == "qianwen":
            is_domain = "qianwen" in url or "tongyi.aliyun.com" in url
            is_landing = url in (
                "https://qianwen.aliyun.com/", "https://www.qianwen.com/",
                "https://tongyi.aliyun.com/", "https://tongyi.aliyun.com",
            )
            is_login = "login" in url.lower() or "sign" in url.lower()
            return is_domain and not is_landing and not is_login
        return False

    def is_authenticated(self, ai_id: str) -> bool:
        return ai_id in self._authenticated

    def get_authenticated_ais(self) -> list[str]:
        """Get list of AIs with saved sessions."""
        return list(self._authenticated)

    def check_all_sessions(self) -> dict[str, bool]:
        """Check which AIs have saved cookie sessions."""
        result = {}
        for ai_id in ["deepseek", "qianwen", "gemini", "chatgpt", "claude"]:
            result[ai_id] = self._has_saved_cookies(ai_id)
        return result

    async def get_status(self) -> EngineStatus:
        pages = []
        for ai_id, page in self._pages.items():
            try:
                auth = await self.check_auth(ai_id)
                pages.append(PageInfo(
                    ai_id=ai_id, url=page.url, title=await page.title(),
                    is_logged_in=auth == AuthStatus.AUTHENTICATED, auth_status=auth,
                ))
            except Exception:
                pages.append(PageInfo(
                    ai_id=ai_id, url="", title="",
                    is_logged_in=False, auth_status=AuthStatus.UNKNOWN,
                ))
        return EngineStatus(
            mode=EngineMode.EMBEDDED, connected=self._connected,
            browser_version="persistent", active_pages=pages,
        )

    async def save_auth_state(self, ai_id: str) -> bool:
        return True

    async def load_auth_state(self, ai_id: str) -> bool:
        return True

    async def ensure_logged_in(self, ai_id: str, on_login_required: Callable | None = None) -> bool:
        return self.is_authenticated(ai_id)
```

---

# FILE: backend/browser/manager/__init__.py

```
"""Browser lifecycle management."""
from .browser_manager import BrowserManager
```

---

# FILE: backend/browser/manager/browser_manager.py

```
"""Browser lifecycle manager."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class BrowserManager:
    """Manages browser lifecycle (launch, connect, disconnect)."""

    def __init__(self):
        self._playwright = None
        self._browser = None
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected and self._browser is not None

    async def launch(self, headless: bool = True) -> bool:
        """Launch a new browser instance."""
        try:
            from patchright.async_api import async_playwright
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
            self._connected = True
            logger.info("Browser launched (headless=%s)", headless)
            return True
        except Exception as e:
            logger.error("Failed to launch browser: %s", e)
            self._connected = False
            return False

    async def disconnect(self) -> None:
        """Close browser and cleanup."""
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None
        self._connected = False
        logger.info("Browser disconnected")

    @property
    def playwright(self):
        return self._playwright

    @property
    def browser(self):
        return self._browser
```

---

# FILE: backend/engine/session/__init__.py

```
"""Session management for AI providers."""
from .manager import SessionManager
from .storage import SessionStorage
```

---

# FILE: backend/engine/session/manager.py

```
"""Session manager — coordinates login state across providers."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from .storage import SessionStorage

logger = logging.getLogger(__name__)


class SessionManager:
    """Manages login sessions for all AI providers.

    Responsibilities:
    - Track which providers are authenticated
    - Coordinate login flows
    - Validate session health
    """

    def __init__(self, storage: SessionStorage | None = None):
        self._storage = storage or SessionStorage()
        self._authenticated: set[str] = set()
        self._last_check: dict[str, float] = {}

    @property
    def storage(self) -> SessionStorage:
        return self._storage

    def is_authenticated(self, provider_id: str) -> bool:
        return provider_id in self._authenticated

    def set_authenticated(self, provider_id: str, authenticated: bool = True) -> None:
        if authenticated:
            self._authenticated.add(provider_id)
            self._last_check[provider_id] = time.time()
        else:
            self._authenticated.discard(provider_id)

    def get_authenticated_providers(self) -> list[str]:
        return list(self._authenticated)

    def has_saved_session(self, provider_id: str) -> bool:
        return self._storage.has_session(provider_id)

    def get_profile_dir(self, provider_id: str) -> str:
        return self._storage.get_profile_dir(provider_id)
```

---

# FILE: backend/engine/session/storage.py

```
"""Session storage — manages login state persistence."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SessionStorage:
    """Manages session data persistence for AI providers.

    Stores login state, cookies, and profile information.
    """

    def __init__(self, base_dir: str | None = None):
        self._base_dir = Path(base_dir) if base_dir else Path.home() / ".omnicouncil"
        self._auth_dir = self._base_dir / "auth"
        self._auth_dir.mkdir(parents=True, exist_ok=True)

    def get_profile_dir(self, provider_id: str) -> str:
        """Get the persistent profile directory for a provider."""
        profile_dir = self._auth_dir / f"{provider_id}_profile"
        profile_dir.mkdir(parents=True, exist_ok=True)
        return str(profile_dir)

    def get_auth_path(self, provider_id: str) -> Path:
        """Get the auth state file path for a provider."""
        return self._auth_dir / f"{provider_id}.json"

    def has_session(self, provider_id: str) -> bool:
        """Check if a saved session exists for a provider."""
        profile_dir = self._auth_dir / f"{provider_id}_profile"
        return profile_dir.exists() and any(profile_dir.iterdir())

    def save_session(self, provider_id: str, data: dict[str, Any]) -> bool:
        """Save session data to file."""
        try:
            path = self.get_auth_path(provider_id)
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
            logger.info("Saved session for %s", provider_id)
            return True
        except Exception as e:
            logger.error("Failed to save session for %s: %s", provider_id, e)
            return False

    def load_session(self, provider_id: str) -> dict[str, Any] | None:
        """Load session data from file."""
        path = self.get_auth_path(provider_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except Exception as e:
            logger.error("Failed to load session for %s: %s", provider_id, e)
            return None

    def delete_session(self, provider_id: str) -> bool:
        """Delete session data for a provider."""
        import shutil
        profile_dir = self._auth_dir / f"{provider_id}_profile"
        auth_file = self.get_auth_path(provider_id)

        deleted = False
        if profile_dir.exists():
            shutil.rmtree(profile_dir)
            deleted = True
        if auth_file.exists():
            auth_file.unlink()
            deleted = True

        if deleted:
            logger.info("Deleted session for %s", provider_id)
        return deleted
```

---

# FILE: backend/providers/__init__.py

```
"""AI Providers — plugin system for multi-AI support.

Usage:
    from providers.registry import create_default_registry
    registry = create_default_registry()
    provider = registry.get("deepseek")
"""
from .registry import ProviderRegistry, create_default_registry
from .base import BaseProvider, ProviderConfig
```

---

# FILE: backend/providers/base/__init__.py

```
"""Base provider classes."""
from .provider import BaseProvider, ProviderConfig
```

---

# FILE: backend/providers/base/provider.py

```
"""Provider base class — unified interface for all AI providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProviderConfig:
    """Configuration for a single AI provider."""
    provider_id: str
    display_name: str
    login_url: str
    chat_url: str
    enabled: bool = True
    icon_color: str = "#6C5CE7"
    icon_emoji: str = "🤖"
    max_concurrent: int = 1
    timeout_ms: int = 120000
    extra: dict = field(default_factory=dict)


class BaseProvider(ABC):
    """Base class for all AI providers.

    Each AI (DeepSeek, Qianwen, Gemini, etc.) implements this class.
    Adding a new AI = create a new directory + implement this class.

    Lifecycle:
        1. config() — return provider configuration
        2. check_login(page) — detect login status
        3. send_message(page, message) — send and extract response
    """

    @abstractmethod
    def config(self) -> ProviderConfig:
        """Return this provider's configuration."""
        ...

    @abstractmethod
    async def check_login(self, page: Any) -> bool:
        """Check if the user is logged in on this page.

        Returns True if logged in, False otherwise.
        Called during login flow and session validation.
        """
        ...

    @abstractmethod
    async def send_message(self, page: Any, message: str) -> str:
        """Send a message and return the AI's response.

        Handles:
        1. Finding the input box
        2. Typing the message
        3. Sending (Enter or click button)
        4. Waiting for response completion
        5. Extracting response text
        """
        ...

    async def on_login_start(self, page: Any) -> None:
        """Hook: called before navigating to login page."""
        pass

    async def on_login_success(self, page: Any) -> None:
        """Hook: called after successful login."""
        pass

    async def on_session_expired(self, page: Any) -> bool:
        """Check if session has expired. Returns True if expired."""
        return False

    def get_input_selector(self) -> str:
        """CSS selector for the message input box."""
        return "textarea"

    def get_submit_selector(self) -> str | None:
        """CSS selector for send button. None = use Enter key."""
        return None
```

---

# FILE: backend/providers/registry/__init__.py

```
"""Provider registry."""
from .registry import ProviderRegistry, create_default_registry
```

---

# FILE: backend/providers/registry/registry.py

```
"""Provider registry with auto-discovery."""

from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Any

from ..base import BaseProvider, ProviderConfig

logger = logging.getLogger(__name__)


class ProviderRegistry:
    """Registry for AI providers.

    Auto-discovers providers from the providers/ directory.
    Each provider is a subdirectory with a provider.py containing a BaseProvider subclass.
    """

    def __init__(self):
        self._providers: dict[str, BaseProvider] = {}

    def register(self, provider: BaseProvider) -> None:
        cfg = provider.config()
        self._providers[cfg.provider_id] = provider
        logger.info("Registered provider: %s (%s)", cfg.provider_id, cfg.display_name)

    def unregister(self, provider_id: str) -> None:
        if provider_id in self._providers:
            del self._providers[provider_id]
            logger.info("Unregistered provider: %s", provider_id)

    def get(self, provider_id: str) -> BaseProvider | None:
        return self._providers.get(provider_id)

    def get_all(self) -> list[BaseProvider]:
        return list(self._providers.values())

    def get_enabled(self) -> list[BaseProvider]:
        return [p for p in self._providers.values() if p.config().enabled]

    def get_configs(self) -> list[dict[str, Any]]:
        return [
            {
                "provider_id": p.config().provider_id,
                "display_name": p.config().display_name,
                "enabled": p.config().enabled,
                "icon_color": p.config().icon_color,
                "icon_emoji": p.config().icon_emoji,
            }
            for p in self._providers.values()
        ]

    def toggle(self, provider_id: str, enabled: bool) -> bool:
        provider = self._providers.get(provider_id)
        if provider:
            provider.config().enabled = enabled
            return True
        return False


def auto_discover_providers() -> list[BaseProvider]:
    """Auto-discover provider classes from the providers/ directory."""
    providers = []
    providers_dir = Path(__file__).parent.parent

    for item in providers_dir.iterdir():
        if not item.is_dir() or item.name in ("__pycache__", "base", "registry"):
            continue
        provider_py = item / "provider.py"
        if not provider_py.exists():
            continue

        try:
            module = importlib.import_module(f".{item.name}.provider", "providers")
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, BaseProvider)
                    and attr is not BaseProvider
                ):
                    providers.append(attr())
                    logger.info("Discovered provider: %s", item.name)
        except Exception as e:
            logger.warning("Failed to load provider from %s: %s", item.name, e)

    return providers


def create_default_registry() -> ProviderRegistry:
    """Create a registry with all discovered providers."""
    registry = ProviderRegistry()
    for provider in auto_discover_providers():
        registry.register(provider)
    return registry
```

---

# FILE: backend/providers/chatgpt/__init__.py

```
"""ChatGPT provider."""
from .provider import ChatGPTProvider
```

---

# FILE: backend/providers/chatgpt/provider.py

```
"""ChatGPT provider implementation.

Note: ChatGPT has strong anti-bot detection. May require careful handling.
"""

from __future__ import annotations

import time
from typing import Any

from ..base import BaseProvider, ProviderConfig


class ChatGPTProvider(BaseProvider):

    def config(self) -> ProviderConfig:
        return ProviderConfig(
            provider_id="chatgpt",
            display_name="ChatGPT",
            login_url="https://chatgpt.com",
            chat_url="https://chatgpt.com",
            icon_color="#10A37F",
            icon_emoji="🤖",
        )

    async def check_login(self, page: Any) -> bool:
        url = page.url
        if "/auth/login" in url or "auth0.openai.com" in url:
            return False
        try:
            textarea = page.locator("#prompt-textarea, textarea")
            return await textarea.count() > 0 and await textarea.first.is_visible(timeout=2000)
        except Exception:
            return False

    async def send_message(self, page: Any, message: str) -> str:
        # Find input
        input_box = None
        for sel in ["#prompt-textarea", "textarea", "[contenteditable='true']"]:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=2000):
                    input_box = el
                    break
            except Exception:
                continue

        if not input_box:
            raise RuntimeError("Could not find input box for ChatGPT")

        await input_box.click()
        await page.wait_for_timeout(300)
        await input_box.fill(message)
        await page.wait_for_timeout(500)

        # Try send button first, then Enter
        send_btn = page.locator("button[data-testid='send-button']").first
        try:
            if await send_btn.is_visible(timeout=1000):
                await send_btn.click()
            else:
                await page.keyboard.press("Enter")
        except Exception:
            await page.keyboard.press("Enter")

        await page.wait_for_timeout(2000)

        # Wait for response
        last_response = ""
        idle_start = None
        deadline = time.time() + 120

        while time.time() < deadline:
            body = await page.locator("body").inner_text(timeout=3000)
            lines = [l.strip() for l in body.split("\n") if l.strip()]

            prompt_idx = None
            for i, line in enumerate(lines):
                if message in line:
                    prompt_idx = i
                    break

            if prompt_idx is not None:
                response_lines = []
                for j in range(prompt_idx + 1, len(lines)):
                    candidate = lines[j]
                    if len(candidate) < 2:
                        continue
                    if any(skip in candidate for skip in ["ChatGPT", "Regenerate", "Copy"]):
                        break
                    response_lines.append(candidate)
                response_text = "\n".join(response_lines) if response_lines else ""

                if response_text:
                    if response_text != last_response:
                        last_response = response_text
                        idle_start = time.time()
                    elif idle_start and (time.time() - idle_start) >= 5:
                        return response_text

            await page.wait_for_timeout(500)

        if last_response:
            return last_response
        raise TimeoutError("ChatGPT response timed out")
```

---

# FILE: backend/providers/claude/__init__.py

```
"""Claude provider."""
from .provider import ClaudeProvider
```

---

# FILE: backend/providers/claude/provider.py

```
"""Claude provider implementation."""

from __future__ import annotations

import time
from typing import Any

from ..base import BaseProvider, ProviderConfig


class ClaudeProvider(BaseProvider):

    def config(self) -> ProviderConfig:
        return ProviderConfig(
            provider_id="claude",
            display_name="Claude",
            login_url="https://claude.ai",
            chat_url="https://claude.ai/new",
            icon_color="#D97706",
            icon_emoji="🧠",
        )

    async def check_login(self, page: Any) -> bool:
        url = page.url
        if "login" in url.lower() or "auth" in url.lower():
            return False
        try:
            textarea = page.locator("[contenteditable='true'], textarea")
            return await textarea.count() > 0 and await textarea.first.is_visible(timeout=2000)
        except Exception:
            return False

    async def send_message(self, page: Any, message: str) -> str:
        input_box = None
        for sel in ["div[contenteditable='true']", "textarea"]:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=2000):
                    input_box = el
                    break
            except Exception:
                continue

        if not input_box:
            raise RuntimeError("Could not find input box for Claude")

        await input_box.click()
        await page.wait_for_timeout(300)
        await input_box.fill(message)
        await page.wait_for_timeout(500)
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(2000)

        last_response = ""
        idle_start = None
        deadline = time.time() + 120

        while time.time() < deadline:
            body = await page.locator("body").inner_text(timeout=3000)
            lines = [l.strip() for l in body.split("\n") if l.strip()]

            prompt_idx = None
            for i, line in enumerate(lines):
                if message in line:
                    prompt_idx = i
                    break

            if prompt_idx is not None:
                response_lines = []
                for j in range(prompt_idx + 1, len(lines)):
                    candidate = lines[j]
                    if len(candidate) < 2:
                        continue
                    if any(skip in candidate for skip in ["Claude", "Copy", "Retry"]):
                        break
                    response_lines.append(candidate)
                response_text = "\n".join(response_lines) if response_lines else ""

                if response_text:
                    if response_text != last_response:
                        last_response = response_text
                        idle_start = time.time()
                    elif idle_start and (time.time() - idle_start) >= 3:
                        return response_text

            await page.wait_for_timeout(500)

        if last_response:
            return last_response
        raise TimeoutError("Claude response timed out")
```

---

# FILE: backend/providers/deepseek/__init__.py

```
"""DeepSeek provider."""
from .provider import DeepSeekProvider
```

---

# FILE: backend/providers/deepseek/provider.py

```
"""DeepSeek provider implementation."""

from __future__ import annotations

import time
from typing import Any

from ..base import BaseProvider, ProviderConfig


class DeepSeekProvider(BaseProvider):

    def config(self) -> ProviderConfig:
        return ProviderConfig(
            provider_id="deepseek",
            display_name="DeepSeek",
            login_url="https://chat.deepseek.com",
            chat_url="https://chat.deepseek.com",
            icon_color="#4F8FFF",
            icon_emoji="🔮",
        )

    async def check_login(self, page: Any) -> bool:
        url = page.url
        if "/sign_in" in url:
            return False
        try:
            textarea = page.locator("textarea")
            return await textarea.count() > 0 and await textarea.first.is_visible(timeout=2000)
        except Exception:
            return False

    async def send_message(self, page: Any, message: str) -> str:
        input_box = page.locator("textarea").first
        await input_box.click()
        await page.wait_for_timeout(300)
        await input_box.fill(message)
        await page.wait_for_timeout(500)
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(2000)

        last_response = ""
        idle_start = None
        deadline = time.time() + 120
        ui_skip = {"DeepThink", "Search", "AI-generated, for reference only", "Instant", "New chat", "Today"}

        while time.time() < deadline:
            body = await page.locator("body").inner_text(timeout=3000)
            lines = [l.strip() for l in body.split("\n") if l.strip()]

            prompt_idx = None
            for i, line in enumerate(lines):
                if message in line:
                    prompt_idx = i
                    break

            if prompt_idx is not None:
                response_lines = []
                for j in range(prompt_idx + 1, len(lines)):
                    candidate = lines[j]
                    if candidate in ui_skip or candidate in ("DeepThink", "Search"):
                        break
                    response_lines.append(candidate)
                response_text = "\n".join(response_lines) if response_lines else ""

                if response_text:
                    if response_text != last_response:
                        last_response = response_text
                        idle_start = time.time()
                    elif idle_start and (time.time() - idle_start) >= 3:
                        return response_text

            await page.wait_for_timeout(500)

        if last_response:
            return last_response
        raise TimeoutError("DeepSeek response timed out")
```

---

# FILE: backend/providers/gemini/__init__.py

```
"""Gemini provider."""
from .provider import GeminiProvider
```

---

# FILE: backend/providers/gemini/provider.py

```
"""Gemini provider implementation.

Note: Gemini requires Google account login and may be region-restricted.
"""

from __future__ import annotations

import time
from typing import Any

from ..base import BaseProvider, ProviderConfig


class GeminiProvider(BaseProvider):

    def config(self) -> ProviderConfig:
        return ProviderConfig(
            provider_id="gemini",
            display_name="Gemini",
            login_url="https://gemini.google.com",
            chat_url="https://gemini.google.com/app",
            icon_color="#A78BFA",
            icon_emoji="💎",
        )

    async def check_login(self, page: Any) -> bool:
        url = page.url
        if "accounts.google.com" in url:
            return False
        try:
            textarea = page.locator("[contenteditable='true'], textarea")
            return await textarea.count() > 0 and await textarea.first.is_visible(timeout=2000)
        except Exception:
            return False

    async def send_message(self, page: Any, message: str) -> str:
        # Find input
        input_box = None
        for sel in ["div[contenteditable='true']", "textarea"]:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=2000):
                    input_box = el
                    break
            except Exception:
                continue

        if not input_box:
            raise RuntimeError("Could not find input box for Gemini")

        await input_box.click()
        await page.wait_for_timeout(300)
        await input_box.fill(message)
        await page.wait_for_timeout(500)
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(2000)

        # Wait for response
        last_response = ""
        idle_start = None
        deadline = time.time() + 120

        while time.time() < deadline:
            body = await page.locator("body").inner_text(timeout=3000)
            lines = [l.strip() for l in body.split("\n") if l.strip()]

            prompt_idx = None
            for i, line in enumerate(lines):
                if message in line:
                    prompt_idx = i
                    break

            if prompt_idx is not None:
                response_lines = []
                for j in range(prompt_idx + 1, len(lines)):
                    candidate = lines[j]
                    if len(candidate) < 2:
                        continue
                    if any(skip in candidate for skip in ["New chat", "Gemini", "Google"]):
                        break
                    response_lines.append(candidate)
                response_text = "\n".join(response_lines) if response_lines else ""

                if response_text:
                    if response_text != last_response:
                        last_response = response_text
                        idle_start = time.time()
                    elif idle_start and (time.time() - idle_start) >= 3:
                        return response_text

            await page.wait_for_timeout(500)

        if last_response:
            return last_response
        raise TimeoutError("Gemini response timed out")
```

---

# FILE: backend/providers/qianwen/__init__.py

```
"""Qianwen provider."""
from .provider import QianwenProvider
```

---

# FILE: backend/providers/qianwen/provider.py

```
"""Qianwen (千问) provider implementation."""

from __future__ import annotations

import time
from typing import Any

from ..base import BaseProvider, ProviderConfig


class QianwenProvider(BaseProvider):

    def config(self) -> ProviderConfig:
        return ProviderConfig(
            provider_id="qianwen",
            display_name="千问",
            login_url="https://tongyi.aliyun.com/qianwen",
            chat_url="https://tongyi.aliyun.com/qianwen",
            icon_color="#F59E0B",
            icon_emoji="🟠",
        )

    async def check_login(self, page: Any) -> bool:
        url = page.url
        if "login" in url.lower() or "sign" in url.lower():
            return False
        try:
            textarea = page.locator("textarea, [contenteditable='true']")
            if await textarea.count() > 0 and await textarea.first.is_visible(timeout=1000):
                return True
        except Exception:
            pass
        return "login" not in url and "sign" not in url and ("qianwen" in url or "tongyi" in url)

    async def send_message(self, page: Any, message: str) -> str:
        input_box = None
        for sel in ["textarea", "[contenteditable='true']", "[role='textbox']"]:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=2000):
                    input_box = el
                    break
            except Exception:
                continue

        if not input_box:
            raise RuntimeError("Could not find input box for Qianwen")

        await input_box.click()
        await page.wait_for_timeout(300)
        await input_box.fill(message)
        await page.wait_for_timeout(500)
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(2000)

        last_response = ""
        idle_start = None
        deadline = time.time() + 120

        while time.time() < deadline:
            body = await page.locator("body").inner_text(timeout=3000)
            body = body.replace("\xa0", " ")
            lines = [l.strip() for l in body.split("\n") if l.strip()]

            prompt_idx = None
            for i, line in enumerate(lines):
                if message in line:
                    prompt_idx = i
                    break

            if prompt_idx is not None:
                response_lines = []
                for j in range(prompt_idx + 1, len(lines)):
                    candidate = lines[j]
                    if len(candidate) < 2:
                        continue
                    response_lines.append(candidate)
                response_text = "\n".join(response_lines) if response_lines else ""

                if response_text:
                    if response_text != last_response:
                        last_response = response_text
                        idle_start = time.time()
                    elif idle_start and (time.time() - idle_start) >= 3:
                        return response_text

            await page.wait_for_timeout(500)

        if last_response:
            return last_response
        raise TimeoutError("Qianwen response timed out")
```

---

# FILE: backend/adapters/__init__.py

```
"""AI adapters — each AI implements its own login detection and interaction logic."""
```

---

# FILE: backend/adapters/base.py

```
"""Base class for AI adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AIConfig:
    """Configuration for a single AI."""
    ai_id: str
    display_name: str
    login_url: str
    chat_url: str
    enabled: bool = True
    icon_color: str = "#6C5CE7"
    extra: dict = field(default_factory=dict)


class AIAdapter(ABC):
    """Base class for AI adapters.

    Each AI (DeepSeek, Qianwen, Gemini, etc.) implements this class
    to provide its own login detection, input selectors, and response extraction.
    """

    @abstractmethod
    def config(self) -> AIConfig:
        """Return this AI's configuration."""
        ...

    @abstractmethod
    async def check_login(self, page: Any) -> bool:
        """Check if the user is logged in on this page.

        Returns True if logged in, False otherwise.
        This is called during the login flow to detect when login is complete.
        """
        ...

    @abstractmethod
    async def send_message(self, page: Any, message: str) -> str:
        """Send a message and return the AI's response.

        This is the core method that handles:
        1. Finding the input box
        2. Typing the message
        3. Sending (Enter or click button)
        4. Waiting for response
        5. Extracting response text
        """
        ...

    async def on_login_start(self, page: Any) -> None:
        """Hook called before navigating to login page (optional)."""
        pass

    async def on_login_success(self, page: Any) -> None:
        """Hook called after successful login (optional)."""
        pass

    async def on_session_expired(self, page: Any) -> bool:
        """Check if the session has expired. Returns True if expired."""
        return False

    def get_input_selector(self) -> str:
        """CSS selector for the message input box."""
        return "textarea"

    def get_submit_selector(self) -> str | None:
        """CSS selector for the send button. None = use Enter key."""
        return None

    def get_response_selector(self) -> str | None:
        """CSS selector for the AI's response content."""
        return None
```

---

# FILE: backend/adapters/registry.py

```
"""AI adapter registry — manages all registered AI adapters."""

from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Any

from .base import AIAdapter, AIConfig

logger = logging.getLogger(__name__)


class AIRegistry:
    """Registry for AI adapters.

    Supports:
    - Manual registration
    - Auto-discovery from adapters/ directory
    - Dynamic enable/disable
    - Get adapter by ID
    """

    def __init__(self):
        self._adapters: dict[str, AIAdapter] = {}

    def register(self, adapter: AIAdapter) -> None:
        """Register an AI adapter."""
        cfg = adapter.config()
        self._adapters[cfg.ai_id] = adapter
        logger.info("Registered AI adapter: %s (%s)", cfg.ai_id, cfg.display_name)

    def unregister(self, ai_id: str) -> None:
        """Remove an AI adapter."""
        if ai_id in self._adapters:
            del self._adapters[ai_id]
            logger.info("Unregistered AI adapter: %s", ai_id)

    def get(self, ai_id: str) -> AIAdapter | None:
        """Get an adapter by ID."""
        return self._adapters.get(ai_id)

    def get_all(self) -> list[AIAdapter]:
        """Get all registered adapters."""
        return list(self._adapters.values())

    def get_enabled(self) -> list[AIAdapter]:
        """Get only enabled adapters."""
        return [a for a in self._adapters.values() if a.config().enabled]

    def get_configs(self) -> list[dict[str, Any]]:
        """Get all adapter configs for frontend."""
        return [
            {
                "ai_id": a.config().ai_id,
                "display_name": a.config().display_name,
                "enabled": a.config().enabled,
                "icon_color": a.config().icon_color,
            }
            for a in self._adapters.values()
        ]

    def toggle(self, ai_id: str, enabled: bool) -> bool:
        """Enable/disable an AI adapter."""
        adapter = self._adapters.get(ai_id)
        if adapter:
            adapter.config().enabled = enabled
            return True
        return False


def auto_discover_adapters() -> list[AIAdapter]:
    """Auto-discover adapter classes from the adapters/ directory."""
    adapters = []
    adapter_dir = Path(__file__).parent

    for file in adapter_dir.glob("*.py"):
        if file.name in ("__init__.py", "base.py", "registry.py"):
            continue

        try:
            module = importlib.import_module(f".{file.stem}", "adapters")
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, AIAdapter)
                    and attr is not AIAdapter
                ):
                    adapters.append(attr())
        except Exception as e:
            logger.warning("Failed to load adapter from %s: %s", file.name, e)

    return adapters


def create_default_registry() -> AIRegistry:
    """Create a registry with all discovered adapters."""
    registry = AIRegistry()
    for adapter in auto_discover_adapters():
        registry.register(adapter)
    return registry
```

---

# FILE: backend/adapters/deepseek.py

```
"""DeepSeek adapter."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from .base import AIAdapter, AIConfig


class DeepSeekAdapter(AIAdapter):

    def config(self) -> AIConfig:
        return AIConfig(
            ai_id="deepseek",
            display_name="DeepSeek",
            login_url="https://chat.deepseek.com",
            chat_url="https://chat.deepseek.com",
            icon_color="#4F8FFF",
        )

    async def check_login(self, page: Any) -> bool:
        url = page.url
        if "/sign_in" in url:
            return False
        try:
            textarea = page.locator("textarea")
            return await textarea.count() > 0 and await textarea.first.is_visible(timeout=2000)
        except Exception:
            return False

    async def send_message(self, page: Any, message: str) -> str:
        # Find input
        input_box = page.locator("textarea").first
        await input_box.click()
        await page.wait_for_timeout(300)
        await input_box.fill(message)
        await page.wait_for_timeout(500)
        await page.keyboard.press("Enter")

        # Wait for response
        await page.wait_for_timeout(2000)

        # Extract response via body text parsing
        last_response = ""
        idle_start = None
        deadline = time.time() + 120
        ui_skip = {"DeepThink", "Search", "AI-generated, for reference only", "Instant", "New chat", "Today"}

        while time.time() < deadline:
            body = await page.locator("body").inner_text(timeout=3000)
            lines = [l.strip() for l in body.split("\n") if l.strip()]

            prompt_idx = None
            for i, line in enumerate(lines):
                if message in line:
                    prompt_idx = i
                    break

            if prompt_idx is not None:
                response_lines = []
                for j in range(prompt_idx + 1, len(lines)):
                    candidate = lines[j]
                    if candidate in ui_skip:
                        continue
                    if candidate in ("DeepThink", "Search"):
                        break
                    response_lines.append(candidate)
                response_text = "\n".join(response_lines) if response_lines else ""

                if response_text:
                    if response_text != last_response:
                        last_response = response_text
                        idle_start = time.time()
                    elif idle_start and (time.time() - idle_start) >= 3:
                        return response_text

            await page.wait_for_timeout(500)

        if last_response:
            return last_response
        raise TimeoutError("DeepSeek response timed out")

    def get_input_selector(self) -> str:
        return "textarea"
```

---

# FILE: backend/adapters/qianwen.py

```
"""Qianwen (千问) adapter."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from .base import AIAdapter, AIConfig


class QianwenAdapter(AIAdapter):

    def config(self) -> AIConfig:
        return AIConfig(
            ai_id="qianwen",
            display_name="千问",
            login_url="https://tongyi.aliyun.com/qianwen",
            chat_url="https://tongyi.aliyun.com/qianwen",
            icon_color="#F59E0B",
        )

    async def check_login(self, page: Any) -> bool:
        url = page.url
        if "login" in url.lower() or "sign" in url.lower():
            return False
        try:
            textarea = page.locator("textarea, [contenteditable='true']")
            if await textarea.count() > 0 and await textarea.first.is_visible(timeout=1000):
                return True
        except Exception:
            pass
        # Fallback: check URL
        if "login" not in url and "sign" not in url:
            if "qianwen" in url or "tongyi" in url:
                return True
        return False

    async def send_message(self, page: Any, message: str) -> str:
        # Find input
        input_box = None
        for sel in ["textarea", "[contenteditable='true']", "[role='textbox']"]:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=2000):
                    input_box = el
                    break
            except Exception:
                continue

        if not input_box:
            raise RuntimeError("Could not find input box for Qianwen")

        await input_box.click()
        await page.wait_for_timeout(300)
        await input_box.fill(message)
        await page.wait_for_timeout(500)
        await page.keyboard.press("Enter")

        # Wait for response
        await page.wait_for_timeout(2000)

        # Extract response via body text parsing
        last_response = ""
        idle_start = None
        deadline = time.time() + 120

        while time.time() < deadline:
            body = await page.locator("body").inner_text(timeout=3000)
            body = body.replace("\xa0", " ")  # Non-breaking space
            lines = [l.strip() for l in body.split("\n") if l.strip()]

            prompt_idx = None
            for i, line in enumerate(lines):
                if message in line:
                    prompt_idx = i
                    break

            if prompt_idx is not None:
                response_lines = []
                for j in range(prompt_idx + 1, len(lines)):
                    candidate = lines[j]
                    if len(candidate) < 2:
                        continue
                    response_lines.append(candidate)
                response_text = "\n".join(response_lines) if response_lines else ""

                if response_text:
                    if response_text != last_response:
                        last_response = response_text
                        idle_start = time.time()
                    elif idle_start and (time.time() - idle_start) >= 3:
                        return response_text

            await page.wait_for_timeout(500)

        if last_response:
            return last_response
        raise TimeoutError("Qianwen response timed out")

    def get_input_selector(self) -> str:
        return "textarea, [contenteditable='true']"
```

---

# FILE: backend/engine/layers/__init__.py

```
"""OmniCouncil 17-layer architecture."""
```

---

# FILE: backend/engine/layers/layer1_ai_access/__init__.py

```
"""Layer 1: AI Access Layer.

Provides unified AI interaction interface, hiding the differences
between individual AI websites. Uses Scrapling for browser automation
and anti-detection.
"""
```

---

# FILE: backend/engine/layers/layer1_ai_access/adapter.py

```
"""AIAdapter base class — interface for individual AI adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from shared.types import AIResponse, AIStatus, ProviderStatus, SubmitOptions


class AIAdapter(ABC):
    """Abstract base class for all AI adapters.

    Each AI (DeepSeek, Gemini, etc.) implements this interface.
    The adapter handles: navigation, input, sending, response detection, extraction.
    """

    @property
    @abstractmethod
    def ai_id(self) -> str:
        """Unique identifier for this AI (e.g., 'deepseek')."""
        ...

    @property
    @abstractmethod
    def ai_name(self) -> str:
        """Human-readable name (e.g., 'DeepSeek')."""
        ...

    @property
    @abstractmethod
    def url(self) -> str:
        """AI website URL."""
        ...

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the adapter (e.g., load config, prepare browser)."""
        ...

    @abstractmethod
    async def destroy(self) -> None:
        """Clean up resources (close browser sessions, etc.)."""
        ...

    @abstractmethod
    def get_status(self) -> ProviderStatus:
        """Get current provider status."""
        ...

    @abstractmethod
    async def send_prompt(self, prompt: str, options: SubmitOptions | None = None) -> AIResponse:
        """Send a prompt to the AI and wait for the full response.

        This is the core method. Implementations should:
        1. Navigate to the AI website (or reuse existing session)
        2. Input the prompt
        3. Send it
        4. Wait for the response to complete
        5. Extract and return the response
        """
        ...

    @abstractmethod
    async def stop_generation(self) -> None:
        """Stop ongoing generation (if possible)."""
        ...

    @abstractmethod
    async def new_conversation(self) -> None:
        """Start a new conversation (clear history)."""
        ...

    def is_ready(self) -> bool:
        """Check if this adapter is ready to accept requests."""
        status = self.get_status()
        return status.status == AIStatus.READY
```

---

# FILE: backend/engine/layers/layer1_ai_access/browser_adapter.py

```
"""Browser-based AI adapter — uses BrowserEngine for page automation."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from pathlib import Path
from typing import Any

from shared.types import AIResponse, AIStatus, ProviderStatus, SubmitOptions
from shared.errors import AILoginRequiredError
from .adapter import AIAdapter
from browser.engine import BrowserEngine, AuthStatus

logger = logging.getLogger(__name__)

CJK_PATTERN = r"[一-鿿぀-ゟ゠-ヿ]"


class BrowserAIAdapter(AIAdapter):
    """Base class for AI adapters that use BrowserEngine.

    Subclasses only need to provide:
    - ai_id, ai_name, url
    - _find_input(page) -> locator
    - _extract_response(page, prompt) -> str
    """

    def __init__(self, engine: BrowserEngine, config: dict):
        self._engine = engine
        self._config = config
        self._status = AIStatus.INITIALIZING
        self._consecutive_failures = 0

    @property
    def ai_id(self) -> str:
        return self._config.get("aiId", "unknown")

    @property
    def ai_name(self) -> str:
        return self._config.get("aiName", "Unknown")

    @property
    def url(self) -> str:
        return self._config.get("url", "")

    def get_status(self) -> ProviderStatus:
        return ProviderStatus(
            ai_id=self.ai_id,
            ai_name=self.ai_name,
            status=self._status,
            last_check_at=time.time(),
            consecutive_failures=self._consecutive_failures,
        )

    async def initialize(self) -> None:
        logger.info("Initializing %s adapter...", self.ai_name)
        self._status = AIStatus.READY
        logger.info("%s adapter ready", self.ai_name)

    async def destroy(self) -> None:
        await self._engine.close_page(self.ai_id)
        self._status = AIStatus.INITIALIZING

    async def send_prompt(self, prompt: str, options: SubmitOptions | None = None) -> AIResponse:
        timeout_ms = options.timeout_ms if options else 120000
        task_id = f"{self.ai_id}_{uuid.uuid4().hex[:8]}"
        start_time = time.time()
        self._status = AIStatus.BUSY

        try:
            result = await self._send_async(prompt, timeout_ms)
            duration = time.time() - start_time
            self._status = AIStatus.READY
            self._consecutive_failures = 0
            return AIResponse(
                success=True, ai_id=self.ai_id, task_id=task_id,
                content=result, model=self.ai_id,
                timestamp=time.time(), duration=duration,
                word_count=self._count_words(result),
            )
        except AILoginRequiredError:
            self._status = AIStatus.LOGIN_REQUIRED
            self._consecutive_failures += 1

            # Try to trigger login window
            try:
                logger.info("%s: triggering login window...", self.ai_name)
                login_success = await self._engine.ensure_logged_in(self.ai_id)
                if login_success:
                    # Retry the request after login
                    logger.info("%s: login successful, retrying...", self.ai_name)
                    self._status = AIStatus.BUSY
                    result = await self._send_async(prompt, timeout_ms)
                    duration = time.time() - start_time
                    self._status = AIStatus.READY
                    self._consecutive_failures = 0
                    return AIResponse(
                        success=True, ai_id=self.ai_id, task_id=task_id,
                        content=result, model=self.ai_id,
                        timestamp=time.time(), duration=duration,
                        word_count=self._count_words(result),
                    )
            except Exception as login_err:
                logger.error("%s: login failed: %s", self.ai_name, login_err)

            return AIResponse(
                success=False, ai_id=self.ai_id, task_id=task_id,
                content="", error_code="LOGIN_REQUIRED",
                error_message=f"{self.ai_name} 需要重新登录",
            )
        except Exception as e:
            self._consecutive_failures += 1
            self._status = AIStatus.READY
            logger.exception("%s send_prompt failed", self.ai_name)
            return AIResponse(
                success=False, ai_id=self.ai_id, task_id=task_id,
                content="", error_code=type(e).__name__, error_message=str(e),
            )

    async def _send_async(self, prompt: str, timeout_ms: int) -> str:
        """Send prompt using BrowserEngine."""
        # Get or create page
        page = await self._engine.get_page(self.ai_id, self.url)
        await page.wait_for_timeout(2000)

        # Check login
        auth = await self._engine.check_auth(self.ai_id)
        if auth in (AuthStatus.NOT_LOGGED_IN, AuthStatus.EXPIRED):
            raise AILoginRequiredError(self.ai_id)

        # Find input
        input_box = await self._find_input(page)
        if input_box is None:
            body = ""
            try:
                body = (await page.locator("body").inner_text(timeout=3000))[:200]
            except Exception:
                pass
            if "登录" in body or "login" in body.lower():
                raise AILoginRequiredError(self.ai_id)
            raise RuntimeError(f"Could not find input box. Body: {body[:100]}")

        # Type and send
        await input_box.click()
        await page.wait_for_timeout(300)
        await input_box.fill(prompt)
        await page.wait_for_timeout(500)
        await page.keyboard.press("Enter")

        # Wait for response
        after_send_wait = self._config.get("timing", {}).get("afterSendWaitMs", 1500)
        await page.wait_for_timeout(after_send_wait)

        # Extract response
        return await self._extract_response(page, prompt, timeout_ms)

    async def _find_input(self, page: Any) -> Any:
        """Find the input element. Override in subclasses for AI-specific selectors."""
        selectors = self._config.get("selectors", {}).get("inputBox", ["textarea"])
        for sel in selectors:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=2000):
                    return el
            except Exception:
                continue
        return None

    async def _extract_response(self, page: Any, prompt: str, timeout_ms: int) -> str:
        """Extract response using body text parsing. Override for AI-specific logic."""
        idle_ms = self._config.get("detection", {}).get("idleTimeoutMs", 3000)
        last_response = ""
        idle_start = None
        deadline = time.time() + timeout_ms / 1000

        while time.time() < deadline:
            body = await page.locator("body").inner_text(timeout=3000)
            body = body.replace("\xa0", " ")
            lines = [l.strip() for l in body.split("\n") if l.strip()]

            # Find the user's prompt
            prompt_idx = None
            for i, line in enumerate(lines):
                if prompt in line:
                    prompt_idx = i
                    break

            if prompt_idx is not None:
                response_lines = []
                for j in range(prompt_idx + 1, len(lines)):
                    candidate = lines[j]
                    if self._is_ui_element(candidate):
                        continue
                    response_lines.append(candidate)
                response_text = "\n".join(response_lines) if response_lines else ""

                if response_text:
                    if response_text != last_response:
                        last_response = response_text
                        idle_start = time.time()
                    elif idle_start and (time.time() - idle_start) * 1000 >= idle_ms:
                        return response_text

            await page.wait_for_timeout(500)

        if last_response:
            return last_response
        raise TimeoutError(f"{self.ai_name} response timed out")

    def _is_ui_element(self, text: str) -> bool:
        """Check if text is a UI element (not part of AI response). Override for AI-specific."""
        ui_elements = {"DeepThink", "Search", "AI-generated, for reference only", "Instant", "New chat", "Today"}
        return text in ui_elements or text.startswith("New chat") or text.startswith("Today")

    @staticmethod
    def _count_words(text: str) -> int:
        cjk = len(re.findall(CJK_PATTERN, text))
        non_cjk = len(re.sub(CJK_PATTERN, " ", text).split())
        return cjk + non_cjk

    async def stop_generation(self) -> None:
        pass

    async def new_conversation(self) -> None:
        await self._engine.close_page(self.ai_id)
```

---

# FILE: backend/engine/layers/layer1_ai_access/manager.py

```
"""AIAccessManager — unified entry point for Layer 1.

This is the ONLY interface that Layer 2 (Scheduler) calls.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from shared.event_bus import EventBus
from shared.types import (
    AIResponse,
    AIStatus,
    ProviderStatus,
    SubmitOptions,
)
from shared.errors import AIAdapterError, CircuitOpenError, RateLimitError

from .adapter import AIAdapter
from .managers.provider_manager import ProviderManager
from .managers.rate_limiter import RateLimiter
from .managers.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)


class AIAccessManager:
    """Unified AI access interface.

    Provides: send_to_ai, send_to_multiple, get_ready_ais
    Layer 2 (Scheduler) depends ONLY on this class.
    """

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self._provider_manager = ProviderManager()
        self._rate_limiter = RateLimiter()
        self._circuit_breakers: dict[str, CircuitBreaker] = {}
        self._event_bus = event_bus or EventBus()

    def register_adapter(self, adapter: AIAdapter) -> None:
        """Register an AI adapter."""
        self._provider_manager.register(adapter)
        self._circuit_breakers[adapter.ai_id] = CircuitBreaker(
            ai_id=adapter.ai_id,
            on_state_change=lambda ai_id, old, new: logger.info(
                "Circuit breaker %s: %s -> %s", ai_id, old.value, new.value
            ),
        )
        logger.info("Registered adapter: %s (%s)", adapter.ai_id, adapter.ai_name)

    async def initialize(self, ai_ids: list[str] | None = None) -> None:
        """Initialize adapters for the specified AIs (or all if None)."""
        adapters = self._provider_manager.get_all()
        if ai_ids:
            adapters = [a for a in adapters if a.ai_id in ai_ids]

        for adapter in adapters:
            try:
                await adapter.initialize()
            except Exception:
                logger.exception("Failed to initialize adapter: %s", adapter.ai_id)

    async def destroy(self) -> None:
        """Destroy all adapters."""
        for adapter in self._provider_manager.get_all():
            try:
                await adapter.destroy()
            except Exception:
                logger.exception("Failed to destroy adapter: %s", adapter.ai_id)

    def get_ready_ais(self) -> list[ProviderStatus]:
        """Get status of all registered AIs."""
        return self._provider_manager.get_all_status()

    def get_provider_status(self, ai_id: str) -> ProviderStatus | None:
        """Get status of a specific AI."""
        return self._provider_manager.get_status(ai_id)

    async def send_to_ai(
        self, ai_id: str, prompt: str, options: SubmitOptions | None = None, task_id: str = ""
    ) -> AIResponse:
        """Send a prompt to a single AI.

        Checks: rate limit → circuit breaker → adapter.send_prompt.
        task_id: the scheduler's task_id for event correlation.
        """
        adapter = self._provider_manager.get(ai_id)
        if adapter is None:
            return AIResponse(
                success=False,
                ai_id=ai_id,
                task_id="",
                content="",
                error_code="ADAPTER_NOT_FOUND",
                error_message=f"No adapter registered for {ai_id}",
            )

        # Check circuit breaker
        cb = self._circuit_breakers.get(ai_id)
        if cb and not cb.should_allow():
            return AIResponse(
                success=False,
                ai_id=ai_id,
                task_id="",
                content="",
                error_code="CIRCUIT_OPEN",
                error_message=f"Circuit breaker is open for {ai_id}",
            )

        # Check rate limiter
        if not self._rate_limiter.allow(ai_id):
            return AIResponse(
                success=False,
                ai_id=ai_id,
                task_id="",
                content="",
                error_code="RATE_LIMITED",
                error_message=f"Rate limit exceeded for {ai_id}",
            )

        # Execute
        try:
            response = await adapter.send_prompt(prompt, options)
            event_task_id = task_id or response.task_id
            if response.success:
                if cb:
                    cb.record_success()
                self._rate_limiter.record(ai_id)
                await self._event_bus.emit(
                    "ai:task:completed",
                    task_id=event_task_id,
                    ai_id=ai_id,
                    response=response,
                )
            else:
                if cb:
                    cb.record_failure()
                await self._event_bus.emit(
                    "ai:task:failed",
                    task_id=event_task_id,
                    ai_id=ai_id,
                    error=response.error_message or "Unknown error",
                )
            return response
        except Exception as e:
            if cb:
                cb.record_failure()
            logger.exception("Error sending to %s", ai_id)
            return AIResponse(
                success=False,
                ai_id=ai_id,
                task_id="",
                content="",
                error_code="INTERNAL_ERROR",
                error_message=str(e),
            )

    async def send_to_multiple(
        self,
        ai_ids: list[str],
        prompt: str,
        options: SubmitOptions | None = None,
        task_id: str = "",
    ) -> dict[str, AIResponse]:
        """Send a prompt to multiple AIs in true parallel.

        Returns a dict of ai_id -> AIResponse.
        task_id: the scheduler's task_id for event correlation.
        """
        coros = [self.send_to_ai(ai_id, prompt, options, task_id=task_id) for ai_id in ai_ids]
        responses = await asyncio.gather(*coros, return_exceptions=True)

        results: dict[str, AIResponse] = {}
        for ai_id, response in zip(ai_ids, responses):
            if isinstance(response, Exception):
                logger.exception("Error in send_to_multiple for %s", ai_id)
                results[ai_id] = AIResponse(
                    success=False,
                    ai_id=ai_id,
                    task_id="",
                    content="",
                    error_code="INTERNAL_ERROR",
                    error_message=str(response),
                )
            else:
                results[ai_id] = response

        return results

    async def stop_generation(self, ai_id: str) -> None:
        """Stop generation for a specific AI."""
        adapter = self._provider_manager.get(ai_id)
        if adapter:
            await adapter.stop_generation()
```

---

# FILE: backend/engine/layers/layer1_ai_access/response_normalizer.py

```
"""ResponseNormalizer — parse raw AI text into structured NormalizedResponse.

This is used by Layer 3 (ResultCollector) to standardize AI responses.
"""

from __future__ import annotations

import re
from shared.types import NormalizedResponse


class ResponseNormalizer:
    """Normalize raw AI response text into structured format.

    Handles: Markdown parsing, paragraph extraction, code block detection,
    word count, language detection.
    """

    # Code block pattern: ```language\n...\n```
    _CODE_BLOCK_RE = re.compile(r"```(\w*)\n(.*?)```", re.DOTALL)
    # Table detection: lines starting with |
    _TABLE_RE = re.compile(r"^\|.+\|$", re.MULTILINE)
    # CJK character range for language detection
    _CJK_RE = re.compile(r"[一-鿿぀-ゟ゠-ヿ]")

    def normalize(self, raw_text: str) -> NormalizedResponse:
        """Normalize raw AI response text."""
        if not raw_text or not raw_text.strip():
            return NormalizedResponse(main_text="")

        # Extract code blocks
        code_blocks: list[tuple[str, str]] = []
        for match in self._CODE_BLOCK_RE.finditer(raw_text):
            lang = match.group(1) or "text"
            code = match.group(2).strip()
            code_blocks.append((lang, code))

        # Remove code blocks from text for paragraph extraction
        text_without_code = self._CODE_BLOCK_RE.sub("", raw_text).strip()

        # Extract paragraphs
        paragraphs = self._extract_paragraphs(text_without_code)

        # Detect language
        detected_language = self._detect_language(raw_text)

        # Check for Markdown features
        has_markdown = self._has_markdown(raw_text)

        # Word count
        word_count = self._count_words(raw_text)

        return NormalizedResponse(
            main_text=raw_text.strip(),
            code_blocks=code_blocks,
            paragraphs=paragraphs,
            word_count=word_count,
            detected_language=detected_language,
            has_markdown=has_markdown,
        )

    def _extract_paragraphs(self, text: str) -> list[str]:
        """Split text into paragraphs."""
        # Split by double newline, filter empty
        raw_paragraphs = re.split(r"\n\s*\n", text)
        paragraphs = []
        for p in raw_paragraphs:
            cleaned = p.strip()
            if cleaned and len(cleaned) >= 10:  # min paragraph length
                # Normalize whitespace
                cleaned = re.sub(r"\s+", " ", cleaned)
                paragraphs.append(cleaned)
        return paragraphs

    def _detect_language(self, text: str) -> str:
        """Detect primary language (simple heuristic)."""
        cjk_count = len(self._CJK_RE.findall(text))
        total_chars = len(text.strip())
        if total_chars == 0:
            return "unknown"
        ratio = cjk_count / total_chars
        if ratio > 0.3:
            return "zh"
        return "en"

    def _has_markdown(self, text: str) -> bool:
        """Check if text contains Markdown features."""
        markdown_indicators = [
            re.compile(r"^#{1,6}\s", re.MULTILINE),      # Headers
            re.compile(r"\*\*.*?\*\*"),                     # Bold
            re.compile(r"^\s*[-*+]\s", re.MULTILINE),     # Lists
            re.compile(r"^\s*\d+\.\s", re.MULTILINE),     # Numbered lists
            re.compile(r"```"),                             # Code blocks
            re.compile(r"\[.*?\]\(.*?\)"),                  # Links
        ]
        return any(pattern.search(text) for pattern in markdown_indicators)

    def _count_words(self, text: str) -> int:
        """Count words (handles CJK characters as individual words)."""
        # Count CJK characters individually
        cjk_chars = len(self._CJK_RE.findall(text))
        # Count non-CJK words
        non_cjk = self._CJK_RE.sub(" ", text)
        non_cjk_words = len(non_cjk.split())
        return cjk_chars + non_cjk_words
```

---

# FILE: backend/engine/layers/layer1_ai_access/adapters/__init__.py

```
"""AI adapter implementations."""
```

---

# FILE: backend/engine/layers/layer1_ai_access/adapters/deepseek.py

```
"""DeepSeek adapter — Playwright async persistent browser."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from pathlib import Path

from shared.types import AIResponse, AIStatus, ProviderStatus, SubmitOptions
from shared.errors import AILoginRequiredError
from ..adapter import AIAdapter

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent.parent / "config" / "deepseek.json"

CJK_PATTERN = r"[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff]"


class DeepSeekAdapter(AIAdapter):
    def __init__(self, user_data_dir=None):
        self._config = self._load_config()
        self._user_data_dir = user_data_dir or str(Path(__file__).parent.parent.parent.parent / "data" / "deepseek_session")
        self._status = AIStatus.INITIALIZING
        self._consecutive_failures = 0
        self._browser = None
        self._context = None
        self._page = None

    @property
    def ai_id(self): return "deepseek"
    @property
    def ai_name(self): return "DeepSeek"
    @property
    def url(self): return self._config["url"]

    def _load_config(self):
        if not CONFIG_PATH.exists():
            return {"aiId":"deepseek","aiName":"DeepSeek","url":"https://chat.deepseek.com","selectors":{"inputBox":["textarea"],"sendButton":[]},"detection":{"idleTimeoutMs":3000,"responseMinLength":1},"timing":{"afterSendWaitMs":1500}}
        with open(CONFIG_PATH) as f: return json.load(f)

    def get_status(self):
        return ProviderStatus(ai_id=self.ai_id, ai_name=self.ai_name, status=self._status, last_check_at=time.time(), consecutive_failures=self._consecutive_failures)

    async def initialize(self):
        logger.info("Initializing DeepSeek adapter...")
        Path(self._user_data_dir).mkdir(parents=True, exist_ok=True)
        await self._prewarm_browser()
        self._status = AIStatus.READY
        logger.info("DeepSeek adapter ready")

    async def _prewarm_browser(self):
        try:
            from patchright.async_api import async_playwright
            logger.info("DeepSeek: launching persistent browser...")
            self._browser = await async_playwright().start()
            self._context = await self._browser.chromium.launch_persistent_context(self._user_data_dir, headless=True, args=["--disable-blink-features=AutomationControlled"])
            self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
            await self._page.goto(self._config["url"], wait_until="domcontentloaded", timeout=60000)
            logger.info("DeepSeek: browser ready at %s", self._page.url)
        except Exception as e:
            logger.warning("DeepSeek: browser pre-warm failed: %s", e)
            self._browser = None

    async def destroy(self):
        if self._context:
            try: await self._context.close()
            except: pass
        if self._browser:
            try: await self._browser.stop()
            except: pass
        self._browser = self._context = self._page = None
        self._status = AIStatus.INITIALIZING
        logger.info("DeepSeek adapter destroyed")

    async def send_prompt(self, prompt, options=None):
        timeout_ms = options.timeout_ms if options else 120000
        task_id = f"ds_{uuid.uuid4().hex[:8]}"
        start_time = time.time()
        self._status = AIStatus.BUSY
        try:
            result = await self._send_async(prompt, timeout_ms)
            duration = time.time() - start_time
            self._status = AIStatus.READY
            self._consecutive_failures = 0
            return AIResponse(success=True, ai_id=self.ai_id, task_id=task_id, content=result, model="deepseek", timestamp=time.time(), duration=duration, word_count=self._count_words(result))
        except AILoginRequiredError:
            self._status = AIStatus.LOGIN_REQUIRED
            self._consecutive_failures += 1
            return AIResponse(success=False, ai_id=self.ai_id, task_id=task_id, content="", error_code="LOGIN_REQUIRED", error_message="DeepSeek login required")
        except Exception as e:
            self._consecutive_failures += 1
            self._status = AIStatus.READY
            logger.exception("DeepSeek send_prompt failed")
            return AIResponse(success=False, ai_id=self.ai_id, task_id=task_id, content="", error_code=type(e).__name__, error_message=str(e))

    @staticmethod
    def _count_words(text):
        cjk = len(re.findall(CJK_PATTERN, text))
        non_cjk = len(re.sub(CJK_PATTERN, " ", text).split())
        return cjk + non_cjk

    async def _send_async(self, prompt, timeout_ms):
        page = self._page
        if page is None: raise RuntimeError("Browser not initialized")
        await page.goto(self._config["url"], wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)
        if "/sign_in" in page.url: raise AILoginRequiredError("deepseek")
        input_box = None
        for sel in self._config["selectors"]["inputBox"]:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=2000): input_box = el; break
            except: continue
        if input_box is None:
            body = (await page.locator("body").inner_text(timeout=3000))[:200]
            if "login" in body.lower(): raise AILoginRequiredError("deepseek")
            raise RuntimeError(f"No input box. Body: {body[:100]}")
        await input_box.click()
        await page.wait_for_timeout(300)
        await input_box.fill(prompt)
        await page.wait_for_timeout(500)
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(self._config["timing"].get("afterSendWaitMs", 1500))
        idle_ms = self._config["detection"].get("idleTimeoutMs", 3000)
        last_response = ""
        idle_start = None
        deadline = time.time() + timeout_ms / 1000
        ui_skip = {"DeepThink", "Search", "AI-generated, for reference only", "Instant", "New chat", "Today"}
        while time.time() < deadline:
            body = await page.locator("body").inner_text(timeout=3000)
            lines = [l.strip() for l in body.split("\n") if l.strip()]
            prompt_idx = None
            for i, line in enumerate(lines):
                if prompt in line: prompt_idx = i; break
            if prompt_idx is not None:
                response_lines = []
                for j in range(prompt_idx + 1, len(lines)):
                    c = lines[j]
                    if c in ui_skip: continue
                    if c in ("DeepThink", "Search"): break
                    response_lines.append(c)
                response_text = "\n".join(response_lines) if response_lines else ""
                if response_text:
                    if response_text != last_response:
                        last_response = response_text
                        idle_start = time.time()
                    elif idle_start and (time.time() - idle_start) * 1000 >= idle_ms:
                        return response_text
            await page.wait_for_timeout(500)
        if last_response: return last_response
        raise TimeoutError("DeepSeek response timed out")

    async def stop_generation(self): pass
    async def new_conversation(self):
        if self._page: await self._page.goto(self._config["url"], wait_until="domcontentloaded", timeout=30000)
```

---

# FILE: backend/engine/layers/layer1_ai_access/adapters/deepseek_browser.py

```
"""DeepSeek adapter — uses BrowserEngine for page automation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..browser_adapter import BrowserAIAdapter
from browser.engine import BrowserEngine

CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "deepseek.json"


class DeepSeekBrowserAdapter(BrowserAIAdapter):
    """DeepSeek adapter using BrowserEngine.

    Handles DeepSeek-specific:
    - Input detection (textarea)
    - Response extraction (body text parsing with DeepSeek UI elements)
    - Login detection (/sign_in redirect)
    """

    def __init__(self, engine: BrowserEngine):
        config = self._load_config()
        super().__init__(engine, config)

    @staticmethod
    def _load_config() -> dict:
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH) as f:
                return json.load(f)
        return {
            "aiId": "deepseek",
            "aiName": "DeepSeek",
            "url": "https://chat.deepseek.com",
            "selectors": {
                "inputBox": ["textarea"],
                "sendButton": [],
            },
            "detection": {"idleTimeoutMs": 3000, "responseMinLength": 1},
            "timing": {"afterSendWaitMs": 1500},
        }

    async def _find_input(self, page: Any) -> Any:
        """DeepSeek uses textarea for input."""
        selectors = ["textarea", "div[contenteditable='true']"]
        for sel in selectors:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=2000):
                    return el
            except Exception:
                continue
        return None

    def _is_ui_element(self, text: str) -> bool:
        """DeepSeek-specific UI elements to skip."""
        ui_elements = {
            "DeepThink", "Search", "AI-generated, for reference only",
            "Instant", "New chat", "Today", "深度思考", "联网搜索",
        }
        if text in ui_elements:
            return True
        if text.startswith("New chat") or text.startswith("Today"):
            return True
        # Skip sidebar items
        if len(text) < 3:
            return True
        return False
```

---

# FILE: backend/engine/layers/layer1_ai_access/adapters/gemini.py

```
"""Gemini adapter — Scrapling-based browser automation."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from pathlib import Path

from shared.types import AIResponse, AIStatus, ProviderStatus, SubmitOptions
from shared.errors import AILoginRequiredError
from ..adapter import AIAdapter

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent.parent / "config" / "gemini.json"


class GeminiAdapter(AIAdapter):
    """Gemini adapter using Scrapling StealthyFetcher."""

    def __init__(self, user_data_dir: str | None = None) -> None:
        self._config = self._load_config()
        self._user_data_dir = user_data_dir or str(
            Path(__file__).parent.parent.parent.parent / "data" / "gemini_session"
        )
        self._status = AIStatus.INITIALIZING
        self._consecutive_failures = 0

    @property
    def ai_id(self) -> str:
        return "gemini"

    @property
    def ai_name(self) -> str:
        return "Gemini"

    @property
    def url(self) -> str:
        return self._config["url"]

    def _load_config(self) -> dict:
        if not CONFIG_PATH.exists():
            logger.warning("Gemini config not found at %s, using defaults", CONFIG_PATH)
            return {
                "aiId": "gemini", "aiName": "Gemini", "url": "https://gemini.google.com/app",
                "selectors": {"inputBox": ["div[contenteditable='true']", "textarea"], "sendButton": [], "responseContainer": [], "responseContent": []},
                "detection": {"idleTimeoutMs": 3000, "responseMinLength": 1},
                "timing": {"afterSendWaitMs": 2000},
            }
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)

    def get_status(self) -> ProviderStatus:
        return ProviderStatus(ai_id=self.ai_id, ai_name=self.ai_name, status=self._status,
                              last_check_at=time.time(), consecutive_failures=self._consecutive_failures)

    async def initialize(self) -> None:
        logger.info("Initializing Gemini adapter...")
        Path(self._user_data_dir).mkdir(parents=True, exist_ok=True)
        self._status = AIStatus.READY
        logger.info("Gemini adapter ready (session: %s)", self._user_data_dir)

    async def destroy(self) -> None:
        self._status = AIStatus.INITIALIZING

    async def send_prompt(self, prompt: str, options: SubmitOptions | None = None) -> AIResponse:
        timeout_ms = options.timeout_ms if options else 120000
        task_id = f"gem_{uuid.uuid4().hex[:8]}"
        start_time = time.time()

        self._status = AIStatus.BUSY

        try:
            result = await asyncio.to_thread(self._fetch_with_scrapling, prompt, timeout_ms)
            duration = time.time() - start_time
            self._status = AIStatus.READY
            self._consecutive_failures = 0

            return AIResponse(success=True, ai_id=self.ai_id, task_id=task_id, content=result,
                              model="gemini", timestamp=time.time(), duration=duration,
                              word_count=self._count_words(result))

        except AILoginRequiredError:
            self._status = AIStatus.LOGIN_REQUIRED
            self._consecutive_failures += 1
            return AIResponse(success=False, ai_id=self.ai_id, task_id=task_id, content="",
                              error_code="LOGIN_REQUIRED", error_message="Gemini login required. Run: python scripts/login_gemini.py")
        except Exception as e:
            self._consecutive_failures += 1
            self._status = AIStatus.READY
            logger.exception("Gemini send_prompt failed")
            return AIResponse(success=False, ai_id=self.ai_id, task_id=task_id, content="",
                              error_code=type(e).__name__, error_message=str(e))

    @staticmethod
    def _count_words(text: str) -> int:
        import re
        cjk = len(re.findall(r"[一-鿿぀-ゟ゠-ヿ]", text))
        non_cjk = len(re.sub(r"[一-鿿぀-ゟ゠-ヿ]", " ", text).split())
        return cjk + non_cjk

    def _find_element(self, page, selectors: list[str], timeout: int = 5000):
        for selector in selectors:
            try:
                page.wait_for_selector(selector, timeout=min(timeout, 2000))
                el = page.locator(selector).first
                if el.is_visible():
                    return el
            except Exception:
                continue
        return None

    def _fetch_with_scrapling(self, prompt: str, timeout_ms: int) -> str:
        from scrapling.fetchers import StealthyFetcher

        config = self._config
        selectors = config["selectors"]
        timing = config["timing"]
        detection = config["detection"]
        captured: dict[str, str | Exception] = {}

        def page_action(page):
            page.wait_for_timeout(5000)

            # Check login
            current_url = page.url
            if "accounts.google.com" in current_url or "signin" in current_url.lower():
                raise AILoginRequiredError("gemini")

            # Find input
            input_box = self._find_element(page, selectors["inputBox"], timeout=10000)
            if input_box is None:
                body_text = ""
                try:
                    body_text = page.locator("body").inner_text(timeout=3000)[:200]
                except Exception:
                    pass
                if "sign in" in body_text.lower() or "login" in body_text.lower():
                    raise AILoginRequiredError("gemini")
                raise RuntimeError(f"Could not find input box. Page text: {body_text[:100]}")

            # Input prompt
            try:
                input_box.click()
                page.wait_for_timeout(300)
                input_box.fill(prompt)
            except Exception:
                try:
                    input_box.click()
                    page.wait_for_timeout(300)
                    input_box.type(prompt, delay=30)
                except Exception as e:
                    raise RuntimeError(f"Failed to input text: {e}")

            page.wait_for_timeout(500)

            # Send
            sent = False
            try:
                page.keyboard.press("Enter")
                sent = True
            except Exception:
                pass

            if not sent:
                send_btn = self._find_element(page, selectors["sendButton"], timeout=2000)
                if send_btn:
                    try:
                        send_btn.click()
                        sent = True
                    except Exception:
                        pass

            if not sent:
                raise RuntimeError("Failed to send message")

            # Wait for response using body text parsing
            page.wait_for_timeout(timing.get("afterSendWaitMs", 2000))

            idle_ms = detection.get("idleTimeoutMs", 3000)
            last_response = ""
            idle_start = None
            deadline = time.time() + timeout_ms / 1000
            ui_skip = {"New chat", "Gemini", "Flash", "Sign in", "Google Terms", "Privacy Policy"}

            while time.time() < deadline:
                try:
                    body = page.locator("body").inner_text(timeout=3000)
                    lines = [l.strip() for l in body.split("\n") if l.strip()]

                    # Find the user's prompt
                    prompt_idx = None
                    for i, line in enumerate(lines):
                        if prompt in line:
                            prompt_idx = i
                            break

                    if prompt_idx is not None:
                        response_lines = []
                        for j in range(prompt_idx + 1, len(lines)):
                            candidate = lines[j]
                            if candidate in ui_skip:
                                continue
                            if any(skip in candidate for skip in ["Google Terms", "Privacy Policy", "EN-US"]):
                                break
                            response_lines.append(candidate)
                        response_text = "\n".join(response_lines) if response_lines else ""

                        if response_text:
                            if response_text != last_response:
                                last_response = response_text
                                idle_start = time.time()
                            elif idle_start and (time.time() - idle_start) * 1000 >= idle_ms:
                                captured["result"] = response_text
                                return
                except Exception:
                    pass

                page.wait_for_timeout(500)

            if last_response:
                captured["result"] = last_response
                return
            captured["error"] = TimeoutError("Gemini response timed out")

        try:
            from scrapling.fetchers import StealthySession
            with StealthySession(headless=True, user_data_dir=self._user_data_dir) as session:
                session.fetch(
                    config["url"], page_action=page_action,
                    network_idle=True, timeout=timeout_ms + 10000,
                )
        except AILoginRequiredError:
            raise
        except Exception as e:
            if "result" not in captured:
                raise

        if "error" in captured:
            raise captured["error"]
        if "result" in captured:
            return captured["result"]
        raise RuntimeError("No response captured from Gemini")

    async def stop_generation(self) -> None:
        logger.info("Gemini stop_generation called (not yet implemented)")

    async def new_conversation(self) -> None:
        logger.info("Gemini new_conversation called (not yet implemented)")
```

---

# FILE: backend/engine/layers/layer1_ai_access/adapters/qianwen.py

```
"""Qianwen adapter — Playwright async persistent browser."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from pathlib import Path

from shared.types import AIResponse, AIStatus, ProviderStatus, SubmitOptions
from shared.errors import AILoginRequiredError
from ..adapter import AIAdapter

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent.parent / "config" / "qianwen.json"

CJK_PATTERN = r"[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff]"


class QianwenAdapter(AIAdapter):
    def __init__(self, user_data_dir=None):
        self._config = self._load_config()
        self._user_data_dir = user_data_dir or str(Path(__file__).parent.parent.parent.parent / "data" / "qianwen_session")
        self._status = AIStatus.INITIALIZING
        self._consecutive_failures = 0
        self._browser = None
        self._context = None
        self._page = None

    @property
    def ai_id(self): return "qianwen"
    @property
    def ai_name(self): return "千问"
    @property
    def url(self): return self._config["url"]

    def _load_config(self):
        if not CONFIG_PATH.exists():
            return {"aiId":"qianwen","aiName":"千问","url":"https://tongyi.aliyun.com/qianwen","selectors":{"inputBox":["textarea","[contenteditable]","[role=textbox]"],"sendButton":[]},"detection":{"idleTimeoutMs":3000,"responseMinLength":1},"timing":{"afterSendWaitMs":2000}}
        with open(CONFIG_PATH) as f: return json.load(f)

    def get_status(self):
        return ProviderStatus(ai_id=self.ai_id, ai_name=self.ai_name, status=self._status, last_check_at=time.time(), consecutive_failures=self._consecutive_failures)

    async def initialize(self):
        logger.info("Initializing Qianwen adapter...")
        Path(self._user_data_dir).mkdir(parents=True, exist_ok=True)
        await self._prewarm_browser()
        self._status = AIStatus.READY
        logger.info("Qianwen adapter ready")

    async def _prewarm_browser(self):
        try:
            from patchright.async_api import async_playwright
            logger.info("Qianwen: launching persistent browser...")
            self._browser = await async_playwright().start()
            self._context = await self._browser.chromium.launch_persistent_context(self._user_data_dir, headless=True, args=["--disable-blink-features=AutomationControlled"])
            self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
            await self._page.goto(self._config["url"], wait_until="domcontentloaded", timeout=60000)
            logger.info("Qianwen: browser ready at %s", self._page.url)
        except Exception as e:
            logger.warning("Qianwen: browser pre-warm failed: %s", e)
            self._browser = None

    async def destroy(self):
        if self._context:
            try: await self._context.close()
            except: pass
        if self._browser:
            try: await self._browser.stop()
            except: pass
        self._browser = self._context = self._page = None
        self._status = AIStatus.INITIALIZING

    async def send_prompt(self, prompt, options=None):
        timeout_ms = options.timeout_ms if options else 120000
        task_id = f"qw_{uuid.uuid4().hex[:8]}"
        start_time = time.time()
        self._status = AIStatus.BUSY
        try:
            result = await self._send_async(prompt, timeout_ms)
            duration = time.time() - start_time
            self._status = AIStatus.READY
            self._consecutive_failures = 0
            return AIResponse(success=True, ai_id=self.ai_id, task_id=task_id, content=result, model="qianwen", timestamp=time.time(), duration=duration, word_count=self._count_words(result))
        except AILoginRequiredError:
            self._status = AIStatus.LOGIN_REQUIRED
            self._consecutive_failures += 1
            return AIResponse(success=False, ai_id=self.ai_id, task_id=task_id, content="", error_code="LOGIN_REQUIRED", error_message="千问需要登录")
        except Exception as e:
            self._consecutive_failures += 1
            self._status = AIStatus.READY
            logger.exception("Qianwen send_prompt failed")
            return AIResponse(success=False, ai_id=self.ai_id, task_id=task_id, content="", error_code=type(e).__name__, error_message=str(e))

    @staticmethod
    def _count_words(text):
        cjk = len(re.findall(CJK_PATTERN, text))
        non_cjk = len(re.sub(CJK_PATTERN, " ", text).split())
        return cjk + non_cjk

    async def _send_async(self, prompt, timeout_ms):
        page = self._page
        if page is None: raise RuntimeError("Browser not initialized")
        await page.goto(self._config["url"], wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)
        if "login" in page.url.lower(): raise AILoginRequiredError("qianwen")
        input_box = None
        for sel in self._config["selectors"]["inputBox"]:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=2000): input_box = el; break
            except: continue
        if input_box is None:
            body = (await page.locator("body").inner_text(timeout=3000))[:200]
            if "登录" in body: raise AILoginRequiredError("qianwen")
            raise RuntimeError(f"No input box. Body: {body[:100]}")
        await input_box.click()
        await page.wait_for_timeout(300)
        await input_box.fill(prompt)
        await page.wait_for_timeout(500)
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(self._config["timing"].get("afterSendWaitMs", 2000))
        idle_ms = self._config["detection"].get("idleTimeoutMs", 3000)
        last_response = ""
        idle_start = None
        deadline = time.time() + timeout_ms / 1000
        while time.time() < deadline:
            body = await page.locator("body").inner_text(timeout=3000)
            body = body.replace("\xa0", " ")
            lines = [l.strip() for l in body.split("\n") if l.strip()]
            prompt_idx = None
            for i, line in enumerate(lines):
                if prompt in line: prompt_idx = i; break
            if prompt_idx is not None:
                response_lines = []
                for j in range(prompt_idx + 1, len(lines)):
                    c = lines[j]
                    if len(c) < 2: continue
                    response_lines.append(c)
                response_text = "\n".join(response_lines) if response_lines else ""
                if response_text:
                    if response_text != last_response:
                        last_response = response_text
                        idle_start = time.time()
                    elif idle_start and (time.time() - idle_start) * 1000 >= idle_ms:
                        return response_text
            await page.wait_for_timeout(500)
        if last_response: return last_response
        raise TimeoutError("Qianwen response timed out")

    async def stop_generation(self): pass
    async def new_conversation(self):
        if self._page: await self._page.goto(self._config["url"], wait_until="domcontentloaded", timeout=30000)
```

---

# FILE: backend/engine/layers/layer1_ai_access/adapters/qianwen_browser.py

```
"""Qianwen (千问) adapter — uses BrowserEngine for page automation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..browser_adapter import BrowserAIAdapter
from browser.engine import BrowserEngine

CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "qianwen.json"


class QianwenBrowserAdapter(BrowserAIAdapter):
    """Qianwen adapter using BrowserEngine.

    Handles Qianwen-specific:
    - Input detection (contenteditable div)
    - Response extraction (body text parsing with non-breaking space handling)
    - Login detection
    """

    def __init__(self, engine: BrowserEngine):
        config = self._load_config()
        super().__init__(engine, config)

    @staticmethod
    def _load_config() -> dict:
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH) as f:
                return json.load(f)
        return {
            "aiId": "qianwen",
            "aiName": "千问",
            "url": "https://tongyi.aliyun.com/qianwen",
            "selectors": {
                "inputBox": ["textarea", "[contenteditable]", "[role=textbox]"],
                "sendButton": [],
            },
            "detection": {"idleTimeoutMs": 3000, "responseMinLength": 1},
            "timing": {"afterSendWaitMs": 2000},
        }

    async def _find_input(self, page: Any) -> Any:
        """Qianwen uses contenteditable div or textarea."""
        selectors = ["textarea", "[contenteditable='true']", "[role='textbox']"]
        for sel in selectors:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=2000):
                    return el
            except Exception:
                continue
        return None

    async def _extract_response(self, page: Any, prompt: str, timeout_ms: int) -> str:
        """Qianwen-specific response extraction with non-breaking space handling."""
        # Qianwen uses \xa0 (non-breaking space) in text
        idle_ms = self._config.get("detection", {}).get("idleTimeoutMs", 3000)
        last_response = ""
        idle_start = None
        deadline = time.time() + timeout_ms / 1000

        while time.time() < deadline:
            body = await page.locator("body").inner_text(timeout=3000)
            # Qianwen uses non-breaking spaces
            body = body.replace("\xa0", " ")
            lines = [l.strip() for l in body.split("\n") if l.strip()]

            # Find the user's prompt
            prompt_idx = None
            for i, line in enumerate(lines):
                if prompt in line:
                    prompt_idx = i
                    break

            if prompt_idx is not None:
                response_lines = []
                for j in range(prompt_idx + 1, len(lines)):
                    candidate = lines[j]
                    if self._is_ui_element(candidate):
                        continue
                    response_lines.append(candidate)
                response_text = "\n".join(response_lines) if response_lines else ""

                if response_text:
                    if response_text != last_response:
                        last_response = response_text
                        idle_start = time.time()
                    elif idle_start and (time.time() - idle_start) * 1000 >= idle_ms:
                        return response_text

            await page.wait_for_timeout(500)

        if last_response:
            return last_response
        raise TimeoutError("千问 response timed out")

    def _is_ui_element(self, text: str) -> bool:
        """Qianwen-specific UI elements to skip."""
        ui_elements = {
            "你好，我是千问", "向千问提问", "任务助理", "思考", "研究",
            "千问高考", "PPT创作", "更多", "内测", "AI生图", "代码",
            "翻译", "AI写作", "录音纪要", "HappyHorse",
        }
        if text in ui_elements:
            return True
        if len(text) < 2:
            return True
        return False
```

---

# FILE: backend/engine/layers/layer1_ai_access/managers/__init__.py

```
"""Layer 1 management modules."""
```

---

# FILE: backend/engine/layers/layer1_ai_access/managers/circuit_breaker.py

```
"""CircuitBreaker — CLOSED → OPEN → HALF_OPEN state machine."""

from __future__ import annotations

import time
from typing import Callable

from shared.types import CircuitState


class CircuitBreaker:
    """Circuit breaker for an individual AI.

    States:
    - CLOSED: Normal operation, requests pass through
    - OPEN: Too many failures, requests rejected
    - HALF_OPEN: Testing recovery, limited requests allowed
    """

    def __init__(
        self,
        ai_id: str,
        failure_threshold: int = 5,
        cooldown_seconds: float = 300.0,
        on_state_change: Callable[[str, CircuitState, CircuitState], None] | None = None,
    ) -> None:
        self._ai_id = ai_id
        self._failure_threshold = failure_threshold
        self._cooldown_seconds = cooldown_seconds
        self._on_state_change = on_state_change

        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._last_failure_time = 0.0

    @property
    def state(self) -> CircuitState:
        return self._state

    def is_open(self) -> bool:
        """Pure check: is the circuit currently open? No side effects."""
        if self._state == CircuitState.OPEN:
            return True
        return False

    def should_allow(self) -> bool:
        """Check if a request should be allowed. May trigger HALF_OPEN transition."""
        if self._state == CircuitState.CLOSED:
            return True
        if self._state == CircuitState.HALF_OPEN:
            return True
        # OPEN state — check if cooldown passed
        if time.time() - self._last_failure_time >= self._cooldown_seconds:
            self._transition(CircuitState.HALF_OPEN)
            return True
        return False

    def record_success(self) -> None:
        """Record a successful request."""
        self._consecutive_failures = 0
        if self._state == CircuitState.HALF_OPEN:
            self._transition(CircuitState.CLOSED)

    def record_failure(self) -> None:
        """Record a failed request."""
        self._consecutive_failures += 1
        self._last_failure_time = time.time()

        if self._state == CircuitState.HALF_OPEN:
            self._transition(CircuitState.OPEN)
        elif self._consecutive_failures >= self._failure_threshold:
            self._transition(CircuitState.OPEN)

    def _transition(self, new_state: CircuitState) -> None:
        """Transition to a new state."""
        old = self._state
        self._state = new_state
        if self._on_state_change and old != new_state:
            self._on_state_change(self._ai_id, old, new_state)

    def reset(self) -> None:
        """Reset to CLOSED state."""
        self._consecutive_failures = 0
        self._state = CircuitState.CLOSED
```

---

# FILE: backend/engine/layers/layer1_ai_access/managers/provider_manager.py

```
"""ProviderManager — AI adapter registry."""

from __future__ import annotations

from typing import TYPE_CHECKING

from shared.types import AIStatus, ProviderStatus

if TYPE_CHECKING:
    from ..adapter import AIAdapter


class ProviderManager:
    """Registry for AI adapters. Manages registration, lookup, and status."""

    def __init__(self) -> None:
        self._adapters: dict[str, AIAdapter] = {}

    def register(self, adapter: AIAdapter) -> None:
        """Register an AI adapter."""
        self._adapters[adapter.ai_id] = adapter

    def get(self, ai_id: str) -> AIAdapter | None:
        """Get an adapter by ID."""
        return self._adapters.get(ai_id)

    def get_all(self) -> list[AIAdapter]:
        """Get all registered adapters."""
        return list(self._adapters.values())

    def get_all_status(self) -> list[ProviderStatus]:
        """Get status of all registered adapters."""
        return [adapter.get_status() for adapter in self._adapters.values()]

    def get_status(self, ai_id: str) -> ProviderStatus | None:
        """Get status of a specific adapter."""
        adapter = self._adapters.get(ai_id)
        return adapter.get_status() if adapter else None

    @property
    def registered_ids(self) -> list[str]:
        """List all registered AI IDs."""
        return list(self._adapters.keys())
```

---

# FILE: backend/engine/layers/layer1_ai_access/managers/rate_limiter.py

```
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
```

---

# FILE: backend/engine/layers/layer2_scheduler/__init__.py

```
"""Layer 2: Scheduler Center.

Thin orchestration layer: dispatches tasks to Layer 1, never touches content.
"""

from .scheduler_center import SchedulerCenter
from .retry_manager import RetryManager
from .timeout_manager import TimeoutManager
from .concurrency_controller import ConcurrencyController

__all__ = ["SchedulerCenter", "RetryManager", "TimeoutManager", "ConcurrencyController"]
```

---

# FILE: backend/engine/layers/layer2_scheduler/scheduler_center.py

```
"""SchedulerCenter — unified entry point for Layer 2."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid

from shared.event_bus import EventBus
from shared.types import (
    AIAvailability,
    QueryRequest,
    TaskHandle,
    TaskStatus,
    TaskStatusInfo,
    TaskProgress,
    TaskMode,
    AIStatus,
    SubmitOptions,
)
from shared.errors import TaskValidationError, NoAvailableAIError

from ..layer1_ai_access.manager import AIAccessManager
from .retry_manager import RetryManager
from .timeout_manager import TimeoutManager
from .concurrency_controller import ConcurrencyController

logger = logging.getLogger(__name__)


class SchedulerCenter:
    """Scheduler Center — thin orchestration layer.

    Responsibilities:
    - Validate query requests
    - Check AI availability
    - Dispatch to AIAccessManager with concurrency/retry/timeout control
    - Track task lifecycle
    - Never read/store/analyze AI response content
    """

    def __init__(
        self,
        ai_manager: AIAccessManager,
        event_bus: EventBus | None = None,
        max_concurrent: int = 2,
        ai_min_interval_ms: int = 2000,
        max_retries: int = 2,
        soft_timeout_ms: int = 60000,
        hard_timeout_ms: int = 180000,
    ) -> None:
        self._ai_manager = ai_manager
        self._event_bus = event_bus or EventBus()
        self._tasks: dict[str, TaskStatusInfo] = {}
        self._cancel_events: dict[str, asyncio.Event] = {}
        self._max_stored_tasks = 1000  # LRU limit

        self._retry = RetryManager(max_retries=max_retries)
        self._timeout = TimeoutManager(soft_timeout_ms=soft_timeout_ms, hard_timeout_ms=hard_timeout_ms)
        self._concurrency = ConcurrencyController(
            max_concurrent=max_concurrent,
            ai_min_interval_ms=ai_min_interval_ms,
        )

    async def submit_query(self, request: QueryRequest) -> TaskHandle:
        """Submit a query for multi-AI processing.

        Validates → checks availability → dispatches → returns handle.
        """
        # Validate
        if not request.query.strip():
            raise TaskValidationError("Query cannot be empty")
        if not request.selected_ai_ids:
            raise TaskValidationError("At least one AI must be selected")

        # Check availability
        availability = self.get_available_ais()
        available_ids = {ai_id for ai_id, _ in availability.available}

        # Filter to available AIs
        usable_ids = [ai_id for ai_id in request.selected_ai_ids if ai_id in available_ids]
        if not usable_ids:
            raise NoAvailableAIError()

        # Create task
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        now = time.time()

        task_info = TaskStatusInfo(
            task_id=task_id,
            status=TaskStatus.CREATED,
            progress=TaskProgress(total_ais=len(usable_ids)),
            created_at=now,
            updated_at=now,
        )
        self._tasks[task_id] = task_info

        # Publish created event
        await self._event_bus.emit(
            "scheduler:task:created",
            task_id=task_id,
            selected_ai_ids=usable_ids,
            mode=request.mode.value,
            query=request.query,
        )

        # Transition to DISPATCHED
        self._tasks[task_id] = TaskStatusInfo(
            task_id=task_id,
            status=TaskStatus.DISPATCHED,
            progress=task_info.progress,
            created_at=now,
            updated_at=time.time(),
        )

        # Publish dispatched event (triggers Layer 3 collection)
        await self._event_bus.emit(
            "scheduler:task:dispatched",
            task_id=task_id,
            selected_ai_ids=usable_ids,
            query=request.query,
            mode=request.mode.value,
        )

        # Create cancel event and execute in background
        self._cancel_events[task_id] = asyncio.Event()
        asyncio.create_task(self._execute_task_safe(task_id, request.query, usable_ids))

        return TaskHandle(task_id=task_id, status=TaskStatus.DISPATCHED, created_at=now)

    async def _execute_task_safe(self, task_id: str, query: str, ai_ids: list[str]) -> None:
        """Wrapper that catches unhandled exceptions in background tasks."""
        try:
            await self._execute_task(task_id, query, ai_ids)
        except Exception:
            logger.exception("Unhandled error in task %s", task_id)
            if task_id in self._tasks and self._tasks[task_id].status not in (
                TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED
            ):
                self._tasks[task_id] = TaskStatusInfo(
                    task_id=task_id,
                    status=TaskStatus.FAILED,
                    progress=self._tasks[task_id].progress,
                    created_at=self._tasks[task_id].created_at,
                    updated_at=time.time(),
                )
        finally:
            self._cancel_events.pop(task_id, None)

    async def _execute_task(self, task_id: str, query: str, ai_ids: list[str]) -> None:
        """Execute the task with concurrency/retry/timeout control."""
        cancel = self._cancel_events.get(task_id)

        # Transition to RUNNING
        self._tasks[task_id] = TaskStatusInfo(
            task_id=task_id,
            status=TaskStatus.RUNNING,
            progress=self._tasks[task_id].progress,
            created_at=self._tasks[task_id].created_at,
            updated_at=time.time(),
        )

        self._timeout.start(task_id)

        async def _send_one(ai_id: str):
            """Send to a single AI with concurrency control."""
            if cancel and cancel.is_set():
                return ai_id, None
            await self._concurrency.acquire(ai_id)
            try:
                return ai_id, await self._send_with_retry(task_id, ai_id, query)
            finally:
                self._concurrency.release(ai_id)

        # True parallel execution via asyncio.gather
        responses = await asyncio.gather(
            *[_send_one(ai_id) for ai_id in ai_ids],
            return_exceptions=True,
        )

        results = {}
        for item in responses:
            if isinstance(item, Exception):
                logger.error("Task %s: unexpected error in parallel dispatch: %s", task_id, item)
                continue
            ai_id, response = item
            results[ai_id] = response

        self._timeout.finish(task_id)

        # Count successes/failures
        success_count = sum(1 for r in results.values() if r and r.success)
        fail_count = len(ai_ids) - success_count

        if success_count == len(ai_ids):
            final_status = TaskStatus.COMPLETED
        elif success_count > 0:
            final_status = TaskStatus.PARTIAL
        else:
            final_status = TaskStatus.FAILED

        self._tasks[task_id] = TaskStatusInfo(
            task_id=task_id,
            status=final_status,
            progress=TaskProgress(
                total_ais=len(ai_ids),
                completed_ais=success_count,
                failed_ais=fail_count,
            ),
            created_at=self._tasks[task_id].created_at,
            updated_at=time.time(),
        )

        logger.info("Task %s completed: %s (%d/%d success)", task_id, final_status.value, success_count, len(ai_ids))

    async def _send_with_retry(self, task_id: str, ai_id: str, query: str):
        """Send to AI with retry logic."""
        options = SubmitOptions(timeout_ms=self._timeout.hard_timeout_ms)

        while True:
            response = await self._ai_manager.send_to_ai(ai_id, query, options, task_id=task_id)

            if response.success:
                self._retry.reset(task_id)
                return response

            # Check if should retry
            error_code = response.error_code or "UNKNOWN"
            if self._retry.should_retry(task_id, error_code):
                attempt = self._retry.record_attempt(task_id)
                delay_ms = self._retry.get_delay_ms(task_id)
                logger.info("Task %s: retrying %s (attempt %d, delay %dms)", task_id, ai_id, attempt, delay_ms)
                await asyncio.sleep(delay_ms / 1000)
                continue

            # No more retries
            self._retry.reset(task_id)
            return response

    def cancel_task(self, task_id: str) -> None:
        """Cancel a task and signal in-flight work to stop."""
        if task_id in self._tasks:
            old = self._tasks[task_id]
            self._tasks[task_id] = TaskStatusInfo(
                task_id=task_id,
                status=TaskStatus.CANCELLED,
                progress=old.progress,
                created_at=old.created_at,
                updated_at=time.time(),
            )
        # Signal cancellation to the background task
        cancel_event = self._cancel_events.get(task_id)
        if cancel_event:
            cancel_event.set()

    def get_task_status(self, task_id: str) -> TaskStatusInfo | None:
        """Get task status."""
        return self._tasks.get(task_id)

    def get_available_ais(self) -> AIAvailability:
        """Check which AIs are available."""
        all_status = self._ai_manager.get_ready_ais()
        available = []
        unavailable = []

        for status in all_status:
            if status.status == AIStatus.READY:
                available.append((status.ai_id, status.ai_name))
            else:
                unavailable.append((status.ai_id, status.status.value))

        return AIAvailability(available=available, unavailable=unavailable)

    def cleanup_old_tasks(self, max_age_seconds: float = 3600) -> int:
        """Remove completed/failed tasks older than max_age_seconds."""
        now = time.time()
        to_remove = []
        for task_id, task in self._tasks.items():
            if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                if now - task.updated_at > max_age_seconds:
                    to_remove.append(task_id)

        for task_id in to_remove:
            del self._tasks[task_id]
            self._cancel_events.pop(task_id, None)

        # Enforce max size (remove oldest)
        while len(self._tasks) > self._max_stored_tasks:
            oldest = min(self._tasks, key=lambda k: self._tasks[k].updated_at)
            del self._tasks[oldest]
            self._cancel_events.pop(oldest, None)

        if to_remove:
            logger.info("Cleaned up %d old tasks", len(to_remove))
        return len(to_remove)
```

---

# FILE: backend/engine/layers/layer2_scheduler/concurrency_controller.py

```
"""ConcurrencyController — global concurrency window + per-AI interval."""

from __future__ import annotations

import asyncio
import time
import logging

logger = logging.getLogger(__name__)


class ConcurrencyController:
    """Controls concurrent task execution.

    - Global max concurrent tasks (default 2) via asyncio.Semaphore
    - Per-AI minimum interval (default 2000ms)
    """

    def __init__(
        self,
        max_concurrent: int = 2,
        ai_min_interval_ms: int = 2000,
    ) -> None:
        self._max_concurrent = max_concurrent
        self._ai_min_interval_ms = ai_min_interval_ms
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._last_dispatch: dict[str, float] = {}
        self._lock = asyncio.Lock()

    @property
    def active_count(self) -> int:
        return self._max_concurrent - self._semaphore._value

    @property
    def available_slots(self) -> int:
        return max(0, self._semaphore._value)

    async def acquire(self, ai_id: str) -> None:
        """Wait until we can dispatch to this AI (concurrency + interval)."""
        # Wait for a concurrency slot
        await self._semaphore.acquire()

        # Wait for per-AI interval
        async with self._lock:
            last = self._last_dispatch.get(ai_id, 0)
            elapsed_ms = (time.time() - last) * 1000
            if elapsed_ms < self._ai_min_interval_ms:
                wait_s = (self._ai_min_interval_ms - elapsed_ms) / 1000
                # Release semaphore during wait, re-acquire after
                self._semaphore.release()
                await asyncio.sleep(wait_s)
                await self._semaphore.acquire()

            self._last_dispatch[ai_id] = time.time()

    def release(self, ai_id: str | None = None) -> None:
        """Release a concurrency slot."""
        try:
            self._semaphore.release()
        except ValueError:
            logger.warning("Attempted to release more slots than acquired")

    def reset(self) -> None:
        """Reset all state."""
        self._last_dispatch.clear()
```

---

# FILE: backend/engine/layers/layer2_scheduler/retry_manager.py

```
"""RetryManager — fixed-delay retry with configurable policy."""

from __future__ import annotations

import asyncio
import logging
import time

logger = logging.getLogger(__name__)


class RetryManager:
    """Manages retry logic for failed AI requests.

    Policy: fixed delay with optional backoff multiplier.
    """

    def __init__(
        self,
        max_retries: int = 2,
        retry_delay_ms: int = 3000,
        backoff_multiplier: float = 1.5,
        retry_on: set[str] | None = None,
        no_retry_on: set[str] | None = None,
    ) -> None:
        self._max_retries = max_retries
        self._retry_delay_ms = retry_delay_ms
        self._backoff_multiplier = backoff_multiplier
        self._retry_on = retry_on or {"AI_TIMEOUT", "AI_CONNECTION_ERROR", "INTERNAL_ERROR"}
        self._no_retry_on = no_retry_on or {"LOGIN_REQUIRED", "CAPTCHA_REQUIRED", "CIRCUIT_OPEN"}
        self._attempt_counts: dict[str, int] = {}

    def should_retry(self, task_id: str, error_code: str) -> bool:
        """Check if a failed task should be retried."""
        if error_code in self._no_retry_on:
            return False
        if error_code not in self._retry_on:
            return False

        attempts = self._attempt_counts.get(task_id, 0)
        return attempts < self._max_retries

    def record_attempt(self, task_id: str) -> int:
        """Record a retry attempt. Returns the current attempt number."""
        self._attempt_counts[task_id] = self._attempt_counts.get(task_id, 0) + 1
        return self._attempt_counts[task_id]

    def get_delay_ms(self, task_id: str) -> int:
        """Get the delay before the next retry attempt."""
        attempts = self._attempt_counts.get(task_id, 0)
        delay = self._retry_delay_ms * (self._backoff_multiplier ** attempts)
        return int(delay)

    def reset(self, task_id: str) -> None:
        """Reset attempt count for a task."""
        self._attempt_counts.pop(task_id, None)

    def reset_all(self) -> None:
        """Reset all attempt counts."""
        self._attempt_counts.clear()
```

---

# FILE: backend/engine/layers/layer2_scheduler/timeout_manager.py

```
"""TimeoutManager — soft and hard timeout management."""

from __future__ import annotations

import asyncio
import logging
import time

logger = logging.getLogger(__name__)


class TimeoutManager:
    """Manages timeouts for AI requests.

    - Soft timeout: check if partial output exists, ask user to continue
    - Hard timeout: force stop, mark as TIMEOUT
    """

    def __init__(
        self,
        soft_timeout_ms: int = 60000,
        hard_timeout_ms: int = 180000,
    ) -> None:
        self._soft_timeout_ms = soft_timeout_ms
        self._hard_timeout_ms = hard_timeout_ms
        self._start_times: dict[str, float] = {}

    @property
    def soft_timeout_ms(self) -> int:
        return self._soft_timeout_ms

    @property
    def hard_timeout_ms(self) -> int:
        return self._hard_timeout_ms

    def start(self, task_id: str) -> None:
        """Start tracking a task's timeout."""
        self._start_times[task_id] = time.time() * 1000

    def check(self, task_id: str) -> str:
        """Check timeout status. Returns 'ok', 'soft_timeout', or 'hard_timeout'."""
        start = self._start_times.get(task_id)
        if start is None:
            return "ok"

        elapsed = time.time() * 1000 - start
        if elapsed >= self._hard_timeout_ms:
            return "hard_timeout"
        if elapsed >= self._soft_timeout_ms:
            return "soft_timeout"
        return "ok"

    def elapsed_ms(self, task_id: str) -> int:
        """Get elapsed time in ms for a task."""
        start = self._start_times.get(task_id)
        if start is None:
            return 0
        return int(time.time() * 1000 - start)

    def finish(self, task_id: str) -> None:
        """Stop tracking a task."""
        self._start_times.pop(task_id, None)

    def reset(self) -> None:
        """Reset all tracking."""
        self._start_times.clear()
```

---

# FILE: backend/engine/layers/layer3_collector/__init__.py

```
"""Layer 3: Result Collection Center.

Collects AI responses, normalizes them, and assembles RoundContext.
"""

from .result_collector import ResultCollector

__all__ = ["ResultCollector"]
```

---

# FILE: backend/engine/layers/layer3_collector/result_collector.py

```
"""ResultCollector — unified entry point for Layer 3."""

from __future__ import annotations

import logging
import time

from shared.event_bus import EventBus
from shared.types import (
    AiResult,
    CollectorProgress,
    NormalizedResponse,
    ResultStatus,
    RoundContext,
    RoundContextSummary,
    TaskMode,
    generate_id,
)

from ..layer1_ai_access.response_normalizer import ResponseNormalizer

logger = logging.getLogger(__name__)


class ResultCollector:
    """Result Collection Center — data bus for the system.

    Listens for ai:task:completed/failed events, normalizes responses,
    assembles RoundContext when all results are collected.
    """

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self._event_bus = event_bus or EventBus()
        self._normalizer = ResponseNormalizer()
        self._pending: dict[str, dict[str, AiResult]] = {}  # task_id -> {ai_id: AiResult}
        self._expected: dict[str, int] = {}  # task_id -> expected count
        self._contexts: dict[str, RoundContext] = {}  # task_id -> RoundContext
        self._queries: dict[str, str] = {}  # task_id -> original query
        self._modes: dict[str, TaskMode] = {}  # task_id -> execution mode

        # Register event handlers
        self._event_bus.on("ai:task:completed", self._on_task_completed)
        self._event_bus.on("ai:task:failed", self._on_task_failed)
        self._event_bus.on("scheduler:task:dispatched", self._on_task_dispatched)

    def _on_task_dispatched(self, task_id: str, selected_ai_ids: list[str], query: str = "", mode: str = "parallel", **kwargs) -> None:
        """Handle task dispatched event — prepare collection."""
        self._pending[task_id] = {}
        self._expected[task_id] = len(selected_ai_ids)
        self._queries[task_id] = query
        self._modes[task_id] = TaskMode(mode) if mode in ("parallel", "sequential") else TaskMode.PARALLEL
        logger.info("Collector ready for task %s, expecting %d results", task_id, len(selected_ai_ids))

    async def _on_task_completed(self, task_id: str, ai_id: str, response, **kwargs) -> None:
        """Handle a successful AI response."""
        normalized = self._normalizer.normalize(response.content)

        result = AiResult(
            ai_id=ai_id,
            task_id=task_id,
            round_number=1,
            status=ResultStatus.SUCCESS,
            raw_text=response.content,
            normalized=normalized,
            start_time=response.timestamp - response.duration,
            end_time=response.timestamp,
            duration=response.duration,
            prompt_used="",
            model=response.model,
        )

        if task_id not in self._pending:
            self._pending[task_id] = {}
        self._pending[task_id][ai_id] = result

        await self._check_completion(task_id)

    async def _on_task_failed(self, task_id: str, ai_id: str, error: str, **kwargs) -> None:
        """Handle a failed AI response."""
        result = AiResult(
            ai_id=ai_id,
            task_id=task_id,
            round_number=1,
            status=ResultStatus.ERROR,
            raw_text="",
            normalized=NormalizedResponse(main_text=""),
            error=error,
        )

        if task_id not in self._pending:
            self._pending[task_id] = {}
        self._pending[task_id][ai_id] = result

        await self._check_completion(task_id)

    async def _check_completion(self, task_id: str) -> None:
        """Check if all expected results have been collected."""
        pending = self._pending.get(task_id, {})
        expected = self._expected.get(task_id, 0)

        if len(pending) >= expected:
            await self._assemble_context(task_id)

    async def _assemble_context(self, task_id: str) -> None:
        """Assemble RoundContext and emit event."""
        pending = self._pending.get(task_id, {})
        results = list(pending.values())

        success_count = sum(1 for r in results if r.status == ResultStatus.SUCCESS)
        failure_count = sum(1 for r in results if r.status == ResultStatus.ERROR)
        timeout_count = sum(1 for r in results if r.status == ResultStatus.TIMEOUT)

        summary = RoundContextSummary(
            total_ais=len(results),
            success_count=success_count,
            failure_count=failure_count,
            timeout_count=timeout_count,
            completed_at=time.time(),
        )

        ctx = RoundContext(
            task_id=task_id,
            round_number=1,
            query=self._queries.get(task_id, ""),
            execution_mode=self._modes.get(task_id, TaskMode.PARALLEL),
            results=results,
            summary=summary,
            created_at=time.time(),
        )

        self._contexts[task_id] = ctx

        # Clean up temporary state
        self._pending.pop(task_id, None)
        self._expected.pop(task_id, None)

        await self._event_bus.emit("collector:context:ready", context=ctx)
        logger.info("RoundContext assembled for task %s: %d results", task_id, len(results))

    def set_query(self, task_id: str, query: str, mode: TaskMode = TaskMode.PARALLEL) -> None:
        """Store the original query for a task (called by scheduler)."""
        self._queries[task_id] = query
        self._modes[task_id] = mode

    def get_round_context(self, task_id: str, round_number: int = 1) -> RoundContext | None:
        """Get RoundContext for a task."""
        return self._contexts.get(task_id)

    def get_latest_round_context(self, task_id: str) -> RoundContext | None:
        """Get the latest RoundContext for a task."""
        return self._contexts.get(task_id)

    def get_partial_results(self, task_id: str) -> list[AiResult]:
        """Get partial results for a task (before all AIs complete)."""
        pending = self._pending.get(task_id, {})
        return list(pending.values())

    def on_context_ready(self, callback) -> None:
        """Register a callback for when RoundContext is ready."""
        self._event_bus.on("collector:context:ready", callback)
```

---

# FILE: backend/engine/layers/layer4_comparison/__init__.py

```
"""Layer 4: Comparison Analysis Center.

Pure computation layer — zero AI dependency.
Transforms RoundContext into ComparisonContext with similarity/differences/unique insights.
"""

from .comparison_engine import ComparisonEngine

__all__ = ["ComparisonEngine"]
```

---

# FILE: backend/engine/layers/layer4_comparison/comparison_engine.py

```
"""ComparisonEngine — 6-stage analysis pipeline."""

from __future__ import annotations

import logging
import time

from shared.event_bus import EventBus
from shared.types import (
    ComparisonContext,
    ComparisonMetrics,
    RoundContext,
    generate_id,
)
from shared.config import ComparisonConfig
from shared.errors import InsufficientResultsError

from .pipeline.text_preprocessor import TextPreprocessor
from .pipeline.semantic_unit_extractor import SemanticUnitExtractor
from .pipeline.similarity_analyzer import SimilarityAnalyzer
from .pipeline.difference_analyzer import DifferenceAnalyzer
from .pipeline.unique_insight_extractor import UniqueInsightExtractor
from .pipeline.comparison_assembler import ComparisonAssembler

logger = logging.getLogger(__name__)


class ComparisonEngine:
    """Comparison Analysis Center — 6-stage pipeline.

    RoundContext → Preprocess → Extract Units → Similarity → Differences → Unique → ComparisonContext
    """

    def __init__(
        self,
        config: ComparisonConfig | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self._config = config or ComparisonConfig()
        self._event_bus = event_bus or EventBus()
        self._contexts: dict[str, ComparisonContext] = {}

        # Pipeline stages
        self._preprocessor = TextPreprocessor(self._config)
        self._unit_extractor = SemanticUnitExtractor()
        self._similarity_analyzer = SimilarityAnalyzer(self._config)
        self._difference_analyzer = DifferenceAnalyzer(self._config)
        self._unique_extractor = UniqueInsightExtractor(self._config)
        self._assembler = ComparisonAssembler()

    def analyze(self, context: RoundContext) -> ComparisonContext:
        """Run the full 6-stage analysis pipeline."""
        start = time.time()

        # Validate input
        successful = [r for r in context.results if r.status.value == "success"]
        if len(successful) < 2:
            return ComparisonContext(
                task_id=context.task_id,
                round_number=context.round_number,
                query=context.query,
                source_context_id=f"{context.task_id}_r{context.round_number}",
                generated_at=time.time(),
                degraded="single_source" if len(successful) == 1 else "no_results",
            )

        # Stage 1: Preprocess
        preprocessed = self._preprocessor.process(context)

        # Stage 2: Extract semantic units
        units = self._unit_extractor.extract(preprocessed)

        if not units:
            return ComparisonContext(
                task_id=context.task_id,
                round_number=context.round_number,
                query=context.query,
                source_context_id=f"{context.task_id}_r{context.round_number}",
                generated_at=time.time(),
                degraded="no_results",
            )

        # Stage 3: Similarity analysis
        matrix = self._similarity_analyzer.analyze(units)

        # Stage 4: Difference detection
        differences = self._difference_analyzer.detect(units, matrix)

        # Stage 5: Unique insight extraction
        unique_insights = self._unique_extractor.extract(units, matrix)

        # Stage 6: Assemble
        comparison_ctx = self._assembler.assemble(
            context, units, matrix, differences, unique_insights, self._config
        )

        elapsed = time.time() - start
        logger.info(
            "Comparison analysis completed for task %s in %.2fs: %d units, %d differences, %d unique",
            context.task_id, elapsed, len(units), len(differences), len(unique_insights),
        )

        self._contexts[context.task_id] = comparison_ctx
        return comparison_ctx

    def get_comparison_context(self, task_id: str) -> ComparisonContext | None:
        """Get a previously computed ComparisonContext."""
        return self._contexts.get(task_id)

    def on_analysis_completed(self, callback) -> None:
        """Register callback for analysis completion."""
        self._event_bus.on("comparison:analysis:completed", callback)
```

---

# FILE: backend/engine/layers/layer4_comparison/comparison_config.py

```
"""Comparison configuration — re-exports from shared.config."""

from shared.config import ComparisonConfig

__all__ = ["ComparisonConfig"]
```

---

# FILE: backend/engine/layers/layer4_comparison/pipeline/__init__.py

```
"""Layer 4 analysis pipeline stages."""
```

---

# FILE: backend/engine/layers/layer4_comparison/pipeline/comparison_assembler.py

```
"""Stage 6: ComparisonAssembler — assemble final ComparisonContext."""

from __future__ import annotations

import time

from shared.types import (
    ComparisonContext,
    ComparisonMetrics,
    DifferenceItem,
    RoundContext,
    SemanticUnit,
    SimilarityMatrix,
    UniqueInsight,
)
from shared.config import ComparisonConfig


class ComparisonAssembler:
    """Assemble all pipeline outputs into a ComparisonContext."""

    def assemble(
        self,
        round_ctx: RoundContext,
        units: list[SemanticUnit],
        matrix: SimilarityMatrix,
        differences: list[DifferenceItem],
        unique_insights: list[UniqueInsight],
        config: ComparisonConfig,
    ) -> ComparisonContext:
        """Build the final ComparisonContext."""
        # Compute metrics
        metrics = self._compute_metrics(units, matrix, differences)

        # Participant AI info
        ai_unit_counts: dict[str, int] = {}
        for u in units:
            ai_unit_counts[u.source_ai_id] = ai_unit_counts.get(u.source_ai_id, 0) + 1
        participant_ais = [(ai_id, count) for ai_id, count in ai_unit_counts.items()]

        return ComparisonContext(
            task_id=round_ctx.task_id,
            round_number=round_ctx.round_number,
            query=round_ctx.query,
            source_context_id=f"{round_ctx.task_id}_r{round_ctx.round_number}",
            generated_at=time.time(),
            participant_ais=participant_ais,
            semantic_units=units,
            similarity_matrix=matrix,
            differences=differences,
            unique_insights=unique_insights,
            metrics=metrics,
        )

    def _compute_metrics(
        self,
        units: list[SemanticUnit],
        matrix: SimilarityMatrix,
        differences: list[DifferenceItem],
    ) -> ComparisonMetrics:
        """Compute global comparison metrics."""
        # Overall divergence = 1 - mean(all pairwise similarities)
        all_sims = []
        n = len(units)
        for i in range(n):
            for j in range(i + 1, n):
                all_sims.append(matrix.unit_matrix[i][j])

        overall_divergence = 1.0 - (sum(all_sims) / len(all_sims)) if all_sims else 0.0

        # Top difference dimension
        top_dimension = ""
        if differences:
            top = max(differences, key=lambda d: d.strength)
            top_dimension = top.dimension

        # Pairwise AI similarities
        pairwise = []
        for i, ai_a in enumerate(matrix.ai_ids):
            for j, ai_b in enumerate(matrix.ai_ids):
                if i < j:
                    pairwise.append((ai_a, ai_b, round(matrix.pairwise_similarities[i][j], 3)))

        return ComparisonMetrics(
            total_units=len(units),
            overall_divergence=round(overall_divergence, 3),
            pairwise_similarities=pairwise,
            top_difference_dimension=top_dimension,
        )
```

---

# FILE: backend/engine/layers/layer4_comparison/pipeline/difference_analyzer.py

```
"""Stage 4: DifferenceAnalyzer — detect differences between AIs."""

from __future__ import annotations

import re
from collections import Counter

from shared.types import DifferenceItem, SemanticUnit, SimilarityMatrix, generate_id
from shared.config import ComparisonConfig

from ..clustering.union_find import UnionFind


# Keyword patterns for difference type classification
_TYPE_PATTERNS = {
    "factual": ["数据", "事实", "根据", "统计", "研究", "source", "data", "fact"],
    "methodological": ["方法", "策略", "步骤", "流程", "架构", "approach", "method", "strategy"],
    "evaluative": ["好", "坏", "优", "劣", "风险", "优势", "pros", "cons", "risk"],
    "recommendational": ["建议", "应该", "推荐", "最好", "首选", "recommend", "suggest", "should"],
}


class DifferenceAnalyzer:
    """Detect differences between AI responses.

    Uses Union-Find clustering on similarity matrix, then identifies
    cross-AI stance divergence within clusters.
    """

    def __init__(self, config: ComparisonConfig) -> None:
        self._similarity_threshold = config.similarity_threshold
        self._difference_trigger = config.difference_trigger

    def detect(
        self, units: list[SemanticUnit], matrix: SimilarityMatrix
    ) -> list[DifferenceItem]:
        """Detect differences between AI responses."""
        if len(units) < 2:
            return []

        # Step 1: Cluster similar units using Union-Find
        n = len(units)
        uf = UnionFind(n)

        for i in range(n):
            for j in range(i + 1, n):
                if matrix.unit_matrix[i][j] >= self._similarity_threshold:
                    uf.union(i, j)

        # Step 2: Analyze each cluster for cross-AI differences
        differences: list[DifferenceItem] = []
        components = uf.components()

        for root, members in components.items():
            if len(members) < 2:
                continue

            # Group members by AI
            ai_groups: dict[str, list[int]] = {}
            for idx in members:
                ai_id = units[idx].source_ai_id
                if ai_id not in ai_groups:
                    ai_groups[ai_id] = []
                ai_groups[ai_id].append(idx)

            # Only look at clusters with multiple AIs
            if len(ai_groups) < 2:
                continue

            # Check cross-AI similarity within cluster
            ai_ids = list(ai_groups.keys())
            for i_ai in range(len(ai_ids)):
                for j_ai in range(i_ai + 1, len(ai_ids)):
                    ai_a = ai_ids[i_ai]
                    ai_b = ai_ids[j_ai]

                    # Average similarity between these two AIs in this cluster
                    cross_sims = []
                    for idx_a in ai_groups[ai_a]:
                        for idx_b in ai_groups[ai_b]:
                            cross_sims.append(matrix.unit_matrix[idx_a][idx_b])

                    if not cross_sims:
                        continue

                    avg_sim = sum(cross_sims) / len(cross_sims)

                    # If similarity is below difference trigger, it's a difference
                    if avg_sim < self._difference_trigger:
                        # Extract dimension from keyword frequency
                        all_text = " ".join(units[idx].content for idx in members)
                        dimension = self._extract_dimension(all_text)

                        # Classify type
                        diff_type = self._classify_type(all_text)

                        # Get stance summaries
                        stance_a = units[ai_groups[ai_a][0]].content[:100]
                        stance_b = units[ai_groups[ai_b][0]].content[:100]

                        strength = 1.0 - avg_sim
                        related_ids = [units[idx].unit_id for idx in members]

                        differences.append(DifferenceItem(
                            id=generate_id("diff"),
                            dimension=dimension,
                            involved_ais=[(ai_a, stance_a), (ai_b, stance_b)],
                            strength=round(strength, 3),
                            diff_type=diff_type,
                            related_unit_ids=related_ids,
                        ))

        return differences

    def _extract_dimension(self, text: str) -> str:
        """Extract topic dimension from text using keyword frequency."""
        # Simple: use most frequent meaningful words
        words = re.findall(r"[\w一-鿿]{2,}", text)
        freq = Counter(words)
        # Filter stopwords
        stopwords = {"的", "是", "在", "了", "和", "也", "就", "都", "而", "及", "与", "或", "the", "is", "and", "to", "of", "a", "in", "that", "for", "it"}
        meaningful = [(w, c) for w, c in freq.most_common(10) if w.lower() not in stopwords]
        if meaningful:
            return meaningful[0][0]
        return "未分类"

    def _classify_type(self, text: str) -> str:
        """Classify difference type using keyword patterns."""
        scores = {}
        text_lower = text.lower()
        for dtype, keywords in _TYPE_PATTERNS.items():
            scores[dtype] = sum(1 for kw in keywords if kw in text_lower)

        if not scores or max(scores.values()) == 0:
            return "evaluative"

        return max(scores, key=scores.get)
```

---

# FILE: backend/engine/layers/layer4_comparison/pipeline/semantic_unit_extractor.py

```
"""Stage 2: SemanticUnitExtractor — convert paragraphs to SemanticUnit objects."""

from __future__ import annotations

from shared.types import SemanticUnit, generate_id

from .text_preprocessor import PreprocessedAI

DEFAULT_MAX_UNITS_PER_AI = 100


class SemanticUnitExtractor:
    """Convert preprocessed paragraphs into SemanticUnit IR."""

    def __init__(self, max_units_per_ai: int = DEFAULT_MAX_UNITS_PER_AI) -> None:
        self._max_units_per_ai = max_units_per_ai

    def extract(self, preprocessed: list[PreprocessedAI]) -> list[SemanticUnit]:
        """Create SemanticUnit from each paragraph, capped per AI."""
        units = []
        for ai in preprocessed:
            for i, paragraph in enumerate(ai.clean_paragraphs[:self._max_units_per_ai]):
                units.append(SemanticUnit(
                    unit_id=generate_id("unit"),
                    source_ai_id=ai.ai_id,
                    content=paragraph,
                    paragraph_index=ai.original_indices[i],
                    unit_type="paragraph",
                ))
        return units
```

---

# FILE: backend/engine/layers/layer4_comparison/pipeline/similarity_analyzer.py

```
"""Stage 3: SimilarityAnalyzer — compute similarity matrix."""

from __future__ import annotations

from shared.types import SemanticUnit, SimilarityMatrix
from shared.config import ComparisonConfig

from ..similarity.tfidf_calculator import TfidfCalculator
from ..similarity.cosine_similarity import cosine_similarity
from ..similarity.lcs_calculator import lcs_ratio


class SimilarityAnalyzer:
    """Compute unit-level and AI-level similarity matrices.

    Uses weighted combination: sim = tfidf_weight * cosine(tfidf) + lcs_weight * lcs_ratio
    """

    def __init__(self, config: ComparisonConfig) -> None:
        self._tfidf_weight = config.tfidf_weight
        self._lcs_weight = config.lcs_weight

    def analyze(self, units: list[SemanticUnit]) -> SimilarityMatrix:
        """Compute similarity matrices for all semantic units."""
        n = len(units)
        if n == 0:
            return SimilarityMatrix()

        # Compute TF-IDF vectors
        calculator = TfidfCalculator()
        documents = [u.content for u in units]
        tfidf_vectors = calculator.fit_transform(documents)

        # Build unit-level similarity matrix
        unit_matrix: list[list[float]] = [[0.0] * n for _ in range(n)]
        for i in range(n):
            unit_matrix[i][i] = 1.0
            for j in range(i + 1, n):
                # TF-IDF cosine similarity
                tfidf_sim = cosine_similarity(tfidf_vectors[i], tfidf_vectors[j])
                # LCS ratio
                lcs_sim = lcs_ratio(units[i].content, units[j].content)
                # Weighted combination
                sim = self._tfidf_weight * tfidf_sim + self._lcs_weight * lcs_sim
                unit_matrix[i][j] = sim
                unit_matrix[j][i] = sim

        # Build AI-level pairwise similarity
        ai_ids = list(dict.fromkeys(u.source_ai_id for u in units))
        ai_index = {ai_id: i for i, ai_id in enumerate(ai_ids)}
        ai_sims: dict[tuple[str, str], list[float]] = {}

        for i in range(n):
            for j in range(i + 1, n):
                ai_a = units[i].source_ai_id
                ai_b = units[j].source_ai_id
                if ai_a != ai_b:
                    key = (min(ai_a, ai_b), max(ai_a, ai_b))
                    if key not in ai_sims:
                        ai_sims[key] = []
                    ai_sims[key].append(unit_matrix[i][j])

        # Average pairwise similarities
        pairwise: list[list[float]] = [[0.0] * len(ai_ids) for _ in range(len(ai_ids))]
        for i in range(len(ai_ids)):
            pairwise[i][i] = 1.0

        for (ai_a, ai_b), sims in ai_sims.items():
            avg = sum(sims) / len(sims) if sims else 0.0
            idx_a = ai_index[ai_a]
            idx_b = ai_index[ai_b]
            pairwise[idx_a][idx_b] = avg
            pairwise[idx_b][idx_a] = avg

        return SimilarityMatrix(
            ai_ids=ai_ids,
            pairwise_similarities=pairwise,
            unit_matrix=unit_matrix,
            unit_index=[u.unit_id for u in units],
        )
```

---

# FILE: backend/engine/layers/layer4_comparison/pipeline/text_preprocessor.py

```
"""Stage 1: TextPreprocessor — extract and clean paragraphs from RoundContext."""

from __future__ import annotations

import re
from dataclasses import dataclass

from shared.types import RoundContext, AiResult, ResultStatus
from shared.config import ComparisonConfig


@dataclass(frozen=True)
class PreprocessedAI:
    ai_id: str
    clean_paragraphs: list[str]
    original_indices: list[int]


class TextPreprocessor:
    """Clean and filter paragraphs from AI results."""

    def __init__(self, config: ComparisonConfig) -> None:
        self._min_length = config.min_paragraph_length

    def process(self, context: RoundContext) -> list[PreprocessedAI]:
        """Extract and clean paragraphs from successful AI results."""
        result = []
        for ai_result in context.results:
            if ai_result.status != ResultStatus.SUCCESS:
                continue

            clean_paragraphs = []
            original_indices = []

            for i, para in enumerate(ai_result.normalized.paragraphs):
                # Normalize whitespace
                cleaned = re.sub(r"\s+", " ", para).strip()
                # Filter short paragraphs
                if len(cleaned) >= self._min_length:
                    clean_paragraphs.append(cleaned)
                    original_indices.append(i)

            if clean_paragraphs:
                result.append(PreprocessedAI(
                    ai_id=ai_result.ai_id,
                    clean_paragraphs=clean_paragraphs,
                    original_indices=original_indices,
                ))

        return result
```

---

# FILE: backend/engine/layers/layer4_comparison/pipeline/unique_insight_extractor.py

```
"""Stage 5: UniqueInsightExtractor — find unique viewpoints from individual AIs."""

from __future__ import annotations

from shared.types import SemanticUnit, SimilarityMatrix, UniqueInsight
from shared.config import ComparisonConfig


class UniqueInsightExtractor:
    """Extract unique viewpoints that only one AI mentioned.

    A unit is "unique" if its max similarity to all other-AI units is below threshold.
    """

    def __init__(self, config: ComparisonConfig) -> None:
        self._uniqueness_threshold = config.uniqueness_threshold

    def extract(
        self, units: list[SemanticUnit], matrix: SimilarityMatrix
    ) -> list[UniqueInsight]:
        """Find unique insights from each AI."""
        insights: list[UniqueInsight] = []

        for i, unit in enumerate(units):
            # Find max similarity to any unit from a different AI
            max_sim = 0.0
            for j, other in enumerate(units):
                if i == j:
                    continue
                if other.source_ai_id == unit.source_ai_id:
                    continue
                max_sim = max(max_sim, matrix.unit_matrix[i][j])

            # If below threshold, it's a unique insight
            if max_sim < self._uniqueness_threshold:
                novelty_score = 1.0 - max_sim

                # Determine importance based on content length and keywords
                importance = self._assess_importance(unit.content)

                insights.append(UniqueInsight(
                    unit_id=unit.unit_id,
                    ai_id=unit.source_ai_id,
                    content=unit.content[:200],
                    novelty_score=round(novelty_score, 3),
                    potential_importance=importance,
                ))

        return insights

    def _assess_importance(self, content: str) -> str:
        """Heuristic importance assessment based on length and keywords."""
        high_keywords = ["创新", "独特", "关键", "重要", "核心", "critical", "key", "innovative", "unique"]
        length = len(content)

        has_keyword = any(kw in content.lower() for kw in high_keywords)

        if length > 100 or has_keyword:
            return "high"
        elif length > 50:
            return "medium"
        return "low"
```

---

# FILE: backend/engine/layers/layer4_comparison/similarity/__init__.py

```
"""Similarity computation modules."""
```

---

# FILE: backend/engine/layers/layer4_comparison/similarity/cosine_similarity.py

```
"""Cosine similarity between sparse vectors."""

from __future__ import annotations

import math


def cosine_similarity(vec_a: dict[str, float], vec_b: dict[str, float]) -> float:
    """Compute cosine similarity between two sparse vectors.

    Vectors are dicts of term -> weight.
    Returns 0.0 if either vector is empty.
    """
    if not vec_a or not vec_b:
        return 0.0

    # Find common terms
    common_terms = set(vec_a.keys()) & set(vec_b.keys())
    if not common_terms:
        return 0.0

    # Dot product
    dot = sum(vec_a[t] * vec_b[t] for t in common_terms)

    # Magnitudes
    mag_a = math.sqrt(sum(v * v for v in vec_a.values()))
    mag_b = math.sqrt(sum(v * v for v in vec_b.values()))

    if mag_a == 0 or mag_b == 0:
        return 0.0

    return dot / (mag_a * mag_b)
```

---

# FILE: backend/engine/layers/layer4_comparison/similarity/lcs_calculator.py

```
"""Longest Common Subsequence (LCS) ratio calculator."""

from __future__ import annotations

# Guard: skip LCS for texts longer than this to avoid O(n*m) blowup
MAX_LCS_LENGTH = 500


def lcs_ratio(text_a: str, text_b: str) -> float:
    """Compute LCS length / max(len(a), len(b)).

    Uses standard DP, O(n*m) complexity.
    Falls back to 0.0 for texts exceeding MAX_LCS_LENGTH.
    """
    if not text_a or not text_b:
        return 0.0

    m, n = len(text_a), len(text_b)

    # Guard against O(n*m) blowup
    if m > MAX_LCS_LENGTH or n > MAX_LCS_LENGTH:
        # Fallback: use simple word overlap ratio
        words_a = set(text_a.split())
        words_b = set(text_b.split())
        if not words_a or not words_b:
            return 0.0
        overlap = len(words_a & words_b)
        return overlap / max(len(words_a), len(words_b))

    # Optimize: only keep two rows
    prev = [0] * (n + 1)
    curr = [0] * (n + 1)

    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if text_a[i - 1] == text_b[j - 1]:
                curr[j] = prev[j - 1] + 1
            else:
                curr[j] = max(prev[j], curr[j - 1])
        prev, curr = curr, [0] * (n + 1)

    lcs_len = prev[n]
    max_len = max(m, n)
    return lcs_len / max_len if max_len > 0 else 0.0
```

---

# FILE: backend/engine/layers/layer4_comparison/similarity/tfidf_calculator.py

```
"""TF-IDF calculator using bigram tokenization (zero dependency)."""

from __future__ import annotations

import math
import re
from collections import Counter


class TfidfCalculator:
    """Compute TF-IDF vectors for text documents using bigram tokenization.

    Bigram approach: split text into overlapping 2-character sequences.
    This works well for Chinese text without any external dependency.
    """

    def __init__(self) -> None:
        self._vocabulary: dict[str, int] = {}
        self._idf: dict[str, float] = {}

    def fit_transform(self, documents: list[str]) -> list[dict[str, float]]:
        """Build vocabulary and compute TF-IDF vectors for all documents."""
        # Tokenize all documents into bigrams
        tokenized = [self._tokenize(doc) for doc in documents]

        # Build vocabulary
        all_terms = set()
        for tokens in tokenized:
            all_terms.update(tokens)
        self._vocabulary = {term: i for i, term in enumerate(sorted(all_terms))}

        # Compute IDF
        n_docs = len(documents)
        doc_freq = Counter()
        for tokens in tokenized:
            unique_terms = set(tokens)
            for term in unique_terms:
                doc_freq[term] += 1

        self._idf = {
            term: math.log((n_docs + 1) / (freq + 1)) + 1
            for term, freq in doc_freq.items()
        }

        # Compute TF-IDF for each document
        vectors = []
        for tokens in tokenized:
            tf = Counter(tokens)
            total = len(tokens) if tokens else 1
            tfidf = {}
            for term, count in tf.items():
                tfidf[term] = (count / total) * self._idf.get(term, 1.0)
            vectors.append(tfidf)

        return vectors

    def _tokenize(self, text: str) -> list[str]:
        """Tokenize text into bigrams.

        For Chinese: character-level bigrams.
        For English: word-level (split by space).
        """
        # Check if text is primarily CJK
        cjk_count = sum(1 for c in text if "一" <= c <= "鿿")
        if cjk_count / max(len(text), 1) > 0.3:
            return self._bigram_tokenize(text)
        else:
            return self._word_tokenize(text)

    def _bigram_tokenize(self, text: str) -> list[str]:
        """Character-level bigram tokenization for CJK text."""
        # Remove whitespace and punctuation
        cleaned = ""
        for c in text:
            if "一" <= c <= "鿿" or c.isalnum():
                cleaned += c
        if len(cleaned) < 2:
            return [cleaned] if cleaned else []
        return [cleaned[i : i + 2] for i in range(len(cleaned) - 1)]

    def _word_tokenize(self, text: str) -> list[str]:
        """Word-level tokenization for non-CJK text."""
        words = re.findall(r"\w+", text.lower())
        return words if words else []
```

---

# FILE: backend/engine/layers/layer4_comparison/clustering/union_find.py

```
"""Union-Find (Disjoint Set) data structure for clustering."""

from __future__ import annotations


class UnionFind:
    """Union-Find with path compression and union by rank."""

    def __init__(self, n: int) -> None:
        self._parent = list(range(n))
        self._rank = [0] * n
        self._count = n

    def find(self, x: int) -> int:
        """Find root of x with path compression."""
        if self._parent[x] != x:
            self._parent[x] = self.find(self._parent[x])
        return self._parent[x]

    def union(self, x: int, y: int) -> bool:
        """Union two sets. Returns True if they were in different sets."""
        root_x = self.find(x)
        root_y = self.find(y)

        if root_x == root_y:
            return False

        if self._rank[root_x] < self._rank[root_y]:
            root_x, root_y = root_y, root_x

        self._parent[root_y] = root_x
        if self._rank[root_x] == self._rank[root_y]:
            self._rank[root_x] += 1

        self._count -= 1
        return True

    def connected(self, x: int, y: int) -> bool:
        """Check if x and y are in the same set."""
        return self.find(x) == self.find(y)

    @property
    def count(self) -> int:
        """Number of distinct sets."""
        return self._count

    def components(self) -> dict[int, list[int]]:
        """Get all connected components as {root: [members]}."""
        result: dict[int, list[int]] = {}
        for i in range(len(self._parent)):
            root = self.find(i)
            if root not in result:
                result[root] = []
            result[root].append(i)
        return result
```

---

# FILE: backend/engine/conflict/__init__.py

```
"""Conflict engine — analyzes why AIs disagree."""
from .engine import ConflictEngine
from .result import ConflictResult, ConflictPoint
```

---

# FILE: backend/engine/conflict/engine.py

```
"""Conflict engine — analyzes why AIs disagree."""

from __future__ import annotations

import logging

from ..collector.response import AIResponse
from ..comparison.result import ComparisonResult
from .result import ConflictPoint, ConflictResult

logger = logging.getLogger(__name__)


class ConflictEngine:
    """Analyzes conflicts between AI responses.

    Takes comparison results and deepens the analysis:
    - Why do AIs disagree?
    - What are the root causes?
    - Are the conflicts resolvable?
    """

    def analyze(
        self,
        task_id: str,
        query: str,
        responses: list[AIResponse],
        comparison: ComparisonResult,
    ) -> ConflictResult:
        """Analyze conflicts from comparison results."""
        conflicts = []

        # Analyze each disagreement from comparison
        for disagreement in comparison.disagreements:
            conflict = self._analyze_disagreement(disagreement, responses)
            if conflict:
                conflicts.append(conflict)

        # Detect additional conflicts by response length variance
        if len(responses) >= 2:
            lengths = [len(r.content) for r in responses]
            avg_len = sum(lengths) / len(lengths)
            if max(lengths) > avg_len * 3:
                conflicts.append(ConflictPoint(
                    topic="回复详细度差异",
                    positions=[
                        {"provider_id": r.provider_id, "stance": f"回复长度: {len(r.content)}字"}
                        for r in responses
                    ],
                    root_cause="不同AI对问题的理解深度不同",
                    severity=0.3,
                    resolvable=True,
                ))

        # Calculate overall conflict level
        if conflicts:
            overall = sum(c.severity for c in conflicts) / len(conflicts)
        else:
            overall = 0.0

        # Generate summary
        summary = self._generate_summary(conflicts, responses)

        return ConflictResult(
            task_id=task_id,
            query=query,
            conflicts=conflicts,
            summary=summary,
            overall_conflict_level=overall,
        )

    def _analyze_disagreement(self, disagreement, responses: list[AIResponse]) -> ConflictPoint | None:
        """Analyze a single disagreement to find root cause."""
        if not disagreement.positions:
            return None

        # Simple root cause analysis
        root_cause = "不同AI基于不同训练数据和推理路径得出不同结论"

        if len(disagreement.positions) >= 2:
            stances = [p.get("stance", "") for p in disagreement.positions]
            # Check if it's a factual vs opinion disagreement
            if any(w in " ".join(stances) for w in ["数据", "事实", "统计"]):
                root_cause = "事实性分歧：不同AI引用了不同的数据来源"
            elif any(w in " ".join(stances) for w in ["我认为", "我觉得", "个人观点"]):
                root_cause = "观点性分歧：不同AI有不同的价值判断"

        return ConflictPoint(
            topic=disagreement.topic,
            positions=disagreement.positions,
            root_cause=root_cause,
            severity=disagreement.severity,
            resolvable=True,
        )

    def _generate_summary(self, conflicts: list[ConflictPoint], responses: list[AIResponse]) -> str:
        if not conflicts:
            return "未发现显著冲突。所有AI观点基本一致。"

        severe = [c for c in conflicts if c.severity >= 0.7]
        if severe:
            return f"发现 {len(conflicts)} 个冲突点，其中 {len(severe)} 个严重冲突。建议重点关注这些分歧。"
        return f"发现 {len(conflicts)} 个轻度冲突点。整体分歧可控。"
```

---

# FILE: backend/engine/conflict/result.py

```
"""Conflict result models."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ConflictPoint:
    """A specific point of conflict between AIs."""
    topic: str
    positions: list[dict]  # [{provider_id, stance, reasoning}]
    root_cause: str = ""
    severity: float = 0.0  # 0-1
    resolvable: bool = True

    def to_dict(self) -> dict:
        return {
            "topic": self.topic,
            "positions": self.positions,
            "root_cause": self.root_cause,
            "severity": self.severity,
            "resolvable": self.resolvable,
        }


@dataclass
class ConflictResult:
    """Result of conflict analysis."""
    task_id: str
    query: str
    conflicts: list[ConflictPoint] = field(default_factory=list)
    summary: str = ""
    overall_conflict_level: float = 0.0  # 0-1

    @property
    def has_conflicts(self) -> bool:
        return len(self.conflicts) > 0

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "query": self.query,
            "conflicts": [c.to_dict() for c in self.conflicts],
            "summary": self.summary,
            "overall_conflict_level": self.overall_conflict_level,
        }
```

---

# FILE: backend/engine/consensus/__init__.py

```
"""Consensus engine — generates final consensus report."""
from .engine import ConsensusEngine
from .result import ConsensusReport
```

---

# FILE: backend/engine/consensus/engine.py

```
"""Consensus engine — synthesizes comparison and conflict results into a final report."""

from __future__ import annotations

import logging

from ..collector.response import AIResponse
from ..comparison.result import ComparisonResult
from ..conflict.result import ConflictResult
from .result import ConsensusReport

logger = logging.getLogger(__name__)


class ConsensusEngine:
    """Generates the final Council Report.

    Takes comparison and conflict results and produces:
    - A clear conclusion
    - Key points from all AIs
    - Recommendations
    - Minority opinions
    """

    def generate(
        self,
        task_id: str,
        query: str,
        responses: list[AIResponse],
        comparison: ComparisonResult,
        conflict: ConflictResult,
    ) -> ConsensusReport:
        """Generate the final consensus report."""

        # Extract key points from all responses
        key_points = []
        for resp in responses:
            # Get first meaningful sentence
            sentences = resp.content.split('。')
            if sentences and len(sentences[0]) > 10:
                key_points.append(f"{resp.provider_id}: {sentences[0].strip()}")

        # Generate conclusion based on agreement level
        conclusion = self._generate_conclusion(comparison, conflict, responses)

        # Calculate confidence
        confidence = comparison.overall_agreement

        # Generate recommendations
        recommendations = self._generate_recommendations(comparison, conflict)

        # Extract minority opinions
        minority = []
        if conflict.has_conflicts:
            for c in conflict.conflicts:
                if len(c.positions) >= 2:
                    # The minority position
                    minority.append({
                        "provider_id": c.positions[-1].get("provider_id", "unknown"),
                        "opinion": c.positions[-1].get("stance", ""),
                    })

        return ConsensusReport(
            task_id=task_id,
            query=query,
            conclusion=conclusion,
            confidence=confidence,
            key_points=key_points[:5],
            recommendations=recommendations,
            minority_opinions=minority,
            metadata={
                "total_providers": len(responses),
                "agreement_count": len(comparison.agreements),
                "disagreement_count": len(comparison.disagreements),
                "conflict_count": len(conflict.conflicts),
            },
        )

    def _generate_conclusion(
        self,
        comparison: ComparisonResult,
        conflict: ConflictResult,
        responses: list[AIResponse],
    ) -> str:
        if comparison.overall_agreement >= 0.8:
            return f"所有AI高度一致。{comparison.summary}"
        elif comparison.overall_agreement >= 0.5:
            return f"多数AI观点相近，存在少量分歧。{comparison.summary}"
        elif conflict.has_conflicts:
            return f"AI之间存在显著分歧。{conflict.summary}"
        else:
            return comparison.summary

    def _generate_recommendations(
        self,
        comparison: ComparisonResult,
        conflict: ConflictResult,
    ) -> list[str]:
        recs = []

        if comparison.has_agreements:
            recs.append("综合考虑所有AI的共同观点作为基础判断")

        if conflict.has_conflicts:
            severe = [c for c in conflict.conflicts if c.severity >= 0.7]
            if severe:
                recs.append("重点关注严重冲突点，可能需要进一步调研")
            recs.append("对于分歧点，建议结合实际情况做最终判断")

        if not recs:
            recs.append("各AI观点一致，可作为可靠参考")

        return recs
```

---

# FILE: backend/engine/consensus/result.py

```
"""Consensus report model."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ConsensusReport:
    """Final council report synthesizing all analysis."""
    task_id: str
    query: str
    conclusion: str = ""
    confidence: float = 0.0  # 0-1
    key_points: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    minority_opinions: list[dict] = field(default_factory=list)  # [{provider_id, opinion}]
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "query": self.query,
            "conclusion": self.conclusion,
            "confidence": self.confidence,
            "key_points": self.key_points,
            "recommendations": self.recommendations,
            "minority_opinions": self.minority_opinions,
            "metadata": self.metadata,
        }
```

---

# FILE: backend/engine/judge/__init__.py

```
"""Judge engine — AI-powered final judgment (requires API key)."""
from .engine import JudgeEngine
from .result import JudgeVerdict
```

---

# FILE: backend/engine/judge/engine.py

```
"""Judge engine — uses external AI APIs for final judgment.

This is the V2-C component that requires API keys.
Can be used as an optional enhancement on top of the rule-based V2-A/V2-B analysis.
"""

from __future__ import annotations

import logging
from typing import Any

from ..consensus.result import ConsensusReport
from .result import JudgeVerdict

logger = logging.getLogger(__name__)


class JudgeEngine:
    """Uses external AI APIs to judge the consensus report.

    This is an OPTIONAL enhancement. The system works without it.
    Only activate when API keys are configured.
    """

    def __init__(self, api_keys: dict[str, str] | None = None):
        self._api_keys = api_keys or {}
        self._judges: dict[str, Any] = {}

    def has_api_key(self, provider: str) -> bool:
        return provider in self._api_keys

    def set_api_key(self, provider: str, api_key: str) -> None:
        self._api_keys[provider] = api_key

    async def judge(
        self,
        query: str,
        responses: list[dict],
        consensus: ConsensusReport,
        judge_provider: str = "openai",
    ) -> JudgeVerdict:
        """Use an external AI to judge the consensus.

        Args:
            query: Original user question
            responses: List of AI responses [{provider_id, content}]
            consensus: The consensus report to judge
            judge_provider: Which AI to use as judge ("openai", "claude", "gemini")

        Returns:
            JudgeVerdict with the judge's assessment
        """
        if not self.has_api_key(judge_provider):
            return JudgeVerdict(
                judge_id=judge_provider,
                query=query,
                verdict="无法执行裁决：未配置 API Key",
                confidence=0.0,
            )

        # Build the judge prompt
        prompt = self._build_judge_prompt(query, responses, consensus)

        # Call the external API
        try:
            result = await self._call_api(judge_provider, prompt)
            return JudgeVerdict(
                judge_id=judge_provider,
                query=query,
                verdict=result.get("verdict", ""),
                reasoning=result.get("reasoning", ""),
                confidence=result.get("confidence", 0.5),
                agrees_with_consensus=result.get("agrees", True),
                additional_insights=result.get("insights", []),
            )
        except Exception as e:
            logger.error("Judge %s failed: %s", judge_provider, e)
            return JudgeVerdict(
                judge_id=judge_provider,
                query=query,
                verdict=f"裁决失败: {str(e)}",
                confidence=0.0,
            )

    def _build_judge_prompt(
        self,
        query: str,
        responses: list[dict],
        consensus: ConsensusReport,
    ) -> str:
        """Build the prompt for the AI judge."""
        resp_text = "\n\n".join(
            f"--- {r['provider_id']} ---\n{r['content']}"
            for r in responses
        )

        return f"""你是一个AI裁判。请根据以下多个AI对同一问题的回答，给出你的最终裁决。

## 问题
{query}

## 各AI的回答
{resp_text}

## 当前共识
结论: {consensus.conclusion}
置信度: {consensus.confidence}
关键点: {', '.join(consensus.key_points)}

## 请你判断：
1. 你是否同意当前共识？
2. 你的最终裁决是什么？
3. 你的推理过程是什么？
4. 有没有其他AI没提到的重要观点？

请以JSON格式回答：
{{
  "verdict": "你的最终裁决",
  "reasoning": "你的推理过程",
  "confidence": 0.0到1.0的置信度,
  "agrees": true或false,
  "insights": ["额外观点1", "额外观点2"]
}}"""

    async def _call_api(self, provider: str, prompt: str) -> dict:
        """Call external AI API. Override for specific providers."""
        # Placeholder — implement actual API calls
        # For now, return a mock response
        logger.warning("Judge API call not implemented for %s", provider)
        return {
            "verdict": "需要实现API调用",
            "reasoning": "Judge Engine API调用尚未实现",
            "confidence": 0.0,
            "agrees": True,
            "insights": [],
        }
```

---

# FILE: backend/engine/judge/result.py

```
"""Judge verdict model."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class JudgeVerdict:
    """Final judgment from an AI judge."""
    judge_id: str  # e.g., "openai", "claude"
    query: str
    verdict: str = ""
    reasoning: str = ""
    confidence: float = 0.0
    agrees_with_consensus: bool = True
    additional_insights: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "judge_id": self.judge_id,
            "query": self.query,
            "verdict": self.verdict,
            "reasoning": self.reasoning,
            "confidence": self.confidence,
            "agrees_with_consensus": self.agrees_with_consensus,
            "additional_insights": self.additional_insights,
        }
```

---

# FILE: backend/engine/collector/__init__.py

```
"""Result collector — unified result format for all providers."""
from .collector import ResultCollector
from .response import AIResponse
```

---

# FILE: backend/engine/collector/collector.py

```
"""Result collector — gathers and normalizes AI responses."""

from __future__ import annotations

import logging
import time
from typing import Any

from .response import AIResponse

logger = logging.getLogger(__name__)


class ResultCollector:
    """Collects AI responses into a unified format.

    Responsibilities:
    - Normalize raw provider responses into AIResponse
    - Track collection progress
    - Assemble final results for downstream analysis
    """

    def __init__(self):
        self._results: dict[str, dict[str, AIResponse]] = {}  # task_id -> {provider_id: AIResponse}

    def collect(
        self,
        task_id: str,
        provider_id: str,
        content: str,
        response_time_ms: int = 0,
        success: bool = True,
        error: str | None = None,
    ) -> AIResponse:
        """Collect a single provider's response."""
        response = AIResponse(
            provider_id=provider_id,
            content=content,
            response_time_ms=response_time_ms,
            success=success,
            error=error,
        )

        if task_id not in self._results:
            self._results[task_id] = {}

        self._results[task_id][provider_id] = response
        logger.info("Collected response from %s for task %s (%d words)",
                    provider_id, task_id, response.word_count)
        return response

    def get_results(self, task_id: str) -> list[AIResponse]:
        """Get all collected results for a task."""
        return list(self._results.get(task_id, {}).values())

    def get_result(self, task_id: str, provider_id: str) -> AIResponse | None:
        """Get a specific provider's result."""
        return self._results.get(task_id, {}).get(provider_id)

    def clear(self, task_id: str) -> None:
        """Clear results for a task."""
        self._results.pop(task_id, None)
```

---

# FILE: backend/engine/collector/response.py

```
"""Unified AI response format."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AIResponse:
    """Unified response from any AI provider."""
    provider_id: str
    content: str
    response_time_ms: int = 0
    word_count: int = 0
    success: bool = True
    error: str | None = None
    metadata: dict = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}
        if self.word_count == 0 and self.content:
            self.word_count = self._count_words(self.content)

    @staticmethod
    def _count_words(text: str) -> int:
        """Count words (CJK-aware)."""
        import re
        cjk = len(re.findall(r"[一-鿿぀-ゟ゠-ヿ]", text))
        non_cjk = len(re.sub(r"[一-鿿぀-ゟ゠-ヿ]", " ", text).split())
        return cjk + non_cjk

    def to_dict(self) -> dict:
        return {
            "provider_id": self.provider_id,
            "content": self.content,
            "response_time_ms": self.response_time_ms,
            "word_count": self.word_count,
            "success": self.success,
            "error": self.error,
        }
```

---

# FILE: backend/engine/comparison/__init__.py

```
"""Comparison engine — analyzes agreements and disagreements between AI responses."""
from .engine import ComparisonEngine
from .result import ComparisonResult, Agreement, Disagreement
```

---

# FILE: backend/engine/comparison/engine.py

```
"""Comparison engine — rule-based analysis without API keys."""

from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Any

from ..collector.response import AIResponse
from .result import Agreement, ComparisonResult, Disagreement

logger = logging.getLogger(__name__)


class ComparisonEngine:
    """Compares multiple AI responses to find agreements and disagreements.

    Uses rule-based text analysis (no API keys needed):
    - Keyword extraction
    - Sentiment analysis (simple)
    - Sentence-level similarity
    """

    def analyze(self, task_id: str, query: str, responses: list[AIResponse]) -> ComparisonResult:
        """Analyze responses and find agreements/disagreements."""
        if len(responses) < 2:
            return ComparisonResult(
                task_id=task_id,
                query=query,
                summary="需要至少2个AI的回复才能进行对比分析",
            )

        # Extract keywords from each response
        keywords_per_provider = {}
        for resp in responses:
            keywords_per_provider[resp.provider_id] = self._extract_keywords(resp.content)

        # Find common keywords (potential agreements)
        all_keywords = list(keywords_per_provider.values())
        common = set(all_keywords[0])
        for kw in all_keywords[1:]:
            common &= kw

        # Find unique keywords per provider (potential disagreements)
        unique_per_provider = {}
        for pid, kws in keywords_per_provider.items():
            unique = kws - set().union(*[v for k, v in keywords_per_provider.items() if k != pid])
            if unique:
                unique_per_provider[pid] = unique

        # Build agreements
        agreements = []
        if common:
            agreements.append(Agreement(
                topic="共同关注点",
                description=f"所有AI都提到了: {', '.join(list(common)[:5])}",
                supporting_providers=[r.provider_id for r in responses],
                confidence=min(1.0, len(common) / 5),
            ))

        # Check for yes/no consensus
        yes_providers = []
        no_providers = []
        for resp in responses:
            first_sentence = resp.content.split('。')[0].split('.')[0].split('\n')[0]
            if any(w in first_sentence for w in ['是', '对', 'Yes', 'yes', '可以', '适合', '推荐']):
                yes_providers.append(resp.provider_id)
            elif any(w in first_sentence for w in ['否', '不', 'No', 'no', '不适合', '不推荐']):
                no_providers.append(resp.provider_id)

        if len(yes_providers) > len(no_providers) and len(yes_providers) >= 2:
            agreements.append(Agreement(
                topic="倾向性共识",
                description=f"多数AI倾向于肯定回答",
                supporting_providers=yes_providers,
                confidence=len(yes_providers) / len(responses),
            ))
        elif len(no_providers) > len(yes_providers) and len(no_providers) >= 2:
            agreements.append(Agreement(
                topic="倾向性共识",
                description=f"多数AI倾向于否定回答",
                supporting_providers=no_providers,
                confidence=len(no_providers) / len(responses),
            ))

        # Build disagreements
        disagreements = []
        if unique_per_provider:
            for pid, keywords in unique_per_provider.items():
                if len(keywords) >= 2:
                    disagreements.append(Disagreement(
                        topic=f"{pid}的独特观点",
                        positions=[{
                            "provider_id": pid,
                            "stance": f"提出了独特关键词: {', '.join(list(keywords)[:3])}",
                        }],
                        severity=0.5,
                    ))

        # Detect explicit disagreements
        for i, r1 in enumerate(responses):
            for r2 in responses[i+1:]:
                if self._has_contradiction(r1.content, r2.content):
                    disagreements.append(Disagreement(
                        topic="观点对立",
                        positions=[
                            {"provider_id": r1.provider_id, "stance": r1.content[:100]},
                            {"provider_id": r2.provider_id, "stance": r2.content[:100]},
                        ],
                        severity=0.8,
                    ))

        # Calculate overall agreement
        if agreements and not disagreements:
            overall = 0.9
        elif agreements and disagreements:
            overall = 0.5
        elif not agreements and disagreements:
            overall = 0.2
        else:
            overall = 0.6

        # Generate summary
        summary = self._generate_summary(agreements, disagreements, responses)

        return ComparisonResult(
            task_id=task_id,
            query=query,
            agreements=agreements,
            disagreements=disagreements,
            summary=summary,
            overall_agreement=overall,
        )

    def _extract_keywords(self, text: str) -> set[str]:
        """Extract meaningful keywords from text."""
        # Remove common stop words
        stop_words = {
            '的', '是', '在', '了', '和', '也', '就', '都', '而', '及',
            '与', '或', '一个', '没有', '我们', '你', '我', '他', '她',
            'the', 'is', 'and', 'or', 'but', 'in', 'on', 'at', 'to',
            'a', 'an', 'of', 'for', 'it', 'this', 'that', 'with',
        }

        # Extract words (simple split for CJK)
        words = re.findall(r'[一-鿿]{2,}|[a-zA-Z]{3,}', text)
        keywords = {w.lower() for w in words if w.lower() not in stop_words and len(w) >= 2}

        # Return top 20 keywords
        return set(list(keywords)[:20])

    def _has_contradiction(self, text1: str, text2: str) -> bool:
        """Simple contradiction detection."""
        contradictions = [
            ('推荐', '不推荐'), ('适合', '不适合'), ('应该', '不应该'),
            ('好', '不好'), ('优', '劣'), ('是', '不是'),
        ]
        t1_lower = text1[:200].lower()
        t2_lower = text2[:200].lower()

        for pos, neg in contradictions:
            if pos in t1_lower and neg in t2_lower:
                return True
            if neg in t1_lower and pos in t2_lower:
                return True
        return False

    def _generate_summary(
        self,
        agreements: list[Agreement],
        disagreements: list[Disagreement],
        responses: list[AIResponse],
    ) -> str:
        parts = []
        parts.append(f"共收到 {len(responses)} 个AI的回复。")

        if agreements:
            parts.append(f"发现 {len(agreements)} 个共识点。")
        if disagreements:
            parts.append(f"发现 {len(disagreements)} 个分歧点。")

        if agreements and not disagreements:
            parts.append("所有AI观点高度一致。")
        elif disagreements:
            parts.append("存在不同观点，建议综合考虑。")

        return " ".join(parts)
```

---

# FILE: backend/engine/comparison/result.py

```
"""Comparison result models."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Agreement:
    """A point of agreement between multiple AIs."""
    topic: str
    description: str
    supporting_providers: list[str] = field(default_factory=list)
    confidence: float = 0.0  # 0-1


@dataclass
class Disagreement:
    """A point of disagreement between AIs."""
    topic: str
    positions: list[dict] = field(default_factory=list)  # [{provider_id, stance, reasoning}]
    severity: float = 0.0  # 0-1


@dataclass
class ComparisonResult:
    """Result of comparing multiple AI responses."""
    task_id: str
    query: str
    agreements: list[Agreement] = field(default_factory=list)
    disagreements: list[Disagreement] = field(default_factory=list)
    summary: str = ""
    overall_agreement: float = 0.0  # 0-1

    @property
    def has_agreements(self) -> bool:
        return len(self.agreements) > 0

    @property
    def has_disagreements(self) -> bool:
        return len(self.disagreements) > 0

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "query": self.query,
            "agreements": [
                {
                    "topic": a.topic,
                    "description": a.description,
                    "supporting_providers": a.supporting_providers,
                    "confidence": a.confidence,
                }
                for a in self.agreements
            ],
            "disagreements": [
                {
                    "topic": d.topic,
                    "positions": d.positions,
                    "severity": d.severity,
                }
                for d in self.disagreements
            ],
            "summary": self.summary,
            "overall_agreement": self.overall_agreement,
        }
```

---

# FILE: backend/engine/scheduler/__init__.py

```
"""Scheduler — unified task dispatch for multi-AI queries."""
from .task import CouncilTask, TaskStatus
from .scheduler import Scheduler
```

---

# FILE: backend/engine/scheduler/scheduler.py

```
"""Scheduler — dispatches tasks to providers."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable

from .task import CouncilTask, TaskStatus

logger = logging.getLogger(__name__)


class Scheduler:
    """Dispatches CouncilTasks to AI providers.

    Supports:
    - Parallel execution (asyncio.gather)
    - Per-task timeout
    - Progress callbacks
    - Cancellation
    """

    def __init__(self, max_concurrent: int = 5):
        self._max_concurrent = max_concurrent
        self._tasks: dict[str, CouncilTask] = {}
        self._cancel_events: dict[str, asyncio.Event] = {}
        self._semaphore = asyncio.Semaphore(max_concurrent)

    def get_task(self, task_id: str) -> CouncilTask | None:
        return self._tasks.get(task_id)

    def get_all_tasks(self) -> list[CouncilTask]:
        return list(self._tasks.values())

    async def submit(
        self,
        query: str,
        provider_ids: list[str],
        send_fn: Callable[[str, str], Any],
        on_progress: Callable[[str, int, int], Any] | None = None,
        timeout_ms: int = 120000,
    ) -> CouncilTask:
        """Submit a query to multiple providers.

        Args:
            query: The user's question
            provider_ids: List of provider IDs to query
            send_fn: async function(provider_id, query) -> response
            on_progress: optional callback(task_id, completed, total)
            timeout_ms: timeout per provider
        """
        task = CouncilTask(
            query=query,
            provider_ids=provider_ids,
            status=TaskStatus.RUNNING,
            timeout_ms=timeout_ms,
        )
        self._tasks[task.task_id] = task
        self._cancel_events[task.task_id] = asyncio.Event()

        logger.info("Task %s: dispatching to %s", task.task_id, provider_ids)

        # Execute in background
        asyncio.create_task(
            self._execute(task, send_fn, on_progress)
        )

        return task

    async def _execute(
        self,
        task: CouncilTask,
        send_fn: Callable,
        on_progress: Callable | None,
    ) -> None:
        """Execute task across all providers in parallel."""
        cancel = self._cancel_events.get(task.task_id)

        async def _send_one(provider_id: str):
            if cancel and cancel.is_set():
                task.mark_failed(provider_id, "Cancelled")
                return

            await self._semaphore.acquire()
            try:
                response = await asyncio.wait_for(
                    send_fn(provider_id, task.query),
                    timeout=task.timeout_ms / 1000,
                )
                task.mark_completed(provider_id, response)
            except asyncio.TimeoutError:
                task.mark_failed(provider_id, "Timeout")
            except Exception as e:
                task.mark_failed(provider_id, str(e))
            finally:
                self._semaphore.release()

            if on_progress:
                on_progress(task.task_id, task.completed_count, task.total_count)

        # Parallel execution
        await asyncio.gather(
            *[_send_one(pid) for pid in task.provider_ids],
            return_exceptions=True,
        )

        logger.info(
            "Task %s: completed (%d/%d success)",
            task.task_id, task.completed_count, task.total_count,
        )

    def cancel_task(self, task_id: str) -> None:
        """Cancel a running task."""
        task = self._tasks.get(task_id)
        if task:
            task.cancel()
        cancel = self._cancel_events.get(task_id)
        if cancel:
            cancel.set()
```

---

# FILE: backend/engine/scheduler/task.py

```
"""Council task model."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TaskStatus(str, Enum):
    PENDING = "pending"
    DISPATCHED = "dispatched"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class CouncilTask:
    """A task representing a query sent to multiple AI providers."""
    task_id: str = field(default_factory=lambda: f"task_{uuid.uuid4().hex[:12]}")
    query: str = ""
    provider_ids: list[str] = field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    created_at: float = field(default_factory=lambda: __import__('time').time())
    updated_at: float = field(default_factory=lambda: __import__('time').time())
    timeout_ms: int = 120000
    priority: int = 0

    # Results
    results: dict[str, Any] = field(default_factory=dict)  # provider_id -> AIResponse
    errors: dict[str, str] = field(default_factory=dict)    # provider_id -> error message

    @property
    def completed_count(self) -> int:
        return len(self.results)

    @property
    def failed_count(self) -> int:
        return len(self.errors)

    @property
    def total_count(self) -> int:
        return len(self.provider_ids)

    @property
    def is_complete(self) -> bool:
        return self.completed_count + self.failed_count >= self.total_count

    def mark_completed(self, provider_id: str, result: Any) -> None:
        self.results[provider_id] = result
        self.updated_at = __import__('time').time()
        if self.is_complete:
            self.status = TaskStatus.COMPLETED if self.failed_count == 0 else TaskStatus.PARTIAL

    def mark_failed(self, provider_id: str, error: str) -> None:
        self.errors[provider_id] = error
        self.updated_at = __import__('time').time()
        if self.is_complete:
            self.status = TaskStatus.COMPLETED if self.completed_count > 0 else TaskStatus.FAILED

    def cancel(self) -> None:
        self.status = TaskStatus.CANCELLED
        self.updated_at = __import__('time').time()
```

---

# FILE: backend/shared/__init__.py

```
"""Shared utilities across all layers."""
```

---

# FILE: backend/shared/config.py

```
"""Global configuration loader."""

from __future__ import annotations

import yaml
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any


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


def load_config(config_path: str | Path | None = None) -> AppConfig:
    """Load configuration from YAML file, falling back to defaults."""
    if config_path is None:
        config_path = Path(__file__).parent.parent / "config" / "default.yaml"

    config_path = Path(config_path)
    if not config_path.exists():
        return AppConfig()

    with open(config_path, "r", encoding="utf-8") as f:
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
```

---

# FILE: backend/shared/errors.py

```
"""Unified error types for OmniCouncil."""

from __future__ import annotations


class OmniCouncilError(Exception):
    """Base exception for all OmniCouncil errors."""

    def __init__(self, code: str, message: str, recoverable: bool = False) -> None:
        self.code = code
        self.message = message
        self.recoverable = recoverable
        super().__init__(f"[{code}] {message}")


# ========== Layer 1 Errors ==========

class AIAdapterError(OmniCouncilError):
    """Error from AI adapter operations."""
    pass


class AIConnectionError(AIAdapterError):
    """Failed to connect to AI website."""

    def __init__(self, ai_id: str, message: str) -> None:
        super().__init__("AI_CONNECTION_ERROR", f"{ai_id}: {message}", recoverable=True)


class AITimeoutError(AIAdapterError):
    """AI response timed out."""

    def __init__(self, ai_id: str, timeout_ms: int) -> None:
        super().__init__("AI_TIMEOUT", f"{ai_id}: timed out after {timeout_ms}ms", recoverable=True)


class AILoginRequiredError(AIAdapterError):
    """AI website requires login."""

    def __init__(self, ai_id: str) -> None:
        super().__init__("LOGIN_REQUIRED", f"{ai_id}: login required", recoverable=False)


class AICaptchaError(AIAdapterError):
    """AI website shows captcha."""

    def __init__(self, ai_id: str) -> None:
        super().__init__("CAPTCHA_REQUIRED", f"{ai_id}: captcha detected", recoverable=True)


class CircuitOpenError(AIAdapterError):
    """Circuit breaker is open."""

    def __init__(self, ai_id: str) -> None:
        super().__init__("CIRCUIT_OPEN", f"{ai_id}: circuit breaker is open", recoverable=True)


class RateLimitError(AIAdapterError):
    """Rate limit exceeded."""

    def __init__(self, ai_id: str) -> None:
        super().__init__("RATE_LIMITED", f"{ai_id}: rate limit exceeded", recoverable=True)


class SelectorError(AIAdapterError):
    """All selector fallbacks failed."""

    def __init__(self, ai_id: str, element: str) -> None:
        super().__init__("SELECTOR_ALL_FAILED", f"{ai_id}: could not find {element}", recoverable=False)


# ========== Layer 2 Errors ==========

class SchedulerError(OmniCouncilError):
    """Error from scheduler operations."""
    pass


class TaskValidationError(SchedulerError):
    """Invalid task request."""

    def __init__(self, message: str) -> None:
        super().__init__("TASK_VALIDATION_ERROR", message, recoverable=False)


class NoAvailableAIError(SchedulerError):
    """No AI available for the request."""

    def __init__(self) -> None:
        super().__init__("NO_AVAILABLE_AI", "No AI available", recoverable=False)


# ========== Layer 3 Errors ==========

class CollectorError(OmniCouncilError):
    """Error from result collector."""
    pass


class CollectionTimeoutError(CollectorError):
    """Collection timed out."""

    def __init__(self, task_id: str) -> None:
        super().__init__("COLLECTION_TIMEOUT", f"Task {task_id}: collection timed out", recoverable=True)


# ========== Layer 4 Errors ==========

class AnalysisError(OmniCouncilError):
    """Error from comparison analysis."""
    pass


class InsufficientResultsError(AnalysisError):
    """Not enough AI results for analysis."""

    def __init__(self, success_count: int, min_required: int) -> None:
        super().__init__(
            "INSUFFICIENT_RESULTS",
            f"Need at least {min_required} successful results, got {success_count}",
            recoverable=False,
        )
```

---

# FILE: backend/shared/event_bus.py

```
"""Global singleton EventBus for inter-layer communication.

All layers share this single instance. Events are dispatched asynchronously.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)

# Type alias for event handlers
EventHandler = Callable[..., Coroutine[Any, Any, None] | None]


class EventBus:
    """Singleton event bus for decoupled inter-layer communication."""

    _instance: EventBus | None = None

    def __new__(cls) -> EventBus:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._handlers = defaultdict(list)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)
        self._initialized = True

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton (for testing)."""
        if cls._instance is not None:
            cls._instance._handlers.clear()
            cls._instance._initialized = False
        cls._instance = None

    def on(self, event: str, handler: EventHandler) -> None:
        """Register an event handler."""
        self._handlers[event].append(handler)
        logger.debug("Registered handler for event '%s': %s", event, handler.__qualname__)

    def off(self, event: str, handler: EventHandler) -> None:
        """Unregister an event handler."""
        try:
            self._handlers[event].remove(handler)
        except ValueError:
            logger.warning("Handler %s not found for event '%s'", handler.__qualname__, event)

    async def emit(self, event: str, **kwargs: Any) -> None:
        """Emit an event, calling all registered handlers.

        Handlers that are coroutines are awaited; regular functions are called directly.
        Errors in individual handlers are logged but do not propagate.
        """
        handlers = self._handlers.get(event, [])
        if not handlers:
            logger.debug("No handlers for event '%s'", event)
            return

        logger.debug("Emitting event '%s' to %d handler(s)", event, len(handlers))

        for handler in handlers:
            try:
                result = handler(**kwargs)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.exception("Error in handler %s for event '%s'", handler.__qualname__, event)

    def emit_sync(self, event: str, **kwargs: Any) -> None:
        """Emit an event synchronously (for non-async contexts).

        Only calls non-coroutine handlers.
        """
        handlers = self._handlers.get(event, [])
        for handler in handlers:
            try:
                result = handler(**kwargs)
                if asyncio.iscoroutine(result):
                    # Can't await in sync context; schedule it
                    logger.warning("Skipping async handler %s in sync emit", handler.__qualname__)
                    continue
            except Exception:
                logger.exception("Error in handler %s for event '%s'", handler.__qualname__, event)

    @property
    def registered_events(self) -> list[str]:
        """List all events with registered handlers."""
        return list(self._handlers.keys())
```

---

# FILE: backend/shared/types.py

```
"""Core data types for OmniCouncil layers 1-4.

All types are immutable dataclasses (frozen=True) following the project's
immutability principle.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ========== Layer 1: AI Access Layer ==========

class AIStatus(str, Enum):
    INITIALIZING = "initializing"
    READY = "ready"
    BUSY = "busy"
    LOGIN_REQUIRED = "login_required"
    CAPTCHA_REQUIRED = "captcha_required"
    ERROR = "error"
    RATE_LIMITED = "rate_limited"
    CIRCUIT_OPEN = "circuit_open"


class CircuitState(str, Enum):
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Tripped, rejecting requests
    HALF_OPEN = "half_open"  # Testing recovery


@dataclass(frozen=True)
class ProviderStatus:
    ai_id: str
    ai_name: str
    status: AIStatus = AIStatus.INITIALIZING
    last_check_at: float = 0.0
    consecutive_failures: int = 0


@dataclass(frozen=True)
class AIResponse:
    success: bool
    ai_id: str
    task_id: str
    content: str
    model: str = ""
    timestamp: float = 0.0
    duration: float = 0.0
    word_count: int = 0
    has_code_block: bool = False
    has_table: bool = False
    is_truncated: bool = False
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class NormalizedResponse:
    """Standardized AI response after normalization."""
    main_text: str
    code_blocks: list[tuple[str, str]] = field(default_factory=list)  # (language, code)
    paragraphs: list[str] = field(default_factory=list)
    word_count: int = 0
    detected_language: str | None = None
    has_markdown: bool = False


@dataclass(frozen=True)
class SubmitOptions:
    timeout_ms: int = 120000
    retry_count: int = 2
    on_stream_chunk: Any = None  # Optional callback


# ========== Layer 2: Scheduler ==========

class TaskMode(str, Enum):
    PARALLEL = "parallel"
    SEQUENTIAL = "sequential"


class TaskStatus(str, Enum):
    CREATED = "created"
    DISPATCHED = "dispatched"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"
    CANCELLED = "cancelled"


class SubTaskStatus(str, Enum):
    QUEUED = "queued"
    DISPATCHING = "dispatching"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class TaskProgress:
    total_ais: int = 0
    completed_ais: int = 0
    failed_ais: int = 0


@dataclass(frozen=True)
class TaskStatusInfo:
    task_id: str
    status: TaskStatus = TaskStatus.CREATED
    progress: TaskProgress = field(default_factory=TaskProgress)
    created_at: float = 0.0
    updated_at: float = 0.0


@dataclass(frozen=True)
class QueryRequest:
    query: str
    selected_ai_ids: list[str]
    mode: TaskMode = TaskMode.PARALLEL
    timeout_ms: int = 120000
    priority: int = 0


@dataclass(frozen=True)
class TaskHandle:
    task_id: str
    status: TaskStatus = TaskStatus.CREATED
    created_at: float = 0.0


@dataclass(frozen=True)
class AIAvailability:
    available: list[tuple[str, str]] = field(default_factory=list)  # (ai_id, ai_name)
    unavailable: list[tuple[str, str]] = field(default_factory=list)  # (ai_id, reason)
    mode: str = "strict"


# ========== Layer 3: Result Collection ==========

class ResultStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class AiResult:
    ai_id: str
    task_id: str
    round_number: int
    status: ResultStatus
    raw_text: str
    normalized: NormalizedResponse
    start_time: float = 0.0
    end_time: float = 0.0
    duration: float = 0.0
    error: str | None = None
    prompt_used: str = ""
    model: str = ""


@dataclass(frozen=True)
class RoundContextSummary:
    total_ais: int = 0
    success_count: int = 0
    failure_count: int = 0
    timeout_count: int = 0
    completed_at: float = 0.0


@dataclass(frozen=True)
class RoundContext:
    task_id: str
    round_number: int
    query: str
    execution_mode: TaskMode
    results: list[AiResult]
    summary: RoundContextSummary = field(default_factory=RoundContextSummary)
    created_at: float = 0.0


@dataclass(frozen=True)
class CollectorProgress:
    task_id: str
    completed_count: int
    total_count: int
    percentage: float
    latest_ai_id: str = ""
    latest_status: str = ""


# ========== Layer 4: Comparison Analysis ==========

@dataclass(frozen=True)
class SemanticUnit:
    unit_id: str
    source_ai_id: str
    content: str
    paragraph_index: int = 0
    unit_type: str = "paragraph"


@dataclass(frozen=True)
class SimilarityMatrix:
    ai_ids: list[str] = field(default_factory=list)
    pairwise_similarities: list[list[float]] = field(default_factory=list)
    unit_matrix: list[list[float]] = field(default_factory=list)
    unit_index: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DifferenceItem:
    id: str
    dimension: str
    involved_ais: list[tuple[str, str]] = field(default_factory=list)  # (ai_id, stance)
    strength: float = 0.0
    diff_type: str = "evaluative"
    related_unit_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class UniqueInsight:
    unit_id: str
    ai_id: str
    content: str
    novelty_score: float = 0.0
    potential_importance: str = "low"


@dataclass(frozen=True)
class ComparisonMetrics:
    total_units: int = 0
    overall_divergence: float = 0.0
    pairwise_similarities: list[tuple[str, str, float]] = field(default_factory=list)
    top_difference_dimension: str = ""


@dataclass(frozen=True)
class ComparisonContext:
    task_id: str
    round_number: int
    query: str
    source_context_id: str
    generated_at: float = 0.0
    participant_ais: list[tuple[str, int]] = field(default_factory=list)  # (ai_id, unit_count)
    semantic_units: list[SemanticUnit] = field(default_factory=list)
    similarity_matrix: SimilarityMatrix = field(default_factory=SimilarityMatrix)
    differences: list[DifferenceItem] = field(default_factory=list)
    unique_insights: list[UniqueInsight] = field(default_factory=list)
    metrics: ComparisonMetrics = field(default_factory=ComparisonMetrics)
    degraded: str | None = None


# ========== Utility ==========

def generate_id(prefix: str = "id") -> str:
    """Generate a unique ID with a prefix."""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"
```

---

# FILE: backend/storage/__init__.py

```
"""Local storage for session history."""
```

---

# FILE: backend/storage/local.py

```
"""Local JSON storage for session history."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class LocalStorage:
    """Local JSON file storage for session history.

    Stores sessions as individual JSON files in ~/.omnicouncil/sessions/.
    """

    def __init__(self, base_dir: str | None = None):
        self._base_dir = Path(base_dir) if base_dir else Path.home() / ".omnicouncil"
        self._sessions_dir = self._base_dir / "sessions"
        self._sessions_dir.mkdir(parents=True, exist_ok=True)

    def save_session(self, session: dict[str, Any]) -> str:
        """Save a session and return its ID."""
        session_id = session.get("task_id", f"session_{int(time.time())}")
        session["saved_at"] = time.time()

        path = self._sessions_dir / f"{session_id}.json"
        path.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Saved session %s", session_id)
        return session_id

    def load_session(self, session_id: str) -> dict[str, Any] | None:
        """Load a session by ID."""
        path = self._sessions_dir / f"{session_id}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error("Failed to load session %s: %s", session_id, e)
            return None

    def list_sessions(self, limit: int = 50) -> list[dict[str, Any]]:
        """List recent sessions, sorted by date descending."""
        sessions = []
        for path in sorted(self._sessions_dir.glob("*.json"), reverse=True)[:limit]:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                # Return summary only
                sessions.append({
                    "task_id": data.get("task_id", path.stem),
                    "query": data.get("query", ""),
                    "ai_ids": data.get("ai_ids", []),
                    "completed_at": data.get("completed_at", 0),
                    "saved_at": data.get("saved_at", 0),
                    "summary": {
                        "total_ais": data.get("summary", {}).get("total_ais", 0),
                        "success_count": data.get("summary", {}).get("success_count", 0),
                        "consensus_count": data.get("consensus_count", 0),
                        "conflict_count": data.get("conflict_count", 0),
                    },
                })
            except Exception as e:
                logger.warning("Failed to read session %s: %s", path.stem, e)
        return sessions

    def delete_session(self, session_id: str) -> bool:
        """Delete a session by ID."""
        path = self._sessions_dir / f"{session_id}.json"
        if path.exists():
            path.unlink()
            logger.info("Deleted session %s", session_id)
            return True
        return False

    def clear_all(self) -> int:
        """Delete all sessions. Returns count of deleted files."""
        count = 0
        for path in self._sessions_dir.glob("*.json"):
            path.unlink()
            count += 1
        logger.info("Cleared %d sessions", count)
        return count
```

---

# FILE: backend/tests/__init__.py

```
```

---

# FILE: backend/tests/test_browser_engine.py

```
"""Tests for BrowserEngine abstraction layer."""

import pytest
from browser.engine import EngineMode, AuthStatus, EngineStatus, PageInfo
from browser.cdp_engine import CDPEngine
from browser.embedded_engine import EmbeddedEngine
from browser.factory import create_engine


class TestBrowserEngine:
    """Test browser engine factory and base functionality."""

    def test_create_cdp_engine(self):
        engine = create_engine("cdp")
        assert isinstance(engine, CDPEngine)
        assert engine.mode == EngineMode.CDP

    def test_create_embedded_engine(self):
        engine = create_engine("embedded")
        assert isinstance(engine, EmbeddedEngine)
        assert engine.mode == EngineMode.EMBEDDED

    def test_create_engine_with_enum(self):
        engine = create_engine(EngineMode.CDP)
        assert isinstance(engine, CDPEngine)


class TestCDPEngine:
    """Test CDP engine."""

    def test_initial_state(self):
        engine = CDPEngine()
        assert engine.mode == EngineMode.CDP

    @pytest.mark.asyncio
    async def test_initial_not_connected(self):
        engine = CDPEngine()
        assert await engine.is_connected() is False

    @pytest.mark.asyncio
    async def test_connect_failure(self):
        engine = CDPEngine(cdp_url="http://localhost:99999")
        result = await engine.connect()
        assert result is False

    @pytest.mark.asyncio
    async def test_disconnect(self):
        engine = CDPEngine()
        await engine.disconnect()  # Should not raise


class TestEmbeddedEngine:
    """Test embedded engine."""

    def test_initial_state(self):
        engine = EmbeddedEngine()
        assert engine.mode == EngineMode.EMBEDDED

    @pytest.mark.asyncio
    async def test_initial_not_connected(self):
        engine = EmbeddedEngine()
        assert await engine.is_connected() is False

    @pytest.mark.asyncio
    async def test_disconnect(self):
        engine = EmbeddedEngine()
        await engine.disconnect()  # Should not raise


class TestAuthStatus:
    """Test auth status enum."""

    def test_auth_status_values(self):
        assert AuthStatus.AUTHENTICATED.value == "authenticated"
        assert AuthStatus.EXPIRED.value == "expired"
        assert AuthStatus.NOT_LOGGED_IN.value == "not_logged_in"
        assert AuthStatus.CAPTCHA_REQUIRED.value == "captcha_required"


class TestEngineStatus:
    """Test engine status dataclass."""

    def test_create_status(self):
        status = EngineStatus(
            mode=EngineMode.CDP,
            connected=True,
            browser_version="1.0",
            active_pages=[],
        )
        assert status.mode == EngineMode.CDP
        assert status.connected is True
        assert len(status.active_pages) == 0

    def test_create_page_info(self):
        page = PageInfo(
            ai_id="deepseek",
            url="https://chat.deepseek.com",
            title="DeepSeek",
            is_logged_in=True,
            auth_status=AuthStatus.AUTHENTICATED,
        )
        assert page.ai_id == "deepseek"
        assert page.is_logged_in is True
```

---

# FILE: backend/tests/test_login_flow.py

```
"""Integration tests for the login flow.

These tests verify that:
1. Each AI uses its own persistent profile directory
2. Login and work share the SAME profile
3. Cookies persist across browser sessions
4. Login detection works correctly
"""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from pathlib import Path

import pytest

from browser.embedded_engine import EmbeddedEngine
from browser.engine import AuthStatus


@pytest.fixture
def temp_auth_dir():
    """Create a temporary auth directory for testing."""
    tmpdir = tempfile.mkdtemp()
    yield tmpdir
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def engine(temp_auth_dir):
    """Create an EmbeddedEngine with a temporary auth directory."""
    return EmbeddedEngine(auth_dir=temp_auth_dir, headless=True)


class TestProfileDirectories:
    """Each AI should have its own profile directory."""

    def test_profile_dir_structure(self, engine):
        """Verify profile directory is created per AI."""
        ds_dir = engine._get_profile_dir("deepseek")
        qw_dir = engine._get_profile_dir("qianwen")

        assert "deepseek_profile" in ds_dir
        assert "qianwen_profile" in qw_dir
        assert ds_dir != qw_dir

    def test_profile_dirs_created_on_demand(self, engine):
        """Profile directories should be created when needed."""
        ds_dir = Path(engine._get_profile_dir("deepseek"))
        ds_dir.mkdir(parents=True, exist_ok=True)
        assert ds_dir.exists()


class TestCookieDetection:
    """Verify cookie-based login detection."""

    def test_no_cookies_initially(self, engine):
        """No cookies before login."""
        assert engine._has_saved_cookies("deepseek") is False

    def test_detects_cookies(self, engine):
        """Should detect cookies after they're saved."""
        profile_dir = Path(engine._get_profile_dir("deepseek"))
        cookie_dir = profile_dir / "Default"
        cookie_dir.mkdir(parents=True, exist_ok=True)
        cookie_file = cookie_dir / "Cookies"
        cookie_file.write_bytes(b"fake cookie data")

        assert engine._has_saved_cookies("deepseek") is True

    def test_empty_cookies_not_detected(self, engine):
        """Empty cookie file should not count as logged in."""
        profile_dir = Path(engine._get_profile_dir("deepseek"))
        cookie_dir = profile_dir / "Default"
        cookie_dir.mkdir(parents=True, exist_ok=True)
        cookie_file = cookie_dir / "Cookies"
        cookie_file.write_bytes(b"")

        assert engine._has_saved_cookies("deepseek") is False


class TestAuthenticationState:
    """Verify authentication state management."""

    def test_initially_not_authenticated(self, engine):
        """No AI should be authenticated initially."""
        assert engine.is_authenticated("deepseek") is False
        assert engine.is_authenticated("qianwen") is False

    def test_authenticated_after_cookie_check(self, engine):
        """Should be authenticated after cookies are found."""
        # Simulate saved cookies
        profile_dir = Path(engine._get_profile_dir("deepseek"))
        cookie_dir = profile_dir / "Default"
        cookie_dir.mkdir(parents=True, exist_ok=True)
        (cookie_dir / "Cookies").write_bytes(b"fake cookies")

        # Simulate connect() which checks for saved sessions
        engine._authenticated.add("deepseek")
        assert engine.is_authenticated("deepseek") is True

    def test_authenticated_providers_list(self, engine):
        """Should list all authenticated providers."""
        engine._authenticated.add("deepseek")
        engine._authenticated.add("qianwen")

        # Use a method that checks auth
        assert engine.is_authenticated("deepseek") is True
        assert engine.is_authenticated("qianwen") is True
        assert engine.is_authenticated("gemini") is False


class TestLoginDetection:
    """Verify login detection for different AIs."""

    def test_deepseek_login_url_patterns(self, engine):
        """DeepSeek login detection based on URL."""
        # Not logged in: on sign_in page
        assert engine._is_on_ai_page("deepseek", "https://chat.deepseek.com/sign_in") is False

        # Logged in: on chat page
        assert engine._is_on_ai_page("deepseek", "https://chat.deepseek.com/") is True
        assert engine._is_on_ai_page("deepseek", "https://chat.deepseek.com/chat/123") is True

    def test_qianwen_login_url_patterns(self, engine):
        """Qianwen login detection based on URL."""
        # Logged in: on chat page
        assert engine._is_on_ai_page("qianwen", "https://qianwen.aliyun.com/chat") is True
        assert engine._is_on_ai_page("qianwen", "https://tongyi.aliyun.com/qianwen/chat") is True

        # Not on AI page
        assert engine._is_on_ai_page("qianwen", "https://example.com") is False

    def test_unknown_ai(self, engine):
        """Unknown AI should return False."""
        assert engine._is_on_ai_page("unknown", "https://example.com") is False


class TestEngineLifecycle:
    """Verify engine lifecycle management."""

    @pytest.mark.asyncio
    async def test_connect_initializes_playwright(self, engine):
        """connect() should initialize Playwright."""
        result = await engine.connect()
        assert result is True
        assert engine._playwright is not None
        assert engine._connected is True
        await engine.disconnect()

    @pytest.mark.asyncio
    async def test_disconnect_cleans_up(self, engine):
        """disconnect() should clean up all resources."""
        await engine.connect()
        await engine.disconnect()
        assert engine._connected is False
        assert engine._playwright is None

    @pytest.mark.asyncio
    async def test_is_connected_after_connect(self, engine):
        """is_connected() should return True after connect."""
        await engine.connect()
        assert await engine.is_connected() is True
        await engine.disconnect()

    @pytest.mark.asyncio
    async def test_is_not_connected_initially(self, engine):
        """is_connected() should return False initially."""
        assert await engine.is_connected() is False
```

---

# FILE: src/main.tsx

```
import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './styles/globals.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
```

---

# FILE: src/App.tsx

```
import { useState, useEffect } from 'react';
import { useWebSocket } from './hooks/useWebSocket';
import { useAppStore } from './stores/appStore';
import { useConfigStore } from './stores/configStore';
import Titlebar from './components/Titlebar';
import { QueryInput } from './components/QueryInput';
import { TabBar } from './components/TabBar';
import { ResponsesTab } from './components/ResponsesTab';
import { ComparisonTab } from './components/ComparisonTab';
import { ConsensusTab } from './components/ConsensusTab';
import { ConflictTab } from './components/ConflictTab';
import { HistoryView } from './components/HistoryView';
import { StatusBar } from './components/StatusBar';
import { AIPlatformManager } from './components/AIPlatformManager';
import { Settings } from './components/Settings';
import { ErrorToast } from './components/ErrorToast';

function App() {
  useWebSocket();

  const activeTab = useAppStore((s) => s.activeTab);
  const connectionStatus = useAppStore((s) => s.connectionStatus);
  const responses = useAppStore((s) => s.responses);
  const { isFirstLaunch, setupCompleted, completeSetup, loadConfig } = useConfigStore();
  const [showSettings, setShowSettings] = useState(false);
  const [showPlatformManager, setShowPlatformManager] = useState(false);
  const [configLoaded, setConfigLoaded] = useState(false);
  const [error, setError] = useState<{ message: string; recoverable: boolean; suggestion?: string } | null>(null);

  // Compute titlebar status
  const isRunning = Object.values(responses).some((r) => r.status === 'waiting' || r.status === 'streaming');
  const titlebarStatus = isRunning ? '分析中...' : connectionStatus === 'connected' ? '就绪' : '未连接';

  // Listen for errors from WebSocket
  useEffect(() => {
    const unsubscribe = useAppStore.subscribe((state, prevState) => {
      const responses = state.responses;
      const prevResponses = prevState.responses;
      for (const aiId of Object.keys(responses)) {
        const current = responses[aiId];
        const prev = prevResponses[aiId];
        if (current?.status === 'error' && prev?.status !== 'error') {
          setError({
            message: current.error || '未知错误',
            recoverable: true,
            suggestion: '请检查网络连接后重试',
          });
        }
      }
    });
    return unsubscribe;
  }, []);

  // Load config on mount
  useEffect(() => {
    loadConfig().then(() => setConfigLoaded(true));
  }, [loadConfig]);

  // Show AI Platform Manager on first launch
  if (configLoaded && (isFirstLaunch || !setupCompleted)) {
    return (
      <AIPlatformManager
        isSetupMode={true}
        onComplete={() => {
          completeSetup();
        }}
      />
    );
  }

  return (
    <div className="app">
      <Titlebar statusText={titlebarStatus} />
      <QueryInput />
      <TabBar />
      <div className="tab-content">
        {activeTab === 'responses' && <ResponsesTab />}
        {activeTab === 'comparison' && <ComparisonTab />}
        {activeTab === 'consensus' && <ConsensusTab />}
        {activeTab === 'conflict' && <ConflictTab />}
        {activeTab === 'history' && <HistoryView />}
      </div>
      <StatusBar />
      {showSettings && <Settings onClose={() => setShowSettings(false)} />}
      {showPlatformManager && (
        <AIPlatformManager
          isSetupMode={false}
          onComplete={() => setShowPlatformManager(false)}
        />
      )}
      {error && (
        <ErrorToast
          error={error.message}
          recoverable={error.recoverable}
          suggestion={error.suggestion}
          onRetry={() => setError(null)}
          onDismiss={() => setError(null)}
        />
      )}
    </div>
  );
}

export default App;
```

---

# FILE: src/hooks/useWebSocket.ts

```
import { useEffect, useRef, useCallback } from 'react';
import { useAppStore } from '../stores/appStore';

const WS_URL = 'ws://127.0.0.1:8765/ws';
const RECONNECT_DELAY = 2000;
const HEARTBEAT_INTERVAL = 15000;

export function useWebSocket() {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout>>();
  const heartbeatIntervalRef = useRef<ReturnType<typeof setInterval>>();

  const setConnectionStatus = useAppStore((s) => s.setConnectionStatus);
  const handleMessage = useAppStore((s) => s.handleMessage);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      console.log('[WS] Connected');
      setConnectionStatus('connected');

      // Start heartbeat
      heartbeatIntervalRef.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'ping', data: {} }));
        }
      }, HEARTBEAT_INTERVAL);
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        handleMessage(msg);
      } catch (e) {
        console.error('[WS] Failed to parse message:', e);
      }
    };

    ws.onclose = () => {
      console.log('[WS] Disconnected');
      setConnectionStatus('disconnected');
      clearInterval(heartbeatIntervalRef.current);

      // Auto reconnect
      reconnectTimeoutRef.current = setTimeout(() => {
        console.log('[WS] Reconnecting...');
        setConnectionStatus('reconnecting');
        connect();
      }, RECONNECT_DELAY);
    };

    ws.onerror = (error) => {
      console.error('[WS] Error:', error);
    };
  }, [setConnectionStatus, handleMessage]);

  const disconnect = useCallback(() => {
    clearTimeout(reconnectTimeoutRef.current);
    clearInterval(heartbeatIntervalRef.current);
    wsRef.current?.close();
    wsRef.current = null;
  }, []);

  const send = useCallback((type: string, data: Record<string, unknown> = {}) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type, data }));
    } else {
      console.warn('[WS] Not connected, cannot send');
    }
  }, []);

  useEffect(() => {
    connect();
    return () => disconnect();
  }, [connect, disconnect]);

  return { send, disconnect };
}
```

---

# FILE: src/stores/appStore.ts

```
import { create } from 'zustand';

// ========== Types ==========

export type ConnectionStatus = 'connected' | 'disconnected' | 'reconnecting';
export type AIStatus = 'idle' | 'waiting' | 'streaming' | 'completed' | 'error';
export type TabId = 'responses' | 'comparison' | 'consensus' | 'conflict' | 'review' | 'debate' | 'history';

export interface AIResponseState {
  status: AIStatus;
  content: string;
  error: string | null;
  wordCount: number | null;
  elapsedMs: number | null;
}

export interface AppState {
  // Connection
  connectionStatus: ConnectionStatus;

  // Auth status per AI
  authStatus: Record<string, { status: string; message: string }>;

  // Current task
  currentTaskId: string | null;
  query: string;
  selectedAIs: string[];

  // Per-AI responses
  responses: Record<string, AIResponseState>;

  // Analysis results
  comparison: Record<string, unknown> | null;
  consensus: Record<string, unknown> | null;
  conflict: Record<string, unknown> | null;

  // UI state
  activeTab: TabId;

  // Actions
  setConnectionStatus: (status: ConnectionStatus) => void;
  submitQuery: (query: string, aiIds: string[]) => void;
  cancelTask: () => void;
  setActiveTab: (tab: TabId) => void;
  handleMessage: (msg: { type: string; data: Record<string, unknown> }) => void;
  resetResponses: () => void;
}

// ========== Initial State ==========

const createInitialResponse = (): AIResponseState => ({
  status: 'idle',
  content: '',
  error: null,
  wordCount: null,
  elapsedMs: null,
});

// ========== Store ==========

export const useAppStore = create<AppState>((set, get) => ({
  // Initial values
  connectionStatus: 'disconnected',
  authStatus: {},
  currentTaskId: null,
  query: '',
  selectedAIs: ['deepseek', 'qianwen'],
  responses: {},
  comparison: null,
  consensus: null,
  conflict: null,
  activeTab: 'responses',

  // Actions
  setConnectionStatus: (status) => set({ connectionStatus: status }),

  submitQuery: (query, aiIds) => {
    const responses: Record<string, AIResponseState> = {};
    aiIds.forEach((id) => {
      responses[id] = { ...createInitialResponse(), status: 'waiting' };
    });

    set({
      query,
      selectedAIs: aiIds,
      responses,
      currentTaskId: null,
      comparison: null,
      consensus: null,
      conflict: null,
      activeTab: 'responses',
    });
  },

  cancelTask: () => {
    set({ currentTaskId: null });
  },

  setActiveTab: (tab) => set({ activeTab: tab }),

  resetResponses: () => {
    const responses: Record<string, AIResponseState> = {};
    get().selectedAIs.forEach((id) => {
      responses[id] = createInitialResponse();
    });
    set({ responses });
  },

  handleMessage: (msg) => {
    const { type, data } = msg;

    switch (type) {
      case 'progress':
        set({ currentTaskId: data.task_id as string });
        break;

      case 'ai_started':
        set((state) => ({
          responses: {
            ...state.responses,
            [data.ai_id as string]: {
              ...state.responses[data.ai_id as string],
              status: 'streaming',
            },
          },
        }));
        break;

      case 'token':
        set((state) => {
          const aiId = data.ai_id as string;
          const current = state.responses[aiId];
          if (!current) return state;
          return {
            responses: {
              ...state.responses,
              [aiId]: {
                ...current,
                content: current.content + (data.token as string),
                status: 'streaming',
              },
            },
          };
        });
        break;

      case 'ai_completed':
        set((state) => ({
          responses: {
            ...state.responses,
            [data.ai_id as string]: {
              status: 'completed',
              content: data.full_text as string,
              error: null,
              wordCount: data.word_count as number,
              elapsedMs: data.elapsed_ms as number,
            },
          },
        }));
        break;

      case 'ai_failed':
        set((state) => ({
          responses: {
            ...state.responses,
            [data.ai_id as string]: {
              ...state.responses[data.ai_id as string],
              status: 'error',
              error: data.error as string,
            },
          },
        }));
        break;

      case 'all_completed':
        set({ currentTaskId: data.task_id as string });
        break;

      case 'comparison_ready':
        set({ comparison: data.comparison_context as Record<string, unknown> });
        break;

      case 'consensus_ready':
        set({ consensus: data.consensus_context as Record<string, unknown> });
        break;

      case 'conflict_ready':
        set({ conflict: data.conflict_context as Record<string, unknown> });
        break;

      case 'error':
        console.error('[Backend Error]', data);
        break;

      case 'engine_status':
        console.log('[Engine] Status:', data);
        break;

      case 'task_created':
        set({ currentTaskId: data.task_id as string });
        break;

      case 'task_cancelled':
        set({ currentTaskId: null });
        break;

      case 'auth_status':
        // Login status update from backend
        console.log('[Auth]', data.ai_id, data.status, data.message);
        set((state) => ({
          authStatus: {
            ...state.authStatus,
            [data.ai_id as string]: {
              status: data.status as string,
              message: data.message as string,
            },
          },
        }));
        break;

      case 'pong':
        break;

      default:
        console.warn('[WS] Unknown message type:', type);
    }
  },
}));
```

---

# FILE: src/stores/configStore.ts

```
import { create } from 'zustand';
import { invoke } from '@tauri-apps/api/core';

export type EngineMode = 'cdp' | 'embedded';

export interface AIConfig {
  aiId: string;
  aiName: string;
  enabled: boolean;
  status: 'connected' | 'disconnected' | 'expired';
}

export interface ConfigState {
  // Setup
  isFirstLaunch: boolean;
  setupCompleted: boolean;
  engineMode: EngineMode;

  // AI configs
  ais: AIConfig[];

  // Actions
  setEngineMode: (mode: EngineMode) => void;
  completeSetup: (mode: EngineMode) => void;
  updateAIStatus: (aiId: string, status: AIConfig['status']) => void;
  toggleAI: (aiId: string) => void;
  loadConfig: () => Promise<void>;
  saveConfig: () => Promise<void>;
}

const DEFAULT_AIS: AIConfig[] = [
  { aiId: 'deepseek', aiName: 'DeepSeek', enabled: true, status: 'disconnected' },
  { aiId: 'gemini', aiName: 'Gemini', enabled: false, status: 'disconnected' },
  { aiId: 'qianwen', aiName: '千问', enabled: true, status: 'disconnected' },
];

export const useConfigStore = create<ConfigState>((set, get) => ({
  isFirstLaunch: true,
  setupCompleted: false,
  engineMode: 'embedded',
  ais: DEFAULT_AIS,

  setEngineMode: (mode) => set({ engineMode: mode }),

  completeSetup: (mode) => {
    set({
      engineMode: mode,
      setupCompleted: true,
      isFirstLaunch: false,
    });
    get().saveConfig();
  },

  updateAIStatus: (aiId, status) => {
    set((state) => ({
      ais: state.ais.map((ai) =>
        ai.aiId === aiId ? { ...ai, status } : ai
      ),
    }));
  },

  toggleAI: (aiId) => {
    set((state) => ({
      ais: state.ais.map((ai) =>
        ai.aiId === aiId ? { ...ai, enabled: !ai.enabled } : ai
      ),
    }));
    get().saveConfig();
  },

  loadConfig: async () => {
    try {
      // In Tauri, read config from filesystem
      const configStr = await invoke<string>('read_config');
      const config = JSON.parse(configStr);

      // Wait for backend to be ready (retry up to 10 times)
      let sessions: Record<string, boolean> = {};
      for (let attempt = 0; attempt < 10; attempt++) {
        try {
          const sessionRes = await fetch('http://localhost:8765/api/sessions/status');
          if (sessionRes.ok) {
            const sessionData = await sessionRes.json();
            sessions = sessionData.sessions || {};
            break;
          }
        } catch {
          await new Promise(resolve => setTimeout(resolve, 1000));
        }
      }

      // Update AI statuses: config is source of truth, backend sessions supplement
      const ais = (config.ais ?? DEFAULT_AIS).map((ai: { aiId: string; status?: string; [key: string]: unknown }) => ({
        ...ai,
        // If config says authenticated, keep it; otherwise check backend sessions
        status: ai.status === 'authenticated' ? 'authenticated' : (sessions[ai.aiId] ? 'authenticated' : 'disconnected'),
      }));

      set({
        isFirstLaunch: config.isFirstLaunch ?? true,
        // Only set setupCompleted if config explicitly says so
        setupCompleted: config.setupCompleted ?? false,
        engineMode: config.engineMode ?? 'embedded',
        ais,
      });
    } catch {
      // Config doesn't exist yet, use defaults
      set({ isFirstLaunch: true });
    }
  },

  saveConfig: async () => {
    const state = get();
    const config = {
      isFirstLaunch: state.isFirstLaunch,
      setupCompleted: state.setupCompleted,
      engineMode: state.engineMode,
      ais: state.ais,
    };
    try {
      await invoke('write_config', { content: JSON.stringify(config, null, 2) });
    } catch (e) {
      console.error('Failed to save config:', e);
    }
  },
}));
```

---

# FILE: src/components/Header.tsx

```
interface HeaderProps {
  onSettingsClick?: () => void;
}

export function Header({ onSettingsClick }: HeaderProps) {
  return (
    <header className="header">
      <div className="header-left">
        <h1 className="header-title">OmniCouncil</h1>
        <span className="header-subtitle">多AI共识决策系统</span>
      </div>
      <div className="header-right">
        <button className="settings-btn" onClick={onSettingsClick} title="设置">
          ⚙️
        </button>
      </div>
    </header>
  );
}
```

---

# FILE: src/components/QueryInput.tsx

```
import { useState } from 'react';
import { useAppStore } from '../stores/appStore';
import { useWebSocket } from '../hooks/useWebSocket';

const AVAILABLE_AIS = [
  { id: 'deepseek', name: 'DeepSeek', color: '#4f8fff' },
  { id: 'gemini', name: 'Gemini', color: '#8b5cf6' },
  { id: 'qianwen', name: '千问', color: '#f59e0b' },
];

export function QueryInput() {
  const [query, setQuery] = useState('');
  const [selectedAIs, setSelectedAIs] = useState<string[]>(['deepseek', 'qianwen']);
  const { send } = useWebSocket();
  const submitQuery = useAppStore((s) => s.submitQuery);
  const responses = useAppStore((s) => s.responses);
  const isRunning = Object.values(responses).some((r) => r.status === 'waiting' || r.status === 'streaming');

  const toggleAI = (aiId: string) => {
    setSelectedAIs((prev) =>
      prev.includes(aiId) ? prev.filter((id) => id !== aiId) : [...prev, aiId]
    );
  };

  const handleSubmit = () => {
    if (!query.trim() || selectedAIs.length === 0 || isRunning) return;
    submitQuery(query, selectedAIs);
    send('submit_query', { query, ai_ids: selectedAIs, mode: 'parallel' });
  };

  return (
    <div className="query-input">
      <textarea
        className="query-textarea"
        placeholder="输入你的问题，让多个AI共同思考..."
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleSubmit();
        }}
      />
      <div className="query-controls">
        <div className="ai-selector">
          {AVAILABLE_AIS.map((ai) => (
            <button
              key={ai.id}
              className={`ai-chip ${selectedAIs.includes(ai.id) ? 'selected' : ''}`}
              style={selectedAIs.includes(ai.id) ? { borderColor: ai.color, background: ai.color + '20' } : {}}
              onClick={() => toggleAI(ai.id)}
            >
              {ai.name}
            </button>
          ))}
        </div>
        <button
          className="submit-btn"
          onClick={handleSubmit}
          disabled={!query.trim() || selectedAIs.length === 0 || isRunning}
        >
          {isRunning ? '⏳ 分析中...' : '🚀 开始分析'}
        </button>
      </div>
    </div>
  );
}
```

---

# FILE: src/components/TabBar.tsx

```
import { useAppStore, TabId } from '../stores/appStore';

interface TabDef {
  id: TabId;
  label: string;
  requires: TabId | null; // null = always available
}

const TABS: TabDef[] = [
  { id: 'responses', label: 'AI回复', requires: null },
  { id: 'comparison', label: '对比分析', requires: 'responses' },
  { id: 'consensus', label: '共识分析', requires: 'comparison' },
  { id: 'conflict', label: '冲突分析', requires: 'comparison' },
  { id: 'history', label: '历史记录', requires: null },
];

export function TabBar() {
  const activeTab = useAppStore((s) => s.activeTab);
  const setActiveTab = useAppStore((s) => s.setActiveTab);
  const responses = useAppStore((s) => s.responses);
  const comparison = useAppStore((s) => s.comparison);
  const consensus = useAppStore((s) => s.consensus);
  const conflict = useAppStore((s) => s.conflict);

  const total = Object.keys(responses).length;
  const completed = Object.values(responses).filter((r) => r.status === 'completed').length;
  const isRunning = Object.values(responses).some((r) => r.status === 'waiting' || r.status === 'streaming');

  const isTabEnabled = (tab: TabDef): boolean => {
    if (!tab.requires) return true;
    switch (tab.requires) {
      case 'responses':
        return completed > 0;
      case 'comparison':
        return comparison !== null;
      default:
        return true;
    }
  };

  const getBadge = (tab: TabDef): string | null => {
    switch (tab.id) {
      case 'responses':
        if (isRunning) return `${completed}/${total}`;
        if (completed > 0) return '✅';
        return null;
      case 'comparison':
        return comparison ? '✅' : null;
      case 'consensus':
        return consensus ? '✅' : null;
      case 'conflict':
        return conflict ? '⚠️' : null;
      default:
        return null;
    }
  };

  return (
    <div className="tab-bar">
      {TABS.map((tab) => {
        const enabled = isTabEnabled(tab);
        const badge = getBadge(tab);
        return (
          <button
            key={tab.id}
            className={`tab-btn ${activeTab === tab.id ? 'active' : ''} ${!enabled ? 'disabled' : ''}`}
            onClick={() => enabled && setActiveTab(tab.id)}
            disabled={!enabled}
            title={!enabled ? '请先完成前置步骤' : ''}
          >
            {tab.label}
            {badge && <span className="tab-badge">{badge}</span>}
          </button>
        );
      })}
    </div>
  );
}
```

---

# FILE: src/components/ResponsesTab.tsx

```
import { useState } from 'react';
import { useAppStore, AIResponseState } from '../stores/appStore';
import { useWebSocket } from '../hooks/useWebSocket';
import ReactMarkdown from 'react-markdown';

const STATUS_ICONS: Record<string, string> = {
  idle: '⚪',
  waiting: '🔄',
  streaming: '⏳',
  completed: '✅',
  error: '❌',
};

const STATUS_LABELS: Record<string, string> = {
  idle: '空闲',
  waiting: '等待中',
  streaming: '生成中...',
  completed: '已完成',
  error: '失败',
};

const AI_COLORS: Record<string, string> = {
  deepseek: '#4F8FFF',
  gemini: '#A78BFA',
  qianwen: '#F59E0B',
};

const AI_NAMES: Record<string, string> = {
  deepseek: 'DeepSeek',
  gemini: 'Gemini',
  qianwen: '千问',
};

function ResponseCard({ aiId, response, onRetry }: { aiId: string; response: AIResponseState; onRetry?: () => void }) {
  const [expanded, setExpanded] = useState(false);
  const color = AI_COLORS[aiId] || '#6366f1';
  const name = AI_NAMES[aiId] || aiId.toUpperCase();
  const contentLength = response.content.length;
  const shouldTruncate = contentLength > 500 && !expanded;

  return (
    <div className="response-card" style={{ borderTopColor: color }}>
      <div className="card-header">
        <div className="card-header-left">
          <span className="card-ai-name" style={{ color }}>
            🤖 {name}
          </span>
          <span className={`card-status status-${response.status}`}>
            {STATUS_ICONS[response.status]} {STATUS_LABELS[response.status]}
          </span>
        </div>
        <div className="card-header-right">
          {response.wordCount && <span className="card-meta">{response.wordCount}字</span>}
          {response.elapsedMs && <span className="card-meta">{(response.elapsedMs / 1000).toFixed(1)}秒</span>}
        </div>
      </div>

      <div className={`card-content ${shouldTruncate ? 'truncated' : ''}`}>
        {response.status === 'idle' && (
          <div className="card-placeholder">
            <span className="placeholder-text">等待发送...</span>
          </div>
        )}

        {response.status === 'waiting' && (
          <div className="card-placeholder">
            <div className="pulse-loader">
              <div className="pulse-dot" style={{ background: color }} />
              <div className="pulse-dot" style={{ background: color }} />
              <div className="pulse-dot" style={{ background: color }} />
            </div>
            <span className="placeholder-text">等待AI回复...</span>
          </div>
        )}

        {response.status === 'streaming' && (
          <div className="card-streaming">
            <div className="markdown-body">
              <ReactMarkdown>{response.content || '思考中...'}</ReactMarkdown>
            </div>
            <span className="cursor" style={{ color }}>▊</span>
          </div>
        )}

        {response.status === 'completed' && (
          <div className="card-completed">
            <div className="markdown-body">
              <ReactMarkdown>{response.content}</ReactMarkdown>
            </div>
          </div>
        )}

        {response.status === 'error' && (
          <div className="card-error">
            <div className="error-icon">❌</div>
            <div className="error-message">{response.error}</div>
            <button className="retry-btn" style={{ borderColor: color }} onClick={onRetry}>
              重试
            </button>
          </div>
        )}
      </div>

      {contentLength > 500 && (
        <button className="card-expand-btn" onClick={() => setExpanded(!expanded)}>
          {expanded ? '收起 ▲' : '展开全文 ▼'}
        </button>
      )}
    </div>
  );
}

export function ResponsesTab() {
  const responses = useAppStore((s) => s.responses);
  const aiIds = Object.keys(responses);
  const { send } = useWebSocket();

  if (aiIds.length === 0) {
    return (
      <div className="empty-state">
        <div className="empty-icon">🤖</div>
        <div className="empty-title">等待提问</div>
        <div className="empty-desc">输入问题并选择AI模型，点击"开始分析"</div>
      </div>
    );
  }

  return (
    <div className="responses-grid">
      {aiIds.map((aiId) => (
        <ResponseCard
          key={aiId}
          aiId={aiId}
          response={responses[aiId]}
          onRetry={() => send('reauth', { ai_id: aiId })}
        />
      ))}
    </div>
  );
}
```

---

# FILE: src/components/ComparisonTab.tsx

```
import { useAppStore } from '../stores/appStore';

const AI_NAMES: Record<string, string> = {
  deepseek: 'DeepSeek',
  gemini: 'Gemini',
  qianwen: '千问',
};

function SimilarityBar({ aiA, aiB, similarity }: { aiA: string; aiB: string; similarity: number }) {
  const nameA = AI_NAMES[aiA] || aiA;
  const nameB = AI_NAMES[aiB] || aiB;
  const percent = Math.round(similarity * 100);
  const color = similarity > 0.7 ? '#22c55e' : similarity > 0.4 ? '#f59e0b' : '#ef4444';

  return (
    <div className="similarity-bar-item">
      <div className="similarity-label">
        <span>{nameA}</span>
        <span className="similarity-arrow">↔</span>
        <span>{nameB}</span>
      </div>
      <div className="similarity-bar-track">
        <div className="similarity-bar-fill" style={{ width: `${percent}%`, background: color }} />
      </div>
      <span className="similarity-value" style={{ color }}>{percent}%</span>
    </div>
  );
}

export function ComparisonTab() {
  const comparison = useAppStore((s) => s.comparison);

  if (!comparison) {
    return (
      <div className="empty-state">
        <div className="empty-icon">📊</div>
        <div className="empty-title">等待对比分析</div>
        <div className="empty-desc">所有AI完成后自动进行对比分析</div>
      </div>
    );
  }

  const metrics = (comparison.metrics as Record<string, unknown>) || {};
  const differences = (comparison.differences as Array<Record<string, unknown>>) || [];
  const uniqueInsights = (comparison.unique_insights as Array<Record<string, unknown>>) || [];
  const pairwiseSimilarities = (metrics.pairwise_similarities as Array<{ ai_a: string; ai_b: string; similarity: number }>) || [];

  return (
    <div className="comparison-view">
      {/* Summary */}
      <div className="comparison-summary">
        <div className="summary-card">
          <span className="summary-icon">📊</span>
          <span className="summary-text">
            语义单元: <strong>{String(metrics.total_units || 0)}</strong>
          </span>
        </div>
        <div className="summary-card">
          <span className="summary-icon">🔀</span>
          <span className="summary-text">
            分歧度: <strong>{((metrics.overall_divergence as number || 0) * 100).toFixed(1)}%</strong>
          </span>
        </div>
        <div className="summary-card">
          <span className="summary-icon">⚠️</span>
          <span className="summary-text">
            差异点: <strong>{differences.length}</strong>
          </span>
        </div>
        <div className="summary-card">
          <span className="summary-icon">💡</span>
          <span className="summary-text">
            独观点: <strong>{uniqueInsights.length}</strong>
          </span>
        </div>
      </div>

      {/* Similarity Matrix */}
      {pairwiseSimilarities.length > 0 && (
        <div className="comparison-section">
          <h3 className="section-title">🔗 相似度</h3>
          <div className="similarity-bars">
            {pairwiseSimilarities.map((sim, i) => (
              <SimilarityBar key={i} aiA={sim.ai_a} aiB={sim.ai_b} similarity={sim.similarity} />
            ))}
          </div>
        </div>
      )}

      {/* Differences */}
      {differences.length > 0 && (
        <div className="comparison-section">
          <h3 className="section-title">🔍 差异点</h3>
          <div className="difference-list">
            {differences.map((diff, i) => (
              <div key={i} className="difference-card">
                <div className="diff-header">
                  <span className="diff-dimension">{String(diff.dimension || '未知')}</span>
                  <span className="diff-strength">
                    强度: {((diff.strength as number || 0) * 100).toFixed(0)}%
                  </span>
                </div>
                <div className="diff-positions">
                  {(diff.involved_ais as Array<{ ai_id: string; stance: string }>)?.map((inv, j) => (
                    <div key={j} className="diff-position">
                      <span className="diff-ai" style={{ color: getAIColor(inv.ai_id) }}>
                        {AI_NAMES[inv.ai_id] || inv.ai_id}
                      </span>
                      <span className="diff-stance">{inv.stance}</span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Unique Insights */}
      {uniqueInsights.length > 0 && (
        <div className="comparison-section">
          <h3 className="section-title">💡 独特观点</h3>
          <div className="insight-list">
            {uniqueInsights.map((insight, i) => (
              <div key={i} className="insight-card">
                <div className="insight-header">
                  <span className="insight-ai" style={{ color: getAIColor(insight.ai_id as string) }}>
                    💎 {AI_NAMES[insight.ai_id as string] || insight.ai_id}
                  </span>
                  <span className="insight-novelty">
                    新颖度: {((insight.novelty_score as number || 0) * 100).toFixed(0)}%
                  </span>
                </div>
                <div className="insight-content">{String(insight.content || '')}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* No findings */}
      {differences.length === 0 && uniqueInsights.length === 0 && (
        <div className="comparison-section">
          <div className="no-findings">
            🎉 所有AI的回答高度一致，没有发现显著差异或独特观点。
          </div>
        </div>
      )}
    </div>
  );
}

function getAIColor(aiId: string): string {
  const colors: Record<string, string> = {
    deepseek: '#4f8fff',
    gemini: '#8b5cf6',
    qianwen: '#f59e0b',
  };
  return colors[aiId] || '#6366f1';
}
```

---

# FILE: src/components/ConsensusTab.tsx

```
import { useState } from 'react';
import { useAppStore } from '../stores/appStore';

const AI_NAMES: Record<string, string> = {
  deepseek: 'DeepSeek',
  gemini: 'Gemini',
  qianwen: '千问',
};

function ConsensusPointCard({ point }: { point: Record<string, unknown> }) {
  const [expanded, setExpanded] = useState(false);
  const confidence = String(point.confidence || 'low');
  const confidenceColor = confidence === 'high' ? '#22c55e' : confidence === 'medium' ? '#f59e0b' : '#888';
  const strength = (point.consensus_strength as number || 0) * 100;
  const coverage = (point.coverage as number || 0) * 100;
  const supportingAIs = (point.supporting_ais as string[]) || [];

  return (
    <div className="consensus-card">
      <div className="consensus-card-header" onClick={() => setExpanded(!expanded)}>
        <div className="consensus-title">
          <span className="consensus-icon">🏆</span>
          <span>{String(point.topic || '未命名共识')}</span>
        </div>
        <div className="consensus-meta">
          <span className="consensus-confidence" style={{ color: confidenceColor }}>
            {confidence.toUpperCase()}
          </span>
          <span className="consensus-expand">{expanded ? '▲' : '▼'}</span>
        </div>
      </div>

      <div className="consensus-strength-bar">
        <div className="strength-label">共识强度</div>
        <div className="strength-track">
          <div className="strength-fill" style={{ width: `${strength}%`, background: confidenceColor }} />
        </div>
        <span className="strength-value">{strength.toFixed(0)}%</span>
      </div>

      <div className="consensus-summary">
        {String(point.summary || '')}
      </div>

      <div className="consensus-support">
        <span className="support-label">支持AI:</span>
        <div className="support-ais">
          {supportingAIs.map((ai, i) => (
            <span key={i} className="support-ai" style={{ color: getAIColor(ai) }}>
              ✓ {AI_NAMES[ai] || ai}
            </span>
          ))}
        </div>
        <span className="coverage">覆盖率: {coverage.toFixed(0)}%</span>
      </div>

      {expanded && (
        <div className="consensus-details">
          <div className="consensus-distribution">
            <h4>支持分布</h4>
            <div className="distribution-grid">
              {supportingAIs.map((ai, i) => (
                <div key={i} className="distribution-item">
                  <span className="dist-ai">{AI_NAMES[ai] || ai}</span>
                  <div className="dist-bar" style={{ background: getAIColor(ai) }} />
                  <span className="dist-check">✓</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export function ConsensusTab() {
  const consensus = useAppStore((s) => s.consensus);

  if (!consensus) {
    return (
      <div className="empty-state">
        <div className="empty-icon">🤝</div>
        <div className="empty-title">等待共识分析</div>
        <div className="empty-desc">对比分析完成后自动提取共识</div>
      </div>
    );
  }

  const metrics = (consensus.metrics as Record<string, unknown>) || {};
  const consensusPoints = (consensus.consensus_points as Array<Record<string, unknown>>) || [];
  const highConfidence = consensusPoints.filter((p) => p.confidence === 'high');
  const mediumConfidence = consensusPoints.filter((p) => p.confidence === 'medium');
  const lowConfidence = consensusPoints.filter((p) => p.confidence === 'low');

  return (
    <div className="consensus-view">
      {/* Summary */}
      <div className="consensus-summary-bar">
        <div className="summary-card">
          <span className="summary-icon">🤝</span>
          <span className="summary-text">
            共识点: <strong>{consensusPoints.length}</strong>
          </span>
        </div>
        <div className="summary-card">
          <span className="summary-icon">📊</span>
          <span className="summary-text">
            全局共识指数: <strong>{((metrics.global_consensus_index as number || 0) * 100).toFixed(0)}%</strong>
          </span>
        </div>
        <div className="summary-card">
          <span className="summary-icon">📈</span>
          <span className="summary-text">
            覆盖率: <strong>{((metrics.unit_coverage_ratio as number || 0) * 100).toFixed(0)}%</strong>
          </span>
        </div>
      </div>

      {/* High Confidence */}
      {highConfidence.length > 0 && (
        <div className="consensus-section">
          <h3 className="section-title">🤝 高置信共识</h3>
          {highConfidence.map((point, i) => (
            <ConsensusPointCard key={i} point={point} />
          ))}
        </div>
      )}

      {/* Medium Confidence */}
      {mediumConfidence.length > 0 && (
        <div className="consensus-section">
          <h3 className="section-title">⚠️ 中置信共识</h3>
          {mediumConfidence.map((point, i) => (
            <ConsensusPointCard key={i} point={point} />
          ))}
        </div>
      )}

      {/* Low Confidence */}
      {lowConfidence.length > 0 && (
        <div className="consensus-section">
          <h3 className="section-title">❓ 低置信共识</h3>
          {lowConfidence.map((point, i) => (
            <ConsensusPointCard key={i} point={point} />
          ))}
        </div>
      )}

      {/* No consensus */}
      {consensusPoints.length === 0 && (
        <div className="no-findings">
          未发现共识点。各AI的回答差异较大。
        </div>
      )}
    </div>
  );
}

function getAIColor(aiId: string): string {
  const colors: Record<string, string> = {
    deepseek: '#4f8fff',
    gemini: '#8b5cf6',
    qianwen: '#f59e0b',
  };
  return colors[aiId] || '#6366f1';
}
```

---

# FILE: src/components/ConflictTab.tsx

```
import { useState } from 'react';
import { useAppStore } from '../stores/appStore';

const AI_NAMES: Record<string, string> = {
  deepseek: 'DeepSeek',
  gemini: 'Gemini',
  qianwen: '千问',
};

const SEVERITY_COLORS: Record<string, string> = {
  critical: '#ef4444',
  significant: '#f59e0b',
  minor: '#3b82f6',
  negligible: '#888',
};

const SEVERITY_ICONS: Record<string, string> = {
  critical: '🔴',
  significant: '🟡',
  minor: '🔵',
  negligible: '⚪',
};

function ConflictFocusCard({ focus }: { focus: Record<string, unknown> }) {
  const [expanded, setExpanded] = useState(false);
  const severity = String(focus.severity || 'minor');
  const severityColor = SEVERITY_COLORS[severity] || '#888';
  const severityIcon = SEVERITY_ICONS[severity] || '⚪';
  const positions = (focus.positions as Array<Record<string, unknown>>) || [];
  const involvedAIs = (focus.involved_ais as string[]) || [];
  const intensity = (focus.conflict_intensity as number || 0) * 100;
  const suggestDebate = focus.suggest_debate as boolean;

  return (
    <div className="conflict-card" style={{ borderLeftColor: severityColor }}>
      <div className="conflict-card-header" onClick={() => setExpanded(!expanded)}>
        <div className="conflict-title">
          <span>{severityIcon}</span>
          <span>{String(focus.topic || '未命名冲突')}</span>
        </div>
        <div className="conflict-meta">
          <span className="conflict-severity" style={{ color: severityColor }}>
            {severity.toUpperCase()}
          </span>
          <span className="conflict-expand">{expanded ? '▲' : '▼'}</span>
        </div>
      </div>

      <div className="conflict-intensity">
        <span className="intensity-label">冲突强度</span>
        <div className="intensity-track">
          <div className="intensity-fill" style={{ width: `${intensity}%`, background: severityColor }} />
        </div>
        <span className="intensity-value">{intensity.toFixed(0)}%</span>
      </div>

      <div className="conflict-involved">
        <span className="involved-label">涉及AI:</span>
        {involvedAIs.map((ai, i) => (
          <span key={i} className="involved-ai">
            {AI_NAMES[ai] || ai}
          </span>
        ))}
      </div>

      {suggestDebate && (
        <div className="conflict-suggestion">
          🎯 建议进入辩论
        </div>
      )}

      {expanded && (
        <div className="conflict-positions">
          <h4>立场对比</h4>
          {positions.map((pos, i) => (
            <div key={i} className="position-card">
              <div className="position-header">
                <span className="position-ai" style={{ color: getAIColor(pos.ai_id as string) }}>
                  👤 {AI_NAMES[pos.ai_id as string] || pos.ai_id}
                </span>
              </div>
              <div className="position-summary">
                {String(pos.summary || '')}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function ConflictTab() {
  const conflict = useAppStore((s) => s.conflict);

  if (!conflict) {
    return (
      <div className="empty-state">
        <div className="empty-icon">⚔️</div>
        <div className="empty-title">等待冲突分析</div>
        <div className="empty-desc">对比分析完成后自动识别冲突</div>
      </div>
    );
  }

  const metrics = (conflict.metrics as Record<string, unknown>) || {};
  const conflictFocuses = (conflict.conflict_focuses as Array<Record<string, unknown>>) || [];
  const critical = conflictFocuses.filter((f) => f.severity === 'critical');
  const significant = conflictFocuses.filter((f) => f.severity === 'significant');
  const minor = conflictFocuses.filter((f) => f.severity === 'minor');

  return (
    <div className="conflict-view">
      {/* Summary */}
      <div className="conflict-summary-bar">
        <div className="summary-card">
          <span className="summary-icon">⚔️</span>
          <span className="summary-text">
            冲突点: <strong>{conflictFocuses.length}</strong>
          </span>
        </div>
        {critical.length > 0 && (
          <div className="summary-card critical">
            <span className="summary-icon">🔴</span>
            <span className="summary-text">
              严重: <strong>{critical.length}</strong>
            </span>
          </div>
        )}
        {significant.length > 0 && (
          <div className="summary-card significant">
            <span className="summary-icon">🟡</span>
            <span className="summary-text">
              中等: <strong>{significant.length}</strong>
            </span>
          </div>
        )}
        <div className="summary-card">
          <span className="summary-icon">📊</span>
          <span className="summary-text">
            整体等级: <strong>{String(metrics.overall_conflict_level || 'none')}</strong>
          </span>
        </div>
      </div>

      {/* Critical Conflicts */}
      {critical.length > 0 && (
        <div className="conflict-section">
          <h3 className="section-title">🔴 严重冲突</h3>
          {critical.map((focus, i) => (
            <ConflictFocusCard key={i} focus={focus} />
          ))}
        </div>
      )}

      {/* Significant Conflicts */}
      {significant.length > 0 && (
        <div className="conflict-section">
          <h3 className="section-title">🟡 中等冲突</h3>
          {significant.map((focus, i) => (
            <ConflictFocusCard key={i} focus={focus} />
          ))}
        </div>
      )}

      {/* Minor Conflicts */}
      {minor.length > 0 && (
        <div className="conflict-section">
          <h3 className="section-title">🔵 轻微冲突</h3>
          {minor.map((focus, i) => (
            <ConflictFocusCard key={i} focus={focus} />
          ))}
        </div>
      )}

      {/* No conflicts */}
      {conflictFocuses.length === 0 && (
        <div className="no-findings">
          🎉 未发现冲突点。所有AI的回答高度一致。
        </div>
      )}
    </div>
  );
}

function getAIColor(aiId: string): string {
  const colors: Record<string, string> = {
    deepseek: '#4f8fff',
    gemini: '#8b5cf6',
    qianwen: '#f59e0b',
  };
  return colors[aiId] || '#6366f1';
}
```

---

# FILE: src/components/Settings.tsx

```
import { useState } from 'react';
import { useConfigStore, EngineMode } from '../stores/configStore';

type SettingsTab = 'ai' | 'engine' | 'reset' | 'about';

export function Settings({ onClose }: { onClose: () => void }) {
  const [activeTab, setActiveTab] = useState<SettingsTab>('ai');
  const { engineMode, setEngineMode, ais, toggleAI, updateAIStatus } = useConfigStore();

  return (
    <div className="settings-overlay">
      <div className="settings-window">
        <div className="settings-header">
          <h1>⚙️ 设置</h1>
          <button className="settings-close" onClick={onClose}>✕</button>
        </div>

        <div className="settings-body">
          {/* Sidebar */}
          <div className="settings-sidebar">
            <button
              className={`settings-nav ${activeTab === 'ai' ? 'active' : ''}`}
              onClick={() => setActiveTab('ai')}
            >
              🤖 AI 管理
            </button>
            <button
              className={`settings-nav ${activeTab === 'engine' ? 'active' : ''}`}
              onClick={() => setActiveTab('engine')}
            >
              🔧 引擎
            </button>
            <button
              className={`settings-nav ${activeTab === 'about' ? 'active' : ''}`}
              onClick={() => setActiveTab('about')}
            >
              ℹ️ 关于
            </button>
            <button
              className={`settings-nav ${activeTab === 'reset' ? 'active' : ''}`}
              onClick={() => setActiveTab('reset')}
            >
              🔄 向导与重置
            </button>
          </div>

          {/* Content */}
          <div className="settings-content">
            {activeTab === 'ai' && (
              <div className="settings-section">
                <h2>🤖 AI 管理</h2>
                <div className="ai-list">
                  {ais.map((ai) => (
                    <div key={ai.aiId} className="ai-item">
                      <div className="ai-info">
                        <span className="ai-name">{ai.aiName}</span>
                        <span className={`ai-status status-${ai.status}`}>
                          {ai.status === 'connected' && '✅ 已连接'}
                          {ai.status === 'disconnected' && '⚪ 未连接'}
                          {ai.status === 'expired' && '⚠️ 已过期'}
                        </span>
                      </div>
                      <div className="ai-actions">
                        <label className="toggle">
                          <input
                            type="checkbox"
                            checked={ai.enabled}
                            onChange={() => toggleAI(ai.aiId)}
                          />
                          <span className="toggle-slider" />
                        </label>
                        {ai.status === 'expired' && (
                          <button className="btn-small" onClick={() => updateAIStatus(ai.aiId, 'connected')}>
                            重新登录
                          </button>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
                <button className="btn-add-ai">+ 添加新 AI</button>
              </div>
            )}

            {activeTab === 'engine' && (
              <div className="settings-section">
                <h2>🔧 引擎设置</h2>
                <div className="setting-group">
                  <label>连接模式</label>
                  <div className="mode-options">
                    <label className="mode-option">
                      <input
                        type="radio"
                        name="engine"
                        value="cdp"
                        checked={engineMode === 'cdp'}
                        onChange={() => setEngineMode('cdp' as EngineMode)}
                      />
                      <span>🖥️ 接管本地 Chrome（推荐）</span>
                    </label>
                    <label className="mode-option">
                      <input
                        type="radio"
                        name="engine"
                        value="embedded"
                        checked={engineMode === 'embedded'}
                        onChange={() => setEngineMode('embedded' as EngineMode)}
                      />
                      <span>🔒 内嵌 Chromium</span>
                    </label>
                  </div>
                </div>
              </div>
            )}

            {activeTab === 'about' && (
              <div className="settings-section">
                <h2>ℹ️ 关于 OmniCouncil</h2>
                <div className="about-info">
                  <p><strong>版本:</strong> 0.1.0</p>
                  <p><strong>描述:</strong> 多AI共识决策操作系统</p>
                  <p><strong>架构:</strong> Tauri + Python + Playwright</p>
                </div>
              </div>
            )}

            {activeTab === 'reset' && (
              <div className="settings-section">
                <h2>🔄 向导与重置</h2>
                <div className="setting-group">
                  <p style={{ color: 'var(--text-secondary)', marginBottom: '16px', fontSize: '13px' }}>
                    如果首次设置出现问题，可以重新运行初始向导或清除所有本地状态。
                  </p>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                    <button
                      className="btn-add-ai"
                      style={{ borderColor: 'var(--accent)', color: 'var(--accent)' }}
                      onClick={() => {
                        useConfigStore.getState().completeSetup('embedded');
                        window.location.reload();
                      }}
                    >
                      🔄 重新运行初始向导
                    </button>
                    <button
                      style={{
                        padding: '10px 16px',
                        background: 'transparent',
                        border: '1px solid var(--error)',
                        borderRadius: '8px',
                        color: 'var(--error)',
                        cursor: 'pointer',
                        width: '100%',
                      }}
                      onClick={() => {
                        if (confirm('确定要清除所有本地状态吗？这将删除所有登录信息和配置。')) {
                          useConfigStore.getState().completeSetup('embedded');
                          window.location.reload();
                        }
                      }}
                    >
                      🗑️ 清除所有本地状态（恢复出厂）
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
```

---

# FILE: src/components/SetupWizard.tsx

```
import { useState, useEffect } from 'react';
import { useWebSocket } from '../hooks/useWebSocket';
import { useAppStore } from '../stores/appStore';

type EngineMode = 'cdp' | 'embedded';
type WizardStep = 'mode' | 'connect' | 'complete';

interface SetupWizardProps {
  onComplete: (mode: EngineMode) => void;
}

interface AIItem {
  aiId: string;
  aiName: string;
  color: string;
}

const AI_LIST: AIItem[] = [
  { aiId: 'deepseek', aiName: 'DeepSeek', color: '#4F8FFF' },
  { aiId: 'qianwen', aiName: '千问', color: '#F59E0B' },
];

export function SetupWizard({ onComplete }: SetupWizardProps) {
  const { send } = useWebSocket();
  const [step, setStep] = useState<WizardStep>('mode');
  const [selectedMode, setSelectedMode] = useState<EngineMode | null>(null);
  const [savedSessions, setSavedSessions] = useState<Record<string, boolean>>({});
  const authStatus = useAppStore((s) => s.authStatus);

  // Check backend for saved sessions on mount
  useEffect(() => {
    fetch('http://localhost:8765/api/sessions/status')
      .then(res => res.json())
      .then(data => {
        if (data.sessions) {
          setSavedSessions(data.sessions);
        }
      })
      .catch(() => {});
  }, []);

  const handleModeSelect = (mode: EngineMode) => {
    setSelectedMode(mode);
    setStep('connect');
  };

  const handleConnect = (aiId: string) => {
    send('reauth', { ai_id: aiId });
  };

  const getStatus = (aiId: string) => {
    // Check WebSocket auth status first
    const s = authStatus[aiId];
    if (s) {
      return {
        connected: s.status === 'authenticated',
        connecting: s.status === 'connecting',
        message: s.message,
      };
    }
    // Fall back to saved session check
    if (savedSessions[aiId]) {
      return { connected: true, connecting: false, message: '已保存登录状态' };
    }
    return { connected: false, connecting: false, message: '' };
  };

  const connectedCount = AI_LIST.filter((ai) => getStatus(ai.aiId).connected).length;

  // Step 1: Mode Selection
  if (step === 'mode') {
    return (
      <div className="setup-wizard">
        <div className="setup-container">
          <div className="setup-step">
            <div className="setup-header">
              <div className="setup-icon">🔮</div>
              <h1>欢迎使用 OmniCouncil</h1>
              <p className="setup-subtitle">
                让多个AI共同思考，而不是让你重复劳动。<br />
                首先，选择连接模式：
              </p>
            </div>

            <div className="mode-cards">
              <div className="mode-card" onClick={() => handleModeSelect('cdp')}>
                <div className="mode-icon">🖥️</div>
                <h2>接管本地 Chrome</h2>
                <div className="mode-divider" />
                <p>复用你日常使用的 Chrome 登录态，无需重复登录</p>
                <ul className="mode-features">
                  <li className="feature-good">✅ 零配置</li>
                  <li className="feature-good">✅ 自动绕过验证码</li>
                  <li className="feature-good">✅ 登录一次永久有效</li>
                  <li className="feature-warn">⚠️ 需要 Chrome 浏览器</li>
                </ul>
                <div className="mode-badge recommended">推荐</div>
              </div>

              <div className="mode-card" onClick={() => handleModeSelect('embedded')}>
                <div className="mode-icon">🔒</div>
                <h2>内嵌浏览器</h2>
                <div className="mode-divider" />
                <p>使用内置的 Chromium，首次需手动登录</p>
                <ul className="mode-features">
                  <li className="feature-good">✅ 开箱即用</li>
                  <li className="feature-good">✅ 不依赖外部 Chrome</li>
                  <li className="feature-warn">⚠️ Cookie 过期需重新登录</li>
                  <li className="feature-warn">⚠️ 风控可能弹验证码</li>
                </ul>
              </div>
            </div>

            <div className="setup-hint">
              💡 提示：如果你日常使用 Chrome 浏览器，推荐选择"接管模式"
            </div>
          </div>
        </div>
      </div>
    );
  }

  // Step 2: AI Connection
  if (step === 'connect') {
    return (
      <div className="setup-wizard">
        <div className="setup-container">
          <div className="setup-step">
            <div className="setup-header">
              <div className="setup-icon">🔗</div>
              <h1>连接 AI 账号</h1>
              <p className="setup-subtitle">
                {selectedMode === 'cdp'
                  ? '请确保 Chrome 已以调试模式启动，然后连接各 AI 账号。'
                  : '点击"连接"按钮，在弹出的浏览器窗口中登录各 AI 账号。'}
              </p>
            </div>

            <div className="login-cards">
              {AI_LIST.map((ai) => {
                const status = getStatus(ai.aiId);
                return (
                  <div key={ai.aiId} className="login-card">
                    <div className="login-header">
                      <span className="login-ai-name" style={{ color: ai.color }}>
                        {ai.aiName}
                      </span>
                      <span className={`login-status ${status.connected ? 'status-connected' : ''}`}>
                        {status.connected ? '✅ 已连接' : status.connecting ? '⏳ 连接中...' : '未连接'}
                      </span>
                    </div>

                    {!status.connected && !status.connecting && (
                      <div style={{ padding: '16px', display: 'flex', gap: '8px' }}>
                        <button className="setup-next" onClick={() => handleConnect(ai.aiId)}>
                          连接 {ai.aiName}
                        </button>
                        <button className="setup-skip" onClick={() => setStep('complete')}>
                          跳过
                        </button>
                      </div>
                    )}

                    {status.connecting && (
                      <div style={{ padding: '24px', textAlign: 'center' }}>
                        <div className="pulse-loader" style={{ justifyContent: 'center', marginBottom: '12px' }}>
                          <div className="pulse-dot" style={{ background: ai.color }} />
                          <div className="pulse-dot" style={{ background: ai.color }} />
                          <div className="pulse-dot" style={{ background: ai.color }} />
                        </div>
                        <p style={{ color: 'var(--text-secondary)', fontSize: '13px' }}>
                          {status.message || '请在弹出的浏览器窗口中完成登录...'}
                        </p>
                      </div>
                    )}

                    {status.connected && (
                      <div style={{ padding: '16px', textAlign: 'center', color: 'var(--success)', fontSize: '13px' }}>
                        ✅ 登录成功，可以使用
                      </div>
                    )}
                  </div>
                );
              })}
            </div>

            <div className="setup-privacy">
              🔒 登录信息仅保存在本地，不会上传到任何服务器
            </div>

            <div className="setup-actions">
              <button className="setup-back" onClick={() => setStep('mode')}>
                ← 返回
              </button>
              <button
                className="setup-next"
                onClick={() => setStep('complete')}
                disabled={connectedCount === 0}
              >
                {connectedCount > 0
                  ? `完成设置 → (${connectedCount} 个已连接)`
                  : '请至少连接 1 个 AI'}
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // Step 3: Complete
  return (
    <div className="setup-wizard">
      <div className="setup-container">
        <div className="setup-step">
          <div className="setup-header">
            <div className="setup-icon">🎉</div>
            <h1>设置完成！</h1>
            <p className="setup-subtitle">
              已连接 {connectedCount} 个 AI。<br />
              现在可以开始使用 OmniCouncil 了。
            </p>
          </div>

          <div style={{ textAlign: 'center', marginTop: '24px' }}>
            <button
              className="setup-next"
              style={{ padding: '14px 32px', fontSize: '16px' }}
              onClick={() => onComplete(selectedMode || 'embedded')}
            >
              进入控制台 →
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
```

---

# FILE: src/components/AIPlatformManager.tsx

```
import { useState, useEffect } from 'react';
import { useWebSocket } from '../hooks/useWebSocket';
import { useAppStore } from '../stores/appStore';

interface AIPlatform {
  aiId: string;
  aiName: string;
  color: string;
  connected: boolean;
  connecting: boolean;
  enabled: boolean;
}

interface AIPlatformManagerProps {
  onComplete: () => void;
  isSetupMode?: boolean;  // true = first launch, false = settings page
}

export function AIPlatformManager({ onComplete, isSetupMode = false }: AIPlatformManagerProps) {
  const { send } = useWebSocket();
  const authStatus = useAppStore((s) => s.authStatus);
  const [platforms, setPlatforms] = useState<AIPlatform[]>([
    { aiId: 'deepseek', aiName: 'DeepSeek', color: '#4F8FFF', connected: false, connecting: false, enabled: true },
    { aiId: 'qianwen', aiName: '千问', color: '#F59E0B', connected: false, connecting: false, enabled: true },
  ]);
  const [showAddModal, setShowAddModal] = useState(false);
  const [newName, setNewName] = useState('');
  const [newUrl, setNewUrl] = useState('');

  // Check saved sessions on mount
  useEffect(() => {
    // Method 1: Try backend API
    const checkViaApi = async () => {
      try {
        const res = await fetch('http://localhost:8765/api/sessions/status');
        if (res.ok) {
          const data = await res.json();
          if (data.sessions) {
            setPlatforms(prev => prev.map(p => ({
              ...p,
              connected: data.sessions[p.aiId] || false,
            })));
            return true;
          }
        }
      } catch {}
      return false;
    };

    // Method 2: Check config file via Tauri invoke
    const checkViaConfig = async () => {
      try {
        const { invoke } = await import('@tauri-apps/api/core');
        const configStr = await invoke<string>('read_config');
        const config = JSON.parse(configStr);
        if (config.ais) {
          setPlatforms(prev => prev.map(p => {
            const configAi = config.ais.find((a: { aiId: string }) => a.aiId === p.aiId);
            return {
              ...p,
              connected: configAi?.status === 'authenticated',
            };
          }));
        }
      } catch {}
    };

    // Try API first, fall back to config
    checkViaApi().then(ok => {
      if (!ok) checkViaConfig();
    });
  }, []);

  // Listen for auth status updates
  useEffect(() => {
    setPlatforms(prev => prev.map(p => {
      const s = authStatus[p.aiId];
      if (s) {
        return {
          ...p,
          connected: s.status === 'authenticated',
          connecting: s.status === 'connecting',
        };
      }
      return p;
    }));
  }, [authStatus]);

  const handleConnect = (aiId: string) => {
    setPlatforms(prev => prev.map(p =>
      p.aiId === aiId ? { ...p, connecting: true } : p
    ));
    send('reauth', { ai_id: aiId });
  };

  const handleDisable = (aiId: string) => {
    // Reset login state
    setPlatforms(prev => prev.map(p =>
      p.aiId === aiId ? { ...p, connected: false, enabled: false } : p
    ));
    // TODO: Call backend to clear cookies
  };

  const handleDelete = (aiId: string) => {
    setPlatforms(prev => prev.filter(p => p.aiId !== aiId));
    // TODO: Call backend to delete all data for this AI
  };

  const handleAddPlatform = () => {
    if (!newName.trim() || !newUrl.trim()) return;
    const aiId = newName.toLowerCase().replace(/\s+/g, '_');
    setPlatforms(prev => [...prev, {
      aiId,
      aiName: newName,
      color: '#6C5CE7',
      connected: false,
      connecting: false,
      enabled: true,
    }]);
    setNewName('');
    setNewUrl('');
    setShowAddModal(false);
  };

  const connectedCount = platforms.filter(p => p.connected).length;

  return (
    <div className="platform-manager">
      <div className="platform-container">
        <div className="platform-header">
          <div className="platform-icon">🤖</div>
          <h1>AI 平台管理</h1>
          <p className="platform-subtitle">
            管理你的 AI 平台连接状态。已连接的平台会保存登录状态，下次启动自动恢复。
          </p>
        </div>

        <div className="platform-grid">
          {platforms.map((platform) => (
            <div key={platform.aiId} className={`platform-card ${platform.connected ? 'connected' : 'disconnected'}`}>
              <div className="platform-card-header">
                <div className="platform-card-icon" style={{ background: platform.color }}>
                  {platform.aiName.charAt(0)}
                </div>
                <div className="platform-card-info">
                  <div className="platform-card-name">{platform.aiName}</div>
                  <div className={`platform-card-status ${platform.connected ? 'connected' : 'disconnected'}`}>
                    {platform.connected ? '✅ 已连接' : platform.connecting ? '⏳ 连接中...' : '🚫 未连接'}
                  </div>
                </div>
              </div>

              {platform.connecting && (
                <div className="platform-card-connecting">
                  <div className="pulse-loader">
                    <div className="pulse-dot" style={{ background: platform.color }} />
                    <div className="pulse-dot" style={{ background: platform.color }} />
                    <div className="pulse-dot" style={{ background: platform.color }} />
                  </div>
                  <span>请在弹出的浏览器窗口中完成登录...</span>
                </div>
              )}

              <div className="platform-card-actions">
                {!platform.connected && !platform.connecting && (
                  <button className="platform-btn connect" onClick={() => handleConnect(platform.aiId)}>
                    🔗 连接
                  </button>
                )}
                {platform.connected && (
                  <button className="platform-btn disable" onClick={() => handleDisable(platform.aiId)}>
                    ⏸️ 停用
                  </button>
                )}
                <button className="platform-btn delete" onClick={() => handleDelete(platform.aiId)}>
                  🗑️ 删除
                </button>
              </div>
            </div>
          ))}

          {/* Add Platform Card */}
          <div className="platform-card add-card" onClick={() => setShowAddModal(true)}>
            <div className="add-card-content">
              <div className="add-icon">+</div>
              <div className="add-text">新增平台</div>
            </div>
          </div>
        </div>

        {/* Add Platform Modal */}
        {showAddModal && (
          <div className="add-modal-overlay" onClick={() => setShowAddModal(false)}>
            <div className="add-modal" onClick={(e) => e.stopPropagation()}>
              <h2>添加新 AI 平台</h2>
              <div className="add-form">
                <label>
                  平台名称
                  <input
                    type="text"
                    placeholder="例如: MiMo"
                    value={newName}
                    onChange={(e) => setNewName(e.target.value)}
                  />
                </label>
                <label>
                  登录页面 URL
                  <input
                    type="text"
                    placeholder="例如: https://mimo.example.com"
                    value={newUrl}
                    onChange={(e) => setNewUrl(e.target.value)}
                  />
                </label>
              </div>
              <div className="add-actions">
                <button className="platform-btn" onClick={() => setShowAddModal(false)}>取消</button>
                <button className="platform-btn connect" onClick={handleAddPlatform}>添加</button>
              </div>
            </div>
          </div>
        )}

        {/* Footer */}
        <div className="platform-footer">
          <div className="platform-summary">
            {connectedCount > 0
              ? `✅ ${connectedCount} 个平台已连接`
              : '🚫 暂无已连接的平台'}
          </div>
          {isSetupMode ? (
            <button
              className="platform-btn connect"
              onClick={onComplete}
              disabled={connectedCount === 0}
            >
              {connectedCount > 0 ? '进入控制台 →' : '请至少连接 1 个平台'}
            </button>
          ) : (
            <button className="platform-btn" onClick={onComplete}>
              完成
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
```

---

# FILE: src/components/StatusBar.tsx

```
import { useAppStore } from '../stores/appStore';

export function StatusBar() {
  const connectionStatus = useAppStore((s) => s.connectionStatus);
  const responses = useAppStore((s) => s.responses);
  const currentTaskId = useAppStore((s) => s.currentTaskId);

  const total = Object.keys(responses).length;
  const completed = Object.values(responses).filter((r) => r.status === 'completed').length;
  const failed = Object.values(responses).filter((r) => r.status === 'error').length;
  const isRunning = Object.values(responses).some((r) => r.status === 'waiting' || r.status === 'streaming');

  const statusIcon = connectionStatus === 'connected' ? '✅' : connectionStatus === 'reconnecting' ? '🔄' : '❌';
  const statusText = connectionStatus === 'connected' ? '已连接' : connectionStatus === 'reconnecting' ? '重连中...' : '未连接';

  return (
    <footer className="status-bar">
      <span>{statusIcon} {statusText}</span>
      {total > 0 && (
        <span>
          {isRunning ? `⏳ 分析中 (${completed}/${total})` : `✅ 完成 ${completed}/${total}`}
          {failed > 0 && ` · ❌ ${failed} 失败`}
        </span>
      )}
    </footer>
  );
}
```

---

# FILE: src/components/Titlebar.tsx

```
import { useState, useEffect } from 'react';

interface TitlebarProps {
  statusText?: string;
}

export default function Titlebar({ statusText = '就绪' }: TitlebarProps) {
  const [isMaximized, setIsMaximized] = useState(false);

  useEffect(() => {
    // Listen for window resize to update maximize state
    const update = async () => {
      try {
        const { getCurrentWindow } = await import('@tauri-apps/api/window');
        const win = getCurrentWindow();
        setIsMaximized(await win.isMaximized());
      } catch {
        // Not in Tauri environment
      }
    };
    update();
    window.addEventListener('resize', update);
    return () => window.removeEventListener('resize', update);
  }, []);

  const handleMinimize = async () => {
    try {
      const { getCurrentWindow } = await import('@tauri-apps/api/window');
      await getCurrentWindow().minimize();
    } catch { /* not in tauri */ }
  };

  const handleToggleMaximize = async () => {
    try {
      const { getCurrentWindow } = await import('@tauri-apps/api/window');
      await getCurrentWindow().toggleMaximize();
    } catch { /* not in tauri */ }
  };

  const handleClose = async () => {
    try {
      const { getCurrentWindow } = await import('@tauri-apps/api/window');
      await getCurrentWindow().close();
    } catch { /* not in tauri */ }
  };

  return (
    <div
      data-tauri-drag-region
      className="titlebar"
    >
      {/* Left: Brand + Status */}
      <div className="titlebar-left" data-tauri-drag-region>
        <div className="titlebar-logo">
          <span className="titlebar-logo-text">Ω</span>
        </div>
        <span className="titlebar-brand">OMNICOUNCIL</span>
        <span className={`titlebar-status-dot ${statusText === '分析中...' ? 'pulse' : ''}`} />
        <span className="titlebar-status-text">{statusText}</span>
      </div>

      {/* Center: Drag area */}
      <div className="titlebar-center" data-tauri-drag-region onDoubleClick={handleToggleMaximize} />

      {/* Right: Window controls */}
      <div className="titlebar-controls">
        <button className="titlebar-btn" onClick={handleMinimize} title="最小化">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
            <path d="M20 12H4" />
          </svg>
        </button>
        <button className="titlebar-btn" onClick={handleToggleMaximize} title={isMaximized ? '还原' : '最大化'}>
          {isMaximized ? (
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M8 16H4V4h12v4M16 8h4v12H8v-4" />
            </svg>
          ) : (
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <rect x="4" y="4" width="16" height="16" />
            </svg>
          )}
        </button>
        <button className="titlebar-btn close" onClick={handleClose} title="关闭">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
            <path d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>
    </div>
  );
}
```

---

# FILE: src/components/ErrorToast.tsx

```
import { useEffect, useState } from 'react';

interface ErrorToastProps {
  error: string;
  recoverable: boolean;
  suggestion?: string;
  onRetry?: () => void;
  onDismiss: () => void;
  autoHideMs?: number;
}

export function ErrorToast({ error, recoverable, suggestion, onRetry, onDismiss, autoHideMs = 8000 }: ErrorToastProps) {
  const [visible, setVisible] = useState(true);

  useEffect(() => {
    const timer = setTimeout(() => {
      setVisible(false);
      setTimeout(onDismiss, 300);
    }, autoHideMs);
    return () => clearTimeout(timer);
  }, [autoHideMs, onDismiss]);

  return (
    <div className={`error-toast ${visible ? 'show' : 'hide'}`}>
      <div className="error-toast-icon">⚠️</div>
      <div className="error-toast-content">
        <div className="error-toast-message">{error}</div>
        {suggestion && <div className="error-toast-suggestion">{suggestion}</div>}
      </div>
      <div className="error-toast-actions">
        {recoverable && onRetry && (
          <button className="error-toast-btn retry" onClick={onRetry}>重试</button>
        )}
        <button className="error-toast-btn dismiss" onClick={onDismiss}>✕</button>
      </div>
    </div>
  );
}
```

---

# FILE: src/components/SkeletonLoader.tsx

```
export function SkeletonLoader() {
  return (
    <div className="skeleton-card">
      <div className="skeleton-header">
        <div className="skeleton-dot" />
        <div className="skeleton-line w-24" />
        <div className="skeleton-line w-12" />
      </div>
      <div className="skeleton-body">
        <div className="skeleton-line w-full" />
        <div className="skeleton-line w-11/12" />
        <div className="skeleton-line w-4/5" />
      </div>
      <div className="skeleton-footer">
        <div className="skeleton-line w-32" />
        <div className="skeleton-line w-20" />
      </div>
    </div>
  );
}
```

---

# FILE: src/components/HistoryView.tsx

```
import { useState } from 'react';

interface HistoryEntry {
  id: string;
  date: string;
  query: string;
  aiNames: string[];
  consensusCount: number;
  conflictCount: number;
  divergence: number;
}

const MOCK_HISTORY: HistoryEntry[] = [];

export function HistoryView() {
  const [searchQuery, setSearchQuery] = useState('');
  const history = MOCK_HISTORY; // Will be replaced with real data from backend

  const filteredHistory = history.filter(
    (entry) => entry.query.toLowerCase().includes(searchQuery.toLowerCase())
  );

  if (history.length === 0) {
    return (
      <div className="empty-state">
        <div className="empty-icon">📚</div>
        <div className="empty-title">暂无历史记录</div>
        <div className="empty-desc">完成一次分析后，历史记录会自动保存</div>
      </div>
    );
  }

  return (
    <div className="history-view">
      <div className="history-header">
        <div className="history-search">
          <input
            type="text"
            placeholder="搜索历史记录..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="history-search-input"
          />
        </div>
        <button className="history-clear-btn">清除全部</button>
      </div>

      <div className="history-list">
        {filteredHistory.map((entry) => (
          <div key={entry.id} className="history-card">
            <div className="history-date">📅 {entry.date}</div>
            <div className="history-query">💬 {entry.query}</div>
            <div className="history-ais">
              🤖 {entry.aiNames.join(' + ')}
            </div>
            <div className="history-stats">
              📊 共识: {entry.consensusCount} · 冲突: {entry.conflictCount} · 分歧: {entry.divergence}%
            </div>
            <div className="history-actions">
              <button className="history-btn">查看</button>
              <button className="history-btn">重新分析</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
```

---

# FILE: src-tauri/Cargo.toml

```
[package]
name = "omnicouncil"
version = "0.1.0"
edition = "2021"

[build-dependencies]
tauri-build = { version = "2", features = [] }

[dependencies]
tauri = { version = "2", features = ["tray-icon"] }
serde = { version = "1", features = ["derive"] }
serde_json = "1"
reqwest = { version = "0.12", default-features = false, features = ["json", "rustls-tls", "blocking"] }
tokio = { version = "1", features = ["full"] }
dirs = "5"

[features]
default = ["custom-protocol"]
custom-protocol = ["tauri/custom-protocol"]
```

---

# FILE: src-tauri/build.rs

```
fn main() {
    tauri_build::build();
}
```

---

# FILE: src-tauri/src/main.rs

```
#![windows_subsystem = "windows"]

mod python_manager;

use python_manager::PythonManager;
use std::fs;
use std::path::PathBuf;
use std::process::Command;
use std::sync::Mutex;
use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Emitter, Manager, State,
};
use serde::{Deserialize, Serialize};

struct AppState {
    python: Mutex<PythonManager>,
}

#[derive(Serialize, Deserialize)]
struct HealthStatus {
    status: String,
    python_running: bool,
    port: u16,
}

// ========== Health ==========

#[tauri::command]
fn get_health(state: State<AppState>) -> HealthStatus {
    let python = state.python.lock().unwrap();
    HealthStatus {
        status: if python.is_healthy() { "ok".to_string() } else { "error".to_string() },
        python_running: python.is_running(),
        port: python.port(),
    }
}

#[tauri::command]
fn restart_python(state: State<AppState>) -> Result<String, String> {
    let mut python = state.python.lock().unwrap();
    python.restart().map_err(|e| e.to_string())?;
    Ok("Python restarted".to_string())
}

// ========== Config Management ==========

fn get_config_dir() -> PathBuf {
    let home = dirs::home_dir().unwrap_or_else(|| PathBuf::from("."));
    home.join(".omnicouncil")
}

fn get_config_path() -> PathBuf {
    get_config_dir().join("config.json")
}

#[tauri::command]
fn read_config() -> Result<String, String> {
    let path = get_config_path();
    if path.exists() {
        fs::read_to_string(&path).map_err(|e| format!("Failed to read config: {}", e))
    } else {
        Ok("{}".to_string())
    }
}

#[tauri::command]
fn write_config(content: String) -> Result<(), String> {
    // Validate JSON before writing
    serde_json::from_str::<serde_json::Value>(&content)
        .map_err(|e| format!("Invalid JSON: {}", e))?;

    let dir = get_config_dir();
    fs::create_dir_all(&dir).map_err(|e| format!("Failed to create config dir: {}", e))?;
    let path = get_config_path();
    fs::write(&path, &content).map_err(|e| format!("Failed to write config: {}", e))
}

// ========== Chrome Launch ==========

#[tauri::command]
fn launch_chrome_debug() -> Result<String, String> {
    #[cfg(target_os = "windows")]
    {
        Command::new("cmd")
            .args(["/C", "start", "chrome", "--remote-debugging-port=9222"])
            .spawn()
            .map_err(|e| format!("Failed to launch Chrome: {}", e))?;
    }

    #[cfg(target_os = "macos")]
    {
        Command::new("open")
            .args(["-a", "Google Chrome", "--args", "--remote-debugging-port=9222"])
            .spawn()
            .map_err(|e| format!("Failed to launch Chrome: {}", e))?;
    }

    #[cfg(target_os = "linux")]
    {
        Command::new("google-chrome")
            .arg("--remote-debugging-port=9222")
            .spawn()
            .map_err(|e| format!("Failed to launch Chrome: {}", e))?;
    }

    Ok("Chrome launched with debug port 9222".to_string())
}

#[tauri::command]
fn check_chrome_connection() -> Result<bool, String> {
    match std::net::TcpStream::connect_timeout(
        &"127.0.0.1:9222".parse().unwrap(),
        std::time::Duration::from_secs(2),
    ) {
        Ok(_) => Ok(true),
        Err(_) => Ok(false),
    }
}

// ========== Main ==========

fn main() {
    tauri::Builder::default()
        .manage(AppState {
            python: Mutex::new(PythonManager::new(8765)),
        })
        .setup(|app| {
            let state = app.state::<AppState>();
            let mut python = state.python.lock().unwrap();

            // Start Python backend
            python.start().expect("Failed to start Python backend");

            // Start heartbeat monitor
            let app_handle = app.handle().clone();
            python.start_heartbeat(app_handle);

            // Show the main window
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.show();
            }

            // ========== System Tray ==========
            let show_item = MenuItem::with_id(app, "show", "显示主窗口", true, None::<&str>)?;
            let settings_item = MenuItem::with_id(app, "settings", "设置", true, None::<&str>)?;
            let restart_item = MenuItem::with_id(app, "restart", "重启服务", true, None::<&str>)?;
            let quit_item = MenuItem::with_id(app, "quit", "退出", true, None::<&str>)?;

            let menu = Menu::with_items(
                app,
                &[&show_item, &settings_item, &restart_item, &quit_item],
            )?;

            let _tray = TrayIconBuilder::new()
                .icon(app.default_window_icon().unwrap().clone())
                .menu(&menu)
                .tooltip("OmniCouncil")
                .on_menu_event(move |app, event| {
                    match event.id.as_ref() {
                        "show" => {
                            if let Some(window) = app.get_webview_window("main") {
                                let _ = window.show();
                                let _ = window.set_focus();
                            }
                        }
                        "settings" => {
                            if let Some(window) = app.get_webview_window("main") {
                                let _ = window.show();
                                let _ = window.set_focus();
                                let _ = window.emit("open-settings", ());
                            }
                        }
                        "restart" => {
                            let state = app.state::<AppState>();
                            let mut python = state.python.lock().unwrap();
                            let _ = python.restart();
                        }
                        "quit" => {
                            let state = app.state::<AppState>();
                            let mut python = state.python.lock().unwrap();
                            python.cleanup();
                            app.exit(0);
                        }
                        _ => {}
                    }
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        let app = tray.app_handle();
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.show();
                            let _ = window.set_focus();
                        }
                    }
                })
                .build(app)?;

            Ok(())
        })
        .on_window_event(|window, event| {
            // Hide to tray instead of closing
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                // Prevent default close, hide to tray instead
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .invoke_handler(tauri::generate_handler![
            get_health,
            restart_python,
            read_config,
            write_config,
            launch_chrome_debug,
            check_chrome_connection
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
```

---

# FILE: src-tauri/src/python_manager.rs

```
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant};
use std::thread;
use tauri::{AppHandle, Emitter};

pub struct PythonManager {
    port: u16,
    process: Option<Child>,
    heartbeat_failures: u32,
    last_heartbeat: Option<Instant>,
    is_healthy: bool,
}

impl PythonManager {
    pub fn new(port: u16) -> Self {
        Self {
            port,
            process: None,
            heartbeat_failures: 0,
            last_heartbeat: None,
            is_healthy: false,
        }
    }

    pub fn port(&self) -> u16 {
        self.port
    }

    pub fn is_running(&self) -> bool {
        self.process.is_some()
    }

    pub fn is_healthy(&self) -> bool {
        self.is_healthy
    }

    pub fn start(&mut self) -> Result<(), Box<dyn std::error::Error>> {
        // Kill existing process if any
        self.cleanup();

        // Start Python backend
        let python_path = self.get_python_path();
        let script_path = self.get_script_path();

        let mut cmd = Command::new(&python_path);
        cmd.arg(&script_path)
            .arg("--port")
            .arg(self.port.to_string())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());

        // Hide Python console window on Windows
        // Note: CREATE_NO_WINDOW propagates to child processes, but Playwright's
        // Chromium is launched via a separate Node.js driver process which handles
        // its own window creation.
        #[cfg(target_os = "windows")]
        {
            use std::os::windows::process::CommandExt;
            cmd.creation_flags(0x08000000); // CREATE_NO_WINDOW
        }

        let child = cmd.spawn()
            .map_err(|e| format!("Failed to start Python: {}", e))?;

        self.process = Some(child);
        self.is_healthy = true;

        // Wait for health endpoint to be ready
        self.wait_for_ready(Duration::from_secs(30))?;

        Ok(())
    }

    pub fn restart(&mut self) -> Result<(), Box<dyn std::error::Error>> {
        self.cleanup();
        thread::sleep(Duration::from_secs(2));
        self.start()
    }

    pub fn cleanup(&mut self) {
        if let Some(mut process) = self.process.take() {
            // Try graceful shutdown first
            let _ = process.kill();
            let _ = process.wait();
        }
        self.is_healthy = false;
        self.heartbeat_failures = 0;
    }

    pub fn start_heartbeat(&mut self, app_handle: AppHandle) {
        let port = self.port;
        let url = format!("http://localhost:{}/health", port);

        thread::spawn(move || {
            let client = reqwest::blocking::Client::new();
            let mut failures = 0u32;

            loop {
                thread::sleep(Duration::from_secs(5));

                match client.get(&url).timeout(Duration::from_secs(3)).send() {
                    Ok(resp) if resp.status().is_success() => {
                        failures = 0;
                        let _ = app_handle.emit("python-heartbeat", true);
                    }
                    _ => {
                        failures += 1;
                        let _ = app_handle.emit("python-heartbeat", false);

                        if failures >= 3 {
                            let _ = app_handle.emit("python-crashed", ());
                            // Wait for restart
                            thread::sleep(Duration::from_secs(10));
                            failures = 0;
                        }
                    }
                }
            }
        });
    }

    fn wait_for_ready(&self, timeout: Duration) -> Result<(), Box<dyn std::error::Error>> {
        let start = Instant::now();
        let url = format!("http://localhost:{}/health", self.port);
        let client = reqwest::blocking::Client::new();

        while start.elapsed() < timeout {
            match client.get(&url).timeout(Duration::from_secs(2)).send() {
                Ok(resp) if resp.status().is_success() => {
                    return Ok(());
                }
                _ => {
                    thread::sleep(Duration::from_millis(500));
                }
            }
        }

        Err("Python backend failed to start within timeout".into())
    }

    fn get_python_path(&self) -> String {
        // In production, this points to the embedded Python
        // In development, use system Python
        if cfg!(debug_assertions) {
            if cfg!(target_os = "windows") {
                // Use python.exe (can launch visible browsers for login)
                let local_app_data = std::env::var("LOCALAPPDATA").unwrap_or_default();
                let python_path = format!("{}\\Programs\\Python\\Python314\\python.exe", local_app_data);
                if std::path::Path::new(&python_path).exists() {
                    python_path
                } else {
                    "python".to_string()
                }
            } else {
                "python3".to_string()
            }
        } else {
            // Production: embedded Python in the app bundle
            let exe_dir = std::env::current_exe()
                .unwrap()
                .parent()
                .unwrap()
                .to_path_buf();

            if cfg!(target_os = "windows") {
                exe_dir.join("python-runtime").join("python.exe").to_string_lossy().to_string()
            } else {
                exe_dir.join("python-runtime").join("bin").join("python3").to_string_lossy().to_string()
            }
        }
    }

    fn get_script_path(&self) -> String {
        if cfg!(debug_assertions) {
            // Development: use the backend directory relative to the project root
            // The exe is in src-tauri/target/debug/, so go up 3 levels to reach project root
            let exe_dir = std::env::current_exe()
                .unwrap()
                .parent()
                .unwrap()
                .to_path_buf();
            let project_root = exe_dir.parent().unwrap().parent().unwrap().parent().unwrap();
            project_root.join("backend").join("main.py").to_string_lossy().to_string()
        } else {
            // Production: bundled with the app
            let exe_dir = std::env::current_exe()
                .unwrap()
                .parent()
                .unwrap()
                .to_path_buf();

            exe_dir.join("engine").join("main.py").to_string_lossy().to_string()
        }
    }
}

impl Drop for PythonManager {
    fn drop(&mut self) {
        self.cleanup();
    }
}
```

---

# FILE: backend/engine/layers/layer1_ai_access/config/deepseek.json

```
{
  "aiId": "deepseek",
  "aiName": "DeepSeek",
  "url": "https://chat.deepseek.com",
  "loginUrl": "https://chat.deepseek.com/sign_in",
  "selectors": {
    "loginInput": [
      "input.ds-input__input[placeholder='Phone number']",
      "input.ds-input__input[placeholder*='phone']",
      "input[type='tel']"
    ],
    "codeInput": [
      "input.ds-input__input[placeholder='Code']",
      "input.ds-input__input[placeholder*='code']",
      "input[type='text'][class*='code']"
    ],
    "passwordToggle": [
      "div[class*='password']",
      "text=Login with password"
    ],
    "inputBox": [
      "textarea",
      "textarea[placeholder*='发送']",
      "textarea[placeholder*='Send']",
      "textarea[placeholder*='Message']",
      "textarea[placeholder*='输入']",
      "div[contenteditable='true'][role='textbox']",
      "div[contenteditable='true']"
    ],
    "sendButton": [
      "button[class*='send']",
      "div[class*='send-btn']",
      "button[aria-label='Send']",
      "div[class*='submit']"
    ],
    "responseContainer": [
      "div.ds-markdown.ds-assistant-message-main-content",
      "div[class*='ds-markdown']",
      "div[class*='message'][class*='assistant']"
    ],
    "responseContent": [
      "div.ds-markdown.ds-assistant-message-main-content",
      "div[class*='ds-markdown']",
      "div.markdown-body"
    ],
    "stopButton": [
      "button[class*='stop']",
      "div[class*='stop-generating']",
      "button[class*='Stop']"
    ],
    "newChatButton": [
      "div[class*='new-chat']",
      "button[class*='new-chat']",
      "a[href='/']"
    ]
  },
  "detection": {
    "completionStrategy": "idle_timeout",
    "idleTimeoutMs": 3000,
    "responseMinLength": 1
  },
  "timing": {
    "typingDelayMin": 30,
    "typingDelayMax": 80,
    "afterSendWaitMs": 1500,
    "maxResponseWaitMs": 180000
  }
}
```

---

# FILE: backend/engine/layers/layer1_ai_access/config/gemini.json

```
{
  "aiId": "gemini",
  "aiName": "Gemini",
  "url": "https://gemini.google.com/app",
  "loginUrl": "https://gemini.google.com",
  "selectors": {
    "inputBox": [
      "div.ql-editor.textarea.new-input-ui[contenteditable='true']",
      "div[contenteditable='true'][role='textbox']",
      "div[contenteditable='true']",
      "textarea"
    ],
    "sendButton": [
      "button.send-button",
      "button[aria-label='Send message']",
      "button[class*='send']"
    ],
    "responseContainer": [
      "message-content",
      "div[class*='response-container']",
      "div[class*='model-response']",
      "div[class*='markdown']"
    ],
    "responseContent": [
      "message-content .markdown",
      "div[class*='response-container'] .markdown",
      "div[class*='markdown']"
    ]
  },
  "detection": {
    "idleTimeoutMs": 3000,
    "responseMinLength": 1
  },
  "timing": {
    "afterSendWaitMs": 2000,
    "maxResponseWaitMs": 180000
  }
}
```

---

# FILE: backend/engine/layers/layer1_ai_access/config/qianwen.json

```
{
  "aiId": "qianwen",
  "aiName": "千问",
  "url": "https://tongyi.aliyun.com/qianwen",
  "loginUrl": "https://tongyi.aliyun.com",
  "selectors": {
    "inputBox": [
      "textarea",
      "div[contenteditable='true'][role='textbox']",
      "div[contenteditable='true']"
    ],
    "sendButton": [
      "button[class*='send']",
      "button[aria-label='发送']"
    ],
    "responseContainer": [
      "div[class*='markdown']",
      "div[class*='message'][class*='assistant']"
    ],
    "responseContent": [
      "div[class*='markdown']"
    ]
  },
  "detection": {
    "idleTimeoutMs": 3000,
    "responseMinLength": 1
  },
  "timing": {
    "afterSendWaitMs": 2000,
    "maxResponseWaitMs": 180000
  }
}
```

---

