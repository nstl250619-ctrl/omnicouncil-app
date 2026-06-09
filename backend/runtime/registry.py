"""RuntimeRegistry — maps platform IDs to AIRuntimeEngine instances.

Replaces the pattern of storing engines in ``AppState`` as ad-hoc
attributes.  The Scheduler and AIAccessManager use this to look up
the correct runtime for each AI.

Usage::

    registry = RuntimeRegistry()
    registry.register("deepseek", deepseek_engine)
    registry.register("chatgpt", chatgpt_engine)

    engine = registry.get("deepseek")
    state = await engine.ensure_ready()
    page = engine.get_page()
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from engine.contracts import RuntimeRegistry as RuntimeRegistryProtocol
from engine.contracts import RuntimeState

if TYPE_CHECKING:
    from runtime.engine import AIRuntimeEngine

logger = logging.getLogger(__name__)


class RuntimeRegistry(RuntimeRegistryProtocol):
    """Concrete ``RuntimeRegistry`` backed by a simple dict."""

    def __init__(self) -> None:
        self._engines: dict[str, AIRuntimeEngine] = {}

    def register(self, platform: str, engine: AIRuntimeEngine) -> None:
        """Register an engine for *platform*.  Overwrites if already present."""
        self._engines[platform] = engine
        logger.info("RuntimeRegistry: registered %s", platform)

    def unregister(self, platform: str) -> None:
        """Remove the engine for *platform*.  No-op if not found."""
        self._engines.pop(platform, None)
        logger.info("RuntimeRegistry: unregistered %s", platform)

    def get(self, platform: str) -> AIRuntimeEngine | None:
        """Return the engine for *platform*, or None."""
        return self._engines.get(platform)

    def get_all(self) -> dict[str, AIRuntimeEngine]:
        """Return all registered engines."""
        return dict(self._engines)

    def all(self) -> dict[str, AIRuntimeEngine]:
        """Alias for get_all() — convenience for iteration."""
        return dict(self._engines)

    def get_platforms(self) -> list[str]:
        """Return all registered platform IDs."""
        return list(self._engines.keys())

    async def ensure_all_ready(self, timeout_s: float = 120.0) -> dict[str, RuntimeState]:
        """Call ``ensure_ready()`` on every registered engine.

        Returns a mapping of platform → resulting state.
        Engines that fail or timeout are mapped to ``UNAVAILABLE``.
        """
        results: dict[str, RuntimeState] = {}

        async def _ensure(platform: str, engine: AIRuntimeEngine) -> None:
            try:
                state = await asyncio.wait_for(engine.ensure_ready(), timeout=timeout_s)
                results[platform] = state
            except asyncio.TimeoutError:
                logger.error("RuntimeRegistry: ensure_ready timed out for %s after %ds", platform, timeout_s)
                results[platform] = RuntimeState.UNAVAILABLE
            except Exception as exc:
                logger.error("RuntimeRegistry: ensure_ready failed for %s: %s", platform, exc)
                results[platform] = RuntimeState.UNAVAILABLE

        await asyncio.gather(
            *[_ensure(p, e) for p, e in self._engines.items()],
            return_exceptions=True,
        )
        return results

    async def shutdown_all(self) -> None:
        """Shut down every registered engine."""
        for platform, engine in self._engines.items():
            try:
                await engine.shutdown()
            except Exception:
                logger.exception("RuntimeRegistry: shutdown failed for %s", platform)
        self._engines.clear()

    def __len__(self) -> int:
        return len(self._engines)

    def __contains__(self, platform: str) -> bool:
        return platform in self._engines
