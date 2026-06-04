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
