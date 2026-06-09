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
from engine.contracts import (
    AuthConfig,
    AuthMethod,
    CookieAuthConfig,
    PageInteractionConfig,
    PlatformCapability,
    PlatformConfig,
)
from engine.layers.layer1_ai_access.manager import AIAccessManager
from engine.layers.layer2_scheduler.scheduler_center import SchedulerCenter
from engine.layers.layer3_collector.result_collector import ResultCollector
from omnicounci1l_comparison import ComparisonEngine
from providers.chatgpt.query_adapter import ChatGPTQueryAdapter
from providers.deepseek.query_adapter import DeepSeekQueryAdapter
from providers.gemini.query_adapter import GeminiQueryAdapter
from providers.mimo.query_adapter import MiMoQueryAdapter
from providers.grok.query_adapter import GrokQueryAdapter
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
        auth=AuthConfig(
            method=AuthMethod.COOKIE,
            cookie=CookieAuthConfig(
                domains=["chat.deepseek.com"],
                names=["sessionid", "token", "auth"],
                match="prefix",
            ),
        ),
        page=PageInteractionConfig(
            input_selectors=["textarea", "div[contenteditable='true']"],
            response_selectors=["[data-role='assistant']", "[class*='response']", "[class*='message-content']"],
            stop_button_selectors=["button[aria-label='Stop generating']", "button:has-text('Stop')"],
            ui_elements=["DeepSeek", "New chat", "Settings", "Copy"],
            login_url_patterns=["signin", "sign-in", "login", "auth0"],
            cloudflare_check=False,
        ),
        capabilities=PlatformCapability(
            supports_streaming=True,
            supports_file_upload=True,
            max_input_chars=10000,
            response_format="markdown",
        ),
    ),
    "qianwen": PlatformConfig(
        name="qianwen",
        home_url="https://www.qianwen.com/qianwen",
        headless=True,
        heartbeat_interval_s=60,
        max_recovery_attempts=3,
        recovery_cooldown_s=30,
        session_check_mode="offline_then_online",
        auth=AuthConfig(
            method=AuthMethod.COOKIE,
            cookie=CookieAuthConfig(
                domains=["qianwen.com"],
                names=["sid", "login_", "ALI_", "Session", "cookie2"],
                match="prefix",
            ),
        ),
        page=PageInteractionConfig(
            input_selectors=["[contenteditable='true'][role='textbox']", "[contenteditable='true']", "textarea"],
            response_selectors=["[class*='message']", "[class*='response']", "[class*='assistant']"],
            stop_button_selectors=["button:has-text('停止')", "button[aria-label='Stop']"],
            ui_elements=["千问", "新对话", "设置", "复制"],
            login_url_patterns=["login", "signin"],
            cloudflare_check=False,
        ),
        capabilities=PlatformCapability(
            supports_streaming=True,
            supports_file_upload=True,
            max_input_chars=10000,
            response_format="markdown",
        ),
    ),
    "gemini": PlatformConfig(
        name="gemini",
        home_url="https://gemini.google.com/app",
        headless=True,
        heartbeat_interval_s=60,
        max_recovery_attempts=3,
        recovery_cooldown_s=30,
        session_check_mode="offline_then_online",
        auth=AuthConfig(
            method=AuthMethod.COOKIE,
            cookie=CookieAuthConfig(
                domains=["google.com"],
                names=["SAPISID", "SSID", "__Secure-", "OSID"],
                match="prefix",
            ),
        ),
        page=PageInteractionConfig(
            input_selectors=["[contenteditable='true']", "div[contenteditable='true']", "textarea", "[role='textbox']", "main textarea", "gemini-app textarea"],
            response_selectors=["[data-role='assistant']", "[class*='response']", "[class*='model-response']", "[class*='message-content']"],
            stop_button_selectors=["button[aria-label='Stop']", "button:has-text('Stop')"],
            ui_elements=["Gemini", "New chat", "Settings", "Copy"],
            login_url_patterns=["signin", "sign-in", "login", "accounts.google.com"],
            cloudflare_check=False,
        ),
        capabilities=PlatformCapability(
            supports_streaming=True,
            supports_file_upload=True,
            supports_image=True,
            max_input_chars=10000,
            response_format="markdown",
        ),
    ),
    "chatgpt": PlatformConfig(
        name="chatgpt",
        home_url="https://chatgpt.com",
        headless=False,
        heartbeat_interval_s=60,
        max_recovery_attempts=3,
        recovery_cooldown_s=30,
        session_check_mode="offline_then_online",
        extra_browser_args=[
            "--window-position=-32000,-32000",
            "--window-size=1,1",
            "--app=https://chatgpt.com",
            "--no-startup-window",
            "--disable-notifications",
            "--disable-infobars",
        ],
        auth=AuthConfig(
            method=AuthMethod.COOKIE,
            cookie=CookieAuthConfig(
                domains=["chatgpt.com"],
                names=["__Secure-next-auth.session-token", "__Host-next-auth.csrf-token"],
                match="prefix",
            ),
        ),
        page=PageInteractionConfig(
            input_selectors=["#prompt-textarea", "[contenteditable='true']", "textarea", "div[contenteditable='true']", "[data-orientation='vertical'] textarea", "main textarea", "[role='textbox']"],
            response_selectors=["[data-message-author-role='assistant']", "[class*='message']", "[class*='response']"],
            stop_button_selectors=["button[aria-label='Stop generating']", "button:has-text('Stop')", "button:has-text('停止')"],
            ui_elements=["ChatGPT", "New chat", "Settings", "Copy", "Regenerate"],
            login_url_patterns=["/auth/login", "auth0.openai.com", "/login"],
            cloudflare_check=True,
        ),
        capabilities=PlatformCapability(
            supports_streaming=True,
            supports_file_upload=True,
            supports_image=True,
            max_input_chars=10000,
            response_format="markdown",
        ),
    ),
    "mimo": PlatformConfig(
        name="mimo",
        home_url="https://aistudio.xiaomimimo.com/#/",
        headless=True,
        heartbeat_interval_s=60,
        max_recovery_attempts=3,
        recovery_cooldown_s=30,
        session_check_mode="offline_then_online",
        auth=AuthConfig(
            method=AuthMethod.COOKIE,
            cookie=CookieAuthConfig(
                domains=["xiaomi.com", "account.xiaomi.com"],
                names=["passToken", "userId", "session", "token", "auth"],
                match="prefix",
            ),
        ),
        page=PageInteractionConfig(
            input_selectors=["[contenteditable='true'][role='textbox']", "[contenteditable='true']", "div[contenteditable='true']", "textarea", "[role='textbox']", "main textarea", "main [contenteditable='true']"],
            response_selectors=["[data-role='assistant']", "[class*='assistant']", "[class*='response']", "[class*='bot-message']", "[class*='ai-message']"],
            stop_button_selectors=["button[aria-label='Stop generating']", "button:has-text('Stop')", "button:has-text('停止')"],
            ui_elements=["MiMo", "New chat", "Settings", "Sign in", "Send", "Copy", "Regenerate", "Help", "History"],
            login_url_patterns=["login", "signin", "sign-in"],
            cloudflare_check=False,
        ),
        capabilities=PlatformCapability(
            supports_streaming=True,
            max_input_chars=10000,
            response_format="markdown",
            requires_chat_mode=True,
        ),
    ),
    "grok": PlatformConfig(
        name="grok",
        home_url="https://grok.com",
        headless=True,
        heartbeat_interval_s=60,
        max_recovery_attempts=3,
        recovery_cooldown_s=30,
        session_check_mode="offline_then_online",
        auth=AuthConfig(
            method=AuthMethod.COOKIE,
            cookie=CookieAuthConfig(
                domains=["x.com", "grok.com"],
                names=["_twitter_sess", "ct0", "auth_token"],
                match="contains",
            ),
        ),
        page=PageInteractionConfig(
            input_selectors=["textarea", "[contenteditable='true']", "[role='textbox']"],
            response_selectors=["[data-message-author-role='assistant']", "[class*='message']", "[class*='response']"],
            stop_button_selectors=["button[aria-label='Stop']", "button:has-text('Stop')"],
            ui_elements=["Grok", "New chat", "Settings", "Copy"],
            login_url_patterns=["login", "signin", "x.com/oauth"],
            cloudflare_check=True,
        ),
        capabilities=PlatformCapability(
            supports_streaming=True,
            supports_image=True,
            max_input_chars=10000,
            response_format="markdown",
        ),
    ),
}


