"""
Smoke tests — fast sanity checks that core modules import and basic objects instantiate.
No browser, no network, no external dependencies.
"""


# ---------------------------------------------------------------------------
# 1. Shared modules
# ---------------------------------------------------------------------------

class TestSharedImports:
    def test_config(self):
        from shared.config import load_config
        assert callable(load_config)

    def test_errors(self):
        from shared.errors import AILoginRequiredError, OmniCouncilError
        assert issubclass(AILoginRequiredError, OmniCouncilError)

    def test_event_bus(self):
        from shared.event_bus import EventBus
        bus = EventBus()
        assert hasattr(bus, "on")
        assert hasattr(bus, "emit")

    def test_types(self):
        from shared.types import AIResponse, TaskStatus
        # AIResponse is a dataclass
        assert hasattr(AIResponse, "__dataclass_fields__")
        # TaskStatus is an Enum
        assert hasattr(TaskStatus, "__members__")


# ---------------------------------------------------------------------------
# 2. Browser engine
# ---------------------------------------------------------------------------

class TestBrowserImports:
    def test_engine_abc(self):
        from browser.engine import BrowserEngine, EngineMode
        assert EngineMode.EMBEDDED.value == "embedded"
        assert EngineMode.CDP.value == "cdp"
        assert hasattr(BrowserEngine, "connect")

    def test_factory(self):
        from browser.factory import create_engine
        assert callable(create_engine)


# ---------------------------------------------------------------------------
# 3. Provider system
# ---------------------------------------------------------------------------

class TestProviderImports:
    def test_base_provider(self):
        from providers.base.provider import BaseProvider
        assert hasattr(BaseProvider, "check_login")
        assert hasattr(BaseProvider, "send_prompt")

    def test_registry(self):
        from providers.registry.registry import ProviderRegistry
        assert hasattr(ProviderRegistry, "register")
        assert hasattr(ProviderRegistry, "get")

    def test_all_providers_importable(self):
        providers = [
            "providers.deepseek.provider",
            "providers.qianwen.provider",
            "providers.gemini.provider",
            "providers.chatgpt.provider",
            "providers.claude.provider",
            "providers.mimo.provider",
        ]
        for mod_name in providers:
            mod = __import__(mod_name, fromlist=["_"])
            # Each module should expose at least one Provider class
            classes = [v for v in dir(mod) if v.endswith("Provider") and v != "BaseProvider"]
            assert len(classes) >= 1, f"{mod_name} has no Provider class"


# ---------------------------------------------------------------------------
# 4. Engine layers
# ---------------------------------------------------------------------------

class TestEngineLayerImports:
    def test_layer1_ai_access(self):
        from engine.layers.layer1_ai_access.manager import AIAccessManager
        assert hasattr(AIAccessManager, "send_to_ai")

    def test_layer2_scheduler(self):
        from engine.layers.layer2_scheduler.scheduler_center import SchedulerCenter
        assert hasattr(SchedulerCenter, "submit_query")

    def test_layer3_collector(self):
        from engine.layers.layer3_collector.result_collector import ResultCollector
        assert hasattr(ResultCollector, "__init__")

    def test_layer4_comparison(self):
        from engine.layers.layer4_comparison.comparison_engine import ComparisonEngine
        assert hasattr(ComparisonEngine, "analyze")


# ---------------------------------------------------------------------------
# 5. Session management
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 6. Main app (import only, no server start)
# ---------------------------------------------------------------------------

class TestMainImport:
    def test_main_module_importable(self):
        """Verify main.py can be imported without starting the server."""
        import importlib
        mod = importlib.import_module("main")
        assert hasattr(mod, "app") or hasattr(mod, "websocket_endpoint")
