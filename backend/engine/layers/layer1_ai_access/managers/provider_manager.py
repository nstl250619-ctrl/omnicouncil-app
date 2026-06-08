"""ProviderManager — AI adapter registry."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from shared.types import ProviderStatus

    from providers.base.query_adapter import BaseQueryAdapter as AIAdapter


class ProviderManager:
    """Registry for AI adapters. Manages registration, lookup, and status."""

    def __init__(self) -> None:
        self._adapters: dict[str, AIAdapter] = {}

    def register(self, adapter: AIAdapter) -> None:
        """Register an AI adapter."""
        self._adapters[adapter.ai_id] = adapter

    def get(self, ai_id: str) -> AIAdapter | None:
        """Get an adapter by ID."""
        return self._adapters.get(ai_id)

    def get_all(self) -> list[AIAdapter]:
        """Get all registered adapters."""
        return list(self._adapters.values())

    def get_all_status(self) -> list[ProviderStatus]:
        """Get status of all registered adapters."""
        return [adapter.get_status() for adapter in self._adapters.values()]

    def get_status(self, ai_id: str) -> ProviderStatus | None:
        """Get status of a specific adapter."""
        adapter = self._adapters.get(ai_id)
        return adapter.get_status() if adapter else None

    @property
    def registered_ids(self) -> list[str]:
        """List all registered AI IDs."""
        return list(self._adapters.keys())
