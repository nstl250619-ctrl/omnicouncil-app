"""AI Providers — plugin system for multi-AI support.

Usage:
    from providers.registry import create_default_registry
    registry = create_default_registry()
    provider = registry.get("deepseek")
"""
from .base import BaseProvider, ProviderConfig
from .registry import ProviderRegistry, create_default_registry

__all__ = ["BaseProvider", "ProviderConfig", "ProviderRegistry", "create_default_registry"]
