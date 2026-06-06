"""Shared application state container.

All engine components are initialized in lifespan() and stored here.
Other modules access state via `AppState.instance()` singleton pattern.

Usage:
    from shared.app_state import AppState
    state = AppState.instance()
    state.ai_manager.get_ready_ais()
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.layers.layer1_ai_access.manager import AIAccessManager
    from engine.layers.layer2_scheduler.scheduler_center import SchedulerCenter
    from engine.layers.layer3_collector.result_collector import ResultCollector
    from engine.layers.layer4_comparison.comparison_engine import ComparisonEngine
    from providers.registry import ProviderRegistry
    from shared.event_bus import EventBus
    from storage.local import LocalStorage


class AppState:
    """Singleton container for engine components.

    Created once during lifespan(), accessed everywhere via instance().
    """

    _singleton: AppState | None = None

    def __init__(self) -> None:
        self.event_bus: EventBus | None = None
        self.ai_manager: AIAccessManager | None = None
        self.scheduler: SchedulerCenter | None = None
        self.collector: ResultCollector | None = None
        self.comparison_engine: ComparisonEngine | None = None
        self.browser_engine = None
        self.provider_registry: ProviderRegistry | None = None
        self.storage: LocalStorage | None = None

    @classmethod
    def create(cls) -> AppState:
        """Create and register the singleton instance."""
        instance = cls()
        cls._singleton = instance
        return instance

    @classmethod
    def instance(cls) -> AppState:
        """Get the singleton instance. Raises RuntimeError if not initialized."""
        if cls._singleton is None:
            raise RuntimeError("AppState not initialized — lifespan() has not run yet")
        return cls._singleton

    @classmethod
    def reset(cls) -> None:
        """Reset all state (for testing or shutdown)."""
        if cls._singleton:
            cls._singleton.event_bus = None
            cls._singleton.ai_manager = None
            cls._singleton.scheduler = None
            cls._singleton.collector = None
            cls._singleton.comparison_engine = None
            cls._singleton.browser_engine = None
            cls._singleton.provider_registry = None
            cls._singleton.storage = None
        cls._singleton = None
