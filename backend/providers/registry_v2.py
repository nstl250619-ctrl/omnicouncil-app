"""ProviderRegistryV2 — enhanced registry with state management."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from shared.types import AIStatus

if TYPE_CHECKING:
    from providers.base.provider import BaseProvider

logger = logging.getLogger(__name__)


class ProviderRegistryV2:
    """Enhanced provider registry with state tracking."""

    def __init__(self) -> None:
        self._providers: dict[str, BaseProvider] = {}
        self._statuses: dict[str, AIStatus] = {}

    def register(self, provider: BaseProvider) -> None:
        pid = provider.ai_id
        existed = pid in self._providers
        self._providers[pid] = provider
        self._statuses[pid] = AIStatus.INITIALIZING
        action = "hot-swapped" if existed else "registered"
        logger.info("Provider %s: %s (%s)", pid, action, provider.ai_name)

    def unregister(self, provider_id: str) -> bool:
        if provider_id not in self._providers:
            return False
        del self._providers[provider_id]
        self._statuses.pop(provider_id, None)
        logger.info("Provider %s: unregistered", provider_id)
        return True

    def get(self, provider_id: str) -> BaseProvider | None:
        return self._providers.get(provider_id)

    def get_all(self) -> list[BaseProvider]:
        return list(self._providers.values())

    def get_ids(self) -> list[str]:
        return list(self._providers.keys())

    def get_status(self, provider_id: str) -> AIStatus | None:
        return self._statuses.get(provider_id)

    def set_status(self, provider_id: str, status: AIStatus) -> None:
        self._statuses[provider_id] = status

    def get_configs(self) -> list[dict[str, Any]]:
        return [
            {
                "provider_id": p.config().provider_id,
                "display_name": p.config().display_name,
                "enabled": p.config().enabled,
                "icon_color": p.config().icon_color,
                "icon_emoji": p.config().icon_emoji,
                "status": self._statuses.get(p.ai_id, AIStatus.INITIALIZING).value,
            }
            for p in self._providers.values()
        ]
