"""OmniCouncil FastAPI + WebSocket Backend — V2 with Runtime + Query Engine.

This is the new application entry point that integrates:
    - ``RuntimeRegistry`` — maps platforms to ``AIRuntimeEngine`` instances
    - ``AIAccessManager`` — uses RuntimeRegistry + QueryAdapter
    - ``HealthMonitor`` — replaces ``SessionManager`` and watchdog
    - ``QueryAdapter`` per platform — replaces old ``BaseProvider``

The old ``main.py`` remains for backward compatibility during migration.
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
from engine.contracts import PlatformConfig
from engine.layers.layer1_ai_access.manager import AIAccessManager
from engine.layers.layer2_scheduler.scheduler_center import SchedulerCenter
from engine.layers.layer3_collector.result_collector import ResultCollector
from omnicounci1l_comparison import ComparisonEngine
from providers.chatgpt.query_adapter import ChatGPTQueryAdapter
from providers.deepseek.query_adapter import DeepSeekQueryAdapter
from providers.gemini.query_adapter import GeminiQueryAdapter
from providers.mimo.query_adapter import MiMoQueryAdapter
from providers.qianwen.query_adapter import QianwenQueryAdapter
from runtime.engine import AIRuntimeEngine
from runtime.registry import RuntimeRegistry
from shared.app_state import AppState
from shared.config import load_config
from shared.event_bus import EventBus
from shared.logger import get_logger
from storage.local import LocalStorage
from ws.connection import GlobalExceptionHandler, websocket_endpoint, ws_manager

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

logger = get_logger(__name__)


# ========== Platform configurations ==========

PLATFORM_CONFIGS: dict[str, PlatformConfig] = {
    "deepseek": PlatformConfig(
        name="deepseek",
        home_url="https://chat.deepseek.com",
        headless=True,
        heartbeat_interval_s=60,
        max_recovery_attempts=3,
        recovery_cooldown_s=30,
        session_check_mode="offline_then_online",
    ),
    "qianwen": PlatformConfig(
        name="qianwen",
        home_url="https://www.qianwen.com/qianwen",
        headless=True,
        heartbeat_interval_s=60,
        max_recovery_attempts=3,
        recovery_cooldown_s=30,
        session_check_mode="offline_then_online",
    ),
    "gemini": PlatformConfig(
        name="gemini",
        home_url="https://gemini.google.com/app",
        headless=True,
        heartbeat_interval_s=60,
        max_recovery_attempts=3,
        recovery_cooldown_s=30,
        session_check_mode="offline_then_online",
    ),
    "chatgpt": PlatformConfig(
        name="chatgpt",
        home_url="https://chatgpt.com",
        headless=False,  # ChatGPT needs non-headless for Cloudflare
        heartbeat_interval_s=60,
        max_recovery_attempts=3,
        recovery_cooldown_s=30,
        session_check_mode="offline_then_online",
    ),
    "mimo": PlatformConfig(
        name="mimo",
        home_url="https://aistudio.xiaomimimo.com/#/",
        headless=True,
        heartbeat_interval_s=60,
        max_recovery_attempts=3,
        recovery_cooldown_s=30,
        session_check_mode="offline_then_online",
    ),
}


# ========== Query adapters ==========

def _create_query_adapters() -> dict:
    """Create query adapters for all platforms."""
    return {
        "deepseek": DeepSeekQueryAdapter(),
        "qianwen": QianwenQueryAdapter(),
        "gemini": GeminiQueryAdapter(),
        "chatgpt": ChatGPTQueryAdapter(),
        "mimo": MiMoQueryAdapter(),
    }


# ========== App Lifecycle ==========

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    state = AppState.create()

    logger.info("Starting OmniCouncil backend (V2)...")

    # Redirect all engine/provider loggers under the omnicouncil handler tree
    from shared.logger import patch_all_loggers
    patch_all_loggers()
    state.event_bus = EventBus()

    # Initialize config
    config = load_config()

    # Initialize RuntimeRegistry
    runtime_registry = RuntimeRegistry()
    state.runtime_registry = runtime_registry

    # Create and register Runtime Engines for each platform
    for platform, platform_config in PLATFORM_CONFIGS.items():
        engine = AIRuntimeEngine(config=platform_config)
        runtime_registry.register(platform, engine)
    logger.info("Runtime engines registered: %s", runtime_registry.get_platforms())

    # Boot all runtimes (parallel)
    boot_results = await runtime_registry.ensure_all_ready()
    for platform, result in boot_results.items():
        logger.info("  %s: %s", platform, result.value)

    # Create query adapters
    query_adapters = _create_query_adapters()

    # Initialize AIAccessManager
    state.ai_manager = AIAccessManager(
        runtime_registry=runtime_registry,
        query_adapters=query_adapters,
        event_bus=state.event_bus,
    )
    logger.info("AIAccessManager initialized")

    # Initialize Layer 2: Scheduler
    state.scheduler = SchedulerCenter(
        ai_manager=state.ai_manager,
        event_bus=state.event_bus,
        max_concurrent=config.scheduler.max_concurrent_tasks,
        ai_min_interval_ms=config.scheduler.ai_min_interval_ms,
        soft_timeout_ms=config.scheduler.soft_timeout_ms,
        hard_timeout_ms=config.scheduler.hard_timeout_ms,
    )

    # Initialize Layer 3: Collector
    state.collector = ResultCollector(event_bus=state.event_bus)

    # Initialize Layer 4: Comparison
    state.comparison_engine = ComparisonEngine(config=config.comparison, event_bus=state.event_bus)

    # Initialize Layer 5: Consensus + Conflict + Judge
    from omnicounci1l_conflict import ConflictEngine
    from omnicounci1l_consensus import ConsensusEngine
    from omnicounci1l_judge import JudgeEngine
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

    ready_ais = [p for p, s in boot_results.items() if s.value == "ready"]
    logger.info("OmniCouncil backend V2 started. Ready AIs: %s", ready_ais)

    yield

    # Cleanup
    logger.info("Shutting down OmniCouncil backend V2...")
    await runtime_registry.shutdown_all()
    if state.ai_manager:
        pass  # AIAccessManager doesn't have destroy()
    TraceStore.reset()
    MetricsCollector.reset()
    EventBus.reset()
    AppState.reset()


# ========== App Creation ==========

app = FastAPI(title="OmniCouncil", version="0.2.0", lifespan=lifespan)


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
