"""Session manager — coordinates login state across providers."""

from __future__ import annotations

import logging
import time

from .storage import SessionStorage

logger = logging.getLogger(__name__)


class SessionManager:
    """Manages login sessions for all AI providers.

    Responsibilities:
    - Track which providers are authenticated
    - Coordinate login flows
    - Validate session health
    """

    def __init__(self, storage: SessionStorage | None = None):
        self._storage = storage or SessionStorage()
        self._authenticated: set[str] = set()
        self._last_check: dict[str, float] = {}

    @property
    def storage(self) -> SessionStorage:
        return self._storage

    def is_authenticated(self, provider_id: str) -> bool:
        return provider_id in self._authenticated

    def set_authenticated(self, provider_id: str, authenticated: bool = True) -> None:
        if authenticated:
            self._authenticated.add(provider_id)
            self._last_check[provider_id] = time.time()
        else:
            self._authenticated.discard(provider_id)

    def get_authenticated_providers(self) -> list[str]:
        return list(self._authenticated)

    def has_saved_session(self, provider_id: str) -> bool:
        return self._storage.has_session(provider_id)

    def get_profile_dir(self, provider_id: str) -> str:
        return self._storage.get_profile_dir(provider_id)
