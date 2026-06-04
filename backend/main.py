"""OmniCouncil FastAPI + WebSocket Backend."""

from __future__ import annotations

import argparse
import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

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
        self.active_connections.remove(websocket)
        logger.info("WebSocket disconnected. Total: %d", len(self.active_connections))

    async def broadcast(self, message: dict):
        """Send message to all connected clients."""
        for connection in self.active_connections:
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


# ========== Global Exception Handler ==========

class GlobalExceptionHandler:
    """Catches unhandled exceptions and pushes them to frontend via WebSocket."""

    def __init__(self, ws: ConnectionManager):
        self.ws = ws

    def install(self):
        import sys
        sys.excepthook = self._sync_hook
        loop = asyncio.get_event_loop()
        loop.set_exception_handler(self._async_hook)

    def _sync_hook(self, exc_type, exc_value, exc_tb):
        error_info = self._format(exc_type, exc_value)
        asyncio.create_task(self.ws.broadcast({
            "type": "error",
            "data": error_info
        }))

    def _async_hook(self, loop, context):
        exception = context.get("exception")
        if exception:
            error_info = self._format(type(exception), exception)
            asyncio.create_task(self.ws.broadcast({
                "type": "error",
                "data": error_info
            }))

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
    logger.info("Starting OmniCouncil backend...")
    exception_handler = GlobalExceptionHandler(ws_manager)
    exception_handler.install()
    yield
    logger.info("Shutting down OmniCouncil backend...")


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
    return {"status": "ok", "version": "0.1.0", "timestamp": time.time()}


# ========== WebSocket Endpoint ==========

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
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
    query = data.get("query", "")
    ai_ids = data.get("ai_ids", ["deepseek"])
    mode = data.get("mode", "parallel")

    task_id = f"task_{int(time.time())}"

    logger.info("Task %s: submitting query to %s", task_id, ai_ids)

    # Notify frontend: task started
    await ws_manager.broadcast({
        "type": "progress",
        "data": {"task_id": task_id, "completed": 0, "total": len(ai_ids), "current_ai": ""}
    })

    # Execute in background
    asyncio.create_task(execute_task(task_id, query, ai_ids))


async def execute_task(task_id: str, query: str, ai_ids: list[str]):
    """Execute query across multiple AIs."""
    completed = 0
    total = len(ai_ids)

    for ai_id in ai_ids:
        try:
            # Notify: AI started
            await ws_manager.broadcast({
                "type": "ai_started",
                "data": {"task_id": task_id, "ai_id": ai_id}
            })

            # TODO: Call actual AI adapter
            # For now, simulate with a delay
            await asyncio.sleep(2)

            # Simulate response
            result = f"[{ai_id}] 这是对 '{query}' 的回答。"

            # Notify: AI completed
            await ws_manager.broadcast({
                "type": "ai_completed",
                "data": {
                    "task_id": task_id,
                    "ai_id": ai_id,
                    "full_text": result,
                    "word_count": len(result),
                    "elapsed_ms": 2000
                }
            })

            completed += 1
            await ws_manager.broadcast({
                "type": "progress",
                "data": {"task_id": task_id, "completed": completed, "total": total, "current_ai": ai_id}
            })

        except Exception as e:
            await ws_manager.broadcast({
                "type": "ai_failed",
                "data": {"task_id": task_id, "ai_id": ai_id, "error": str(e)}
            })

    # All done
    await ws_manager.broadcast({
        "type": "all_completed",
        "data": {"task_id": task_id}
    })


async def handle_cancel_task(data: dict):
    """Handle task cancellation."""
    task_id = data.get("task_id")
    logger.info("Task %s: cancelled", task_id)
    await ws_manager.broadcast({
        "type": "task_cancelled",
        "data": {"task_id": task_id}
    })


async def handle_get_status(websocket: WebSocket):
    """Handle status request."""
    await ws_manager.send_personal(websocket, {
        "type": "status",
        "data": {"connected": True, "ai_count": 0}
    })


# ========== Entry Point ==========

if __name__ == "__main__":
    import uvicorn

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    logger.info("Starting on port %d", args.port)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")
