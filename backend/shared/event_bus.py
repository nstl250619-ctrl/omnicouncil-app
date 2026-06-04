"""Global singleton EventBus for inter-layer communication.

All layers share this single instance. Events are dispatched asynchronously.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)

# Type alias for event handlers
EventHandler = Callable[..., Coroutine[Any, Any, None] | None]


class EventBus:
    """Singleton event bus for decoupled inter-layer communication."""

    _instance: EventBus | None = None

    def __new__(cls) -> EventBus:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._handlers = defaultdict(list)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)
        self._initialized = True

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton (for testing)."""
        if cls._instance is not None:
            cls._instance._handlers.clear()
            cls._instance._initialized = False
        cls._instance = None

    def on(self, event: str, handler: EventHandler) -> None:
        """Register an event handler."""
        self._handlers[event].append(handler)
        logger.debug("Registered handler for event '%s': %s", event, handler.__qualname__)

    def off(self, event: str, handler: EventHandler) -> None:
        """Unregister an event handler."""
        try:
            self._handlers[event].remove(handler)
        except ValueError:
            logger.warning("Handler %s not found for event '%s'", handler.__qualname__, event)

    async def emit(self, event: str, **kwargs: Any) -> None:
        """Emit an event, calling all registered handlers.

        Handlers that are coroutines are awaited; regular functions are called directly.
        Errors in individual handlers are logged but do not propagate.
        """
        handlers = self._handlers.get(event, [])
        if not handlers:
            logger.debug("No handlers for event '%s'", event)
            return

        logger.debug("Emitting event '%s' to %d handler(s)", event, len(handlers))

        for handler in handlers:
            try:
                result = handler(**kwargs)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.exception("Error in handler %s for event '%s'", handler.__qualname__, event)

    def emit_sync(self, event: str, **kwargs: Any) -> None:
        """Emit an event synchronously (for non-async contexts).

        Only calls non-coroutine handlers.
        """
        handlers = self._handlers.get(event, [])
        for handler in handlers:
            try:
                result = handler(**kwargs)
                if asyncio.iscoroutine(result):
                    # Can't await in sync context; schedule it
                    logger.warning("Skipping async handler %s in sync emit", handler.__qualname__)
                    continue
            except Exception:
                logger.exception("Error in handler %s for event '%s'", handler.__qualname__, event)

    @property
    def registered_events(self) -> list[str]:
        """List all events with registered handlers."""
        return list(self._handlers.keys())
