"""Provider registry with auto-discovery."""

from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Any

from ..base import BaseProvider

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
