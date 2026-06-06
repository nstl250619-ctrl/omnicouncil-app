"""OmniCouncil FastAPI + WebSocket Backend.

This is the application entry point. It owns:
- FastAPI app creation and middleware
- Lifespan (initialization / shutdown of all engine components)
- Mounting routes and WebSocket from submodules

All business logic lives in:
- api/routes.py    — HTTP endpoints
- api/events.py    — Engine → WebSocket event handlers
- ws/connection.py — WebSocket manager and message handlers
"""

from __future__ import annotations

import argparse
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# Ensure critical Windows env vars are present (Tauri may strip them)
if sys.platform == "win32":
    if "LOCALAPPDATA" not in os.environ:
        user_profile = os.path.expanduser("~")
        os.environ["LOCALAPPDATA"] = os.path.join(user_profile, "AppData", "Local")
        os.environ["USERPROFILE"] = user_profile

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Add backend to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from typing import TYPE_CHECKING

from api.events import register_events
from api.routes import register_routes
from browser.factory import create_engine
from engine.layers.layer1_ai_access.manager import AIAccessManager
from engine.layers.layer2_scheduler.scheduler_center import SchedulerCenter
from engine.layers.layer3_collector.result_collector import ResultCollector
from engine.layers.layer4_comparison.comparison_engine import ComparisonEngine
from providers.registry import create_default_registry
from shared.app_state import AppState
from shared.config import load_config
from shared.event_bus import EventBus
from shared.logger import get_logger
from storage.local import LocalStorage
from ws.connection import GlobalExceptionHandler, websocket_endpoint, ws_manager

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

logger = get_logger(__name__)


# ========== App Lifecycle ==========

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    state = AppState.create()

    logger.info("Starting OmniCouncil backend...")

    # Initialize EventBus
    state.event_bus = EventBus()

    # Initialize config
    config = load_config()

    # Initialize Browser Engine
    browser_mode = "embedded"
    state.browser_engine = create_engine(browser_mode, headless=True)
    connected = await state.browser_engine.connect()
    logger.info("Browser engine: %s (connected=%s)", browser_mode, connected)

    # Initialize Provider Runtime OS
    from providers.runtime import ProviderRuntime
    state.provider_runtime = ProviderRuntime()

    # Auto-discover and register providers
    registry = create_default_registry()
    for provider in registry.get_all():
        provider._engine = state.browser_engine
        await state.provider_runtime.register(provider)
    state.provider_registry = registry
    # V1: exclude Claude — only ship DeepSeek, Qianwen, Gemini, ChatGPT, MiMo
    state.provider_runtime.unregister("claude")
    logger.info("Providers: %s", state.provider_runtime.get_ids())

    # Initialize Layer 1: AI Access — register all providers as adapters
    state.ai_manager = AIAccessManager(event_bus=state.event_bus)
    for provider in state.provider_runtime.get_all():
        state.ai_manager.register_adapter(provider)
    await state.ai_manager.initialize()
    await state.provider_runtime.initialize_all()

    # Initialize Layer 2: Scheduler
    state.scheduler = SchedulerCenter(
        ai_manager=state.ai_manager,
        event_bus=state.event_bus,
        max_concurrent=config.scheduler.max_concurrent_tasks,
        ai_min_interval_ms=config.scheduler.ai_min_interval_ms,
    )

    # Initialize Layer 3: Collector
    state.collector = ResultCollector(event_bus=state.event_bus)

    # Initialize Layer 4: Comparison
    state.comparison_engine = ComparisonEngine(config=config.comparison, event_bus=state.event_bus)

    # Initialize Layer 5: Consensus + Conflict + Judge
    from engine.consensus import ConsensusEngine
    from engine.conflict import ConflictEngine
    from engine.judge import JudgeEngine
    state.consensus_engine = ConsensusEngine(config=config.comparison)
    state.conflict_engine = ConflictEngine()
    state.judge_engine = JudgeEngine()

    # Initialize Storage
    state.storage = LocalStorage()

    # Register event handlers (Engine → WebSocket)
    register_events(ws_manager)

    # Install sidecar instrumentation (trace + metrics)
    from shared.instrumentation import Instrumentation
    from shared.metrics import MetricsCollector
    from shared.trace import TraceStore
    if config.tracing_enabled:
        TraceStore.instance()
    if config.metrics_enabled:
        MetricsCollector.instance()
    instrumentation = Instrumentation(
        event_bus=state.event_bus,
        tracing_enabled=config.tracing_enabled,
        metrics_enabled=config.metrics_enabled,
    )
    instrumentation.install()

    # Install global exception handler
    exception_handler = GlobalExceptionHandler(ws_manager)
    exception_handler.install()

    logger.info("OmniCouncil backend started. AIs: %s", [a.ai_id for a in state.ai_manager.get_ready_ais()])

    yield

    # Cleanup
    logger.info("Shutting down OmniCouncil backend...")
    if state.provider_runtime:
        await state.provider_runtime.destroy_all()
    if state.browser_engine:
        await state.browser_engine.disconnect()
    if state.ai_manager:
        await state.ai_manager.destroy()
    TraceStore.reset()
    MetricsCollector.reset()
    EventBus.reset()
    AppState.reset()


# ========== App Creation ==========

app = FastAPI(title="OmniCouncil", version="0.1.0", lifespan=lifespan)

class DevCORSMiddleware(CORSMiddleware):
    """CORS middleware that allows any localhost/127.0.0.1 origin (dev mode)."""

    def is_allowed_origin(self, origin: str) -> bool:
        if super().is_allowed_origin(origin):
            return True
        return bool(origin) and (
            origin.startswith("http://localhost:")
            or origin.startswith("http://127.0.0.1:")
        )


app.add_middleware(
    DevCORSMiddleware,
    allow_origins=[
        "tauri://localhost",
        "http://localhost:8765",
        "http://127.0.0.1:8765",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount HTTP routes
register_routes(app)

# Mount WebSocket endpoint
app.websocket("/ws")(websocket_endpoint)


# ========== Entry Point ==========

if __name__ == "__main__":
    import uvicorn

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    logger.info("Starting on port %d", args.port)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")
