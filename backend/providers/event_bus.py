"""ProviderEventBus — lightweight event system for provider lifecycle events.

Separate from core EventBus. Only handles provider-level events.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable, Coroutine
from typing import Any

logger = logging.getLogger(__name__)

EventHandler = Callable[..., Coroutine[Any, Any, None] | None]

# Event constants
PROVIDER_REGISTERED = "provider:registered"
PROVIDER_UNREGISTERED = "provider:unregistered"
PROVIDER_LOGIN_SUCCESS = "provider:login_success"
PROVIDER_LOGIN_FAILED = "provider:login_failed"
PROVIDER_HEALTH_CHANGED = "provider:health_changed"
PROVIDER_SESSION_EXPIRED = "provider:session_expired"
PROVIDER_ERROR = "provider:error"


class ProviderEventBus:
    """Lightweight event bus for provider lifecycle events."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)

    def on(self, event: str, handler: EventHandler) -> None:
        self._handlers[event].append(handler)

    def off(self, event: str, handler: EventHandler) -> None:
        try:
            self._handlers[event].remove(handler)
        except ValueError:
            pass

    async def emit(self, event: str, **kwargs: Any) -> None:
        for handler in self._handlers.get(event, []):
            try:
                result = handler(**kwargs)
                if hasattr(result, "__await__"):
                    await result
            except Exception:
                logger.exception("ProviderEventBus handler error for %s", event)
