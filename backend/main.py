"""OmniCouncil FastAPI + WebSocket Backend with Engine Integration."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

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
        for connection in self.active_connections[:]:
            try:
                await connection.send_json(message)
            except Exception:
                pass

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
        asyncio.create_task(self.ws.broadcast({"type": "error", "data": error_info}))

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
    global event_bus, ai_manager, scheduler, collector, comparison_engine, browser_engine

    logger.info("Starting OmniCouncil backend...")

    # Initialize EventBus
    event_bus = EventBus()

    # Initialize config
    config = load_config()

    # Initialize Browser Engine
    browser_mode = "embedded"  # Default, will be overridden by config
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
    allow_origins=["*"],
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

            if msg_type == "submit_query":
                await handle_submit_query(data.get("data", {}))
            elif msg_type == "cancel_task":
                await handle_cancel_task(data.get("data", {}))
            elif msg_type == "get_status":
                await handle_get_status(websocket)
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

    task_id = f"task_{int(time.time())}_{id(query) % 10000}"

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


async def handle_reauth(data: dict):
    """Handle re-authentication request by launching a visible browser for login."""
    ai_id = data.get("ai_id")
    if not ai_id:
        return

    logger.info("Reauth requested for %s", ai_id)

    # Notify frontend: login started
    await ws_manager.broadcast({
        "type": "auth_status",
        "data": {"ai_id": ai_id, "status": "connecting", "message": "正在打开登录窗口..."}
    })

    try:
        # Launch visible browser for login
        from patchright.async_api import async_playwright

        urls = {
            "deepseek": "https://chat.deepseek.com",
            "qianwen": "https://tongyi.aliyun.com/qianwen",
        }
        url = urls.get(ai_id, "https://example.com")

        # Use user_data_dir to persist login session
        auth_dir = str(Path.home() / ".omnicouncil" / "auth")
        Path(auth_dir).mkdir(parents=True, exist_ok=True)
        profile_dir = str(Path(auth_dir) / f"{ai_id}_profile")

        pw = await async_playwright().start()
        browser = await pw.chromium.launch_persistent_context(
            profile_dir,
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = browser.pages[0] if browser.pages else await browser.new_page()

        await page.goto(url, wait_until="domcontentloaded", timeout=30000)

        # Wait for login (poll every 2 seconds, max 5 minutes)
        max_wait = 300
        start = time.time()

        while time.time() - start < max_wait:
            await asyncio.sleep(2)
            current_url = page.url

            # Check if login is complete by checking for chat interface elements
            logged_in = False

            if ai_id == "deepseek":
                logged_in = "/sign_in" not in current_url
            elif ai_id == "qianwen":
                # Check for chat input or URL change
                try:
                    # Check if we're on a chat page
                    if "/chat" in current_url or "qianwen.com" in current_url:
                        # Look for textarea or contenteditable (chat input)
                        textarea = page.locator("textarea")
                        if await textarea.count() > 0 and await textarea.first.is_visible(timeout=2000):
                            logged_in = True
                except Exception:
                    pass

            if logged_in:
                # Save auth state
                try:
                    auth_path = Path(auth_dir) / f"{ai_id}.json"
                    await browser.storage_state(path=str(auth_path))
                    logger.info("Saved auth state for %s", ai_id)
                except Exception as e:
                    logger.warning("Failed to save auth state: %s", e)

                # Copy cookies to main browser context if available
                if browser_engine and hasattr(browser_engine, '_context') and browser_engine._context:
                    try:
                        cookies = await browser.cookies()
                        await browser_engine._context.add_cookies(cookies)
                        logger.info("Copied %d cookies to main context for %s", len(cookies), ai_id)
                    except Exception as e:
                        logger.warning("Failed to copy cookies: %s", e)

                logger.info("Login successful for %s", ai_id)
                await ws_manager.broadcast({
                    "type": "auth_status",
                    "data": {"ai_id": ai_id, "status": "authenticated", "message": "登录成功"}
                })

                # Safely close browser
                try:
                    await browser.close()
                except Exception:
                    pass
                try:
                    await pw.stop()
                except Exception:
                    pass
                return

        # Timeout
        logger.warning("Login timeout for %s", ai_id)
        await ws_manager.broadcast({
            "type": "auth_status",
            "data": {"ai_id": ai_id, "status": "failed", "message": "登录超时"}
        })
        try:
            await browser.close()
        except Exception:
            pass
        try:
            await pw.stop()
        except Exception:
            pass

    except Exception as e:
        logger.exception("Login failed for %s", ai_id)
        await ws_manager.broadcast({
            "type": "auth_status",
            "data": {"ai_id": ai_id, "status": "failed", "message": f"登录失败: {str(e)}"}
        })


# ========== Session History ==========

from storage.local import LocalStorage

storage = LocalStorage()


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