# ========== YAML config loading (Phase 5) ==========

def _load_platform_configs() -> dict[str, PlatformConfig]:
    """Load platform configs from YAML, fallback to hardcoded."""
    from runtime.config_loader import PlatformConfigLoader
    from pathlib import Path

    providers_dir = Path(__file__).parent / "providers"
    loader = PlatformConfigLoader(providers_dir)
    yaml_configs = loader.load_all()

    if yaml_configs:
        logger.info("Loaded %d platform configs from YAML", len(yaml_configs))
        # Merge: YAML overrides hardcoded for matching platforms
        merged = dict(PLATFORM_CONFIGS)
        for name, config in yaml_configs.items():
            merged[name] = config
        return merged
    else:
        logger.info("No YAML configs found, using hardcoded PLATFORM_CONFIGS")
        return dict(PLATFORM_CONFIGS)


# ========== Query adapters ==========

def _create_query_adapters() -> dict:
    """Create query adapters for all platforms."""
    return {
        "deepseek": DeepSeekQueryAdapter(),
        "qianwen": QianwenQueryAdapter(),
        "gemini": GeminiQueryAdapter(),
        "chatgpt": ChatGPTQueryAdapter(),
        "mimo": MiMoQueryAdapter(),
        "grok": GrokQueryAdapter(),
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
    # Phase 5: load from YAML first, fallback to hardcoded
    active_configs = _load_platform_configs()
    for platform, platform_config in active_configs.items():
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

# Mount Dashboard API
from api.dashboard import router as dashboard_router
app.include_router(dashboard_router)

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
