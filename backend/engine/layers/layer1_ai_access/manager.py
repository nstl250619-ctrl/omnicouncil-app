"""AIAccessManager — unified entry point for Layer 1.

This is the ONLY interface that Layer 2 (Scheduler) calls.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from shared.event_bus import EventBus
from shared.types import (
    AIResponse,
    ProviderStatus,
    SubmitOptions,
)

from .managers.circuit_breaker import CircuitBreaker
from .managers.provider_manager import ProviderManager
from .managers.rate_limiter import RateLimiter

if TYPE_CHECKING:
    from .adapter import AIAdapter

logger = logging.getLogger(__name__)


class AIAccessManager:
    """Unified AI access interface.

    Provides: send_to_ai, send_to_multiple, get_ready_ais
    Layer 2 (Scheduler) depends ONLY on this class.
    """

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self._provider_manager = ProviderManager()
        self._rate_limiter = RateLimiter()
        self._circuit_breakers: dict[str, CircuitBreaker] = {}
        self._event_bus = event_bus or EventBus()

    def register_adapter(self, adapter: AIAdapter) -> None:
        """Register an AI adapter."""
        self._provider_manager.register(adapter)
        self._circuit_breakers[adapter.ai_id] = CircuitBreaker(
            ai_id=adapter.ai_id,
            on_state_change=lambda ai_id, old, new: logger.info(
                "Circuit breaker %s: %s -> %s", ai_id, old.value, new.value
            ),
        )
        logger.info("Registered adapter: %s (%s)", adapter.ai_id, adapter.ai_name)

    async def initialize(self, ai_ids: list[str] | None = None) -> None:
        """Initialize adapters for the specified AIs (or all if None)."""
        adapters = self._provider_manager.get_all()
        if ai_ids:
            adapters = [a for a in adapters if a.ai_id in ai_ids]

        for adapter in adapters:
            try:
                await adapter.initialize()
            except Exception:
                logger.exception("Failed to initialize adapter: %s", adapter.ai_id)

    async def destroy(self) -> None:
        """Destroy all adapters."""
        for adapter in self._provider_manager.get_all():
            try:
                await adapter.destroy()
            except Exception:
                logger.exception("Failed to destroy adapter: %s", adapter.ai_id)

    def get_ready_ais(self) -> list[ProviderStatus]:
        """Get status of all registered AIs."""
        return self._provider_manager.get_all_status()

    def get_provider_status(self, ai_id: str) -> ProviderStatus | None:
        """Get status of a specific AI."""
        return self._provider_manager.get_status(ai_id)

    async def send_to_ai(
        self, ai_id: str, prompt: str, options: SubmitOptions | None = None, task_id: str = ""
    ) -> AIResponse:
        """Send a prompt to a single AI.

        Checks: rate limit → circuit breaker → adapter.send_prompt.
        task_id: the scheduler's task_id for event correlation.
        """
        adapter = self._provider_manager.get(ai_id)
        if adapter is None:
            return AIResponse(
                success=False,
                ai_id=ai_id,
                task_id="",
                content="",
                error_code="ADAPTER_NOT_FOUND",
                error_message=f"No adapter registered for {ai_id}",
            )

        # Check circuit breaker
        cb = self._circuit_breakers.get(ai_id)
        if cb and not cb.should_allow():
            return AIResponse(
                success=False,
                ai_id=ai_id,
                task_id="",
                content="",
                error_code="CIRCUIT_OPEN",
                error_message=f"Circuit breaker is open for {ai_id}",
            )

        # Check rate limiter
        if not self._rate_limiter.allow(ai_id):
            return AIResponse(
                success=False,
                ai_id=ai_id,
                task_id="",
                content="",
                error_code="RATE_LIMITED",
                error_message=f"Rate limit exceeded for {ai_id}",
            )

        # Execute
        try:
            response = await adapter.send_prompt(prompt, options)
            event_task_id = task_id or response.task_id
            if response.success:
                if cb:
                    cb.record_success()
                self._rate_limiter.record(ai_id)
                await self._event_bus.emit(
                    "ai:task:completed",
                    task_id=event_task_id,
                    ai_id=ai_id,
                    response=response,
                )
            else:
                if cb:
                    cb.record_failure()
                await self._event_bus.emit(
                    "ai:task:failed",
                    task_id=event_task_id,
                    ai_id=ai_id,
                    error=response.error_message or "Unknown error",
                )
            return response
        except Exception as e:
            if cb:
                cb.record_failure()
            logger.exception("Error sending to %s", ai_id)
            return AIResponse(
                success=False,
                ai_id=ai_id,
                task_id="",
                content="",
                error_code="INTERNAL_ERROR",
                error_message=str(e),
            )

    async def send_to_multiple(
        self,
        ai_ids: list[str],
        prompt: str,
        options: SubmitOptions | None = None,
        task_id: str = "",
    ) -> dict[str, AIResponse]:
        """Send a prompt to multiple AIs in true parallel.

        Returns a dict of ai_id -> AIResponse.
        task_id: the scheduler's task_id for event correlation.
        """
        coros = [self.send_to_ai(ai_id, prompt, options, task_id=task_id) for ai_id in ai_ids]
        responses = await asyncio.gather(*coros, return_exceptions=True)

        results: dict[str, AIResponse] = {}
        for ai_id, response in zip(ai_ids, responses, strict=False):
            if isinstance(response, Exception):
                logger.exception("Error in send_to_multiple for %s", ai_id)
                results[ai_id] = AIResponse(
                    success=False,
                    ai_id=ai_id,
                    task_id="",
                    content="",
                    error_code="INTERNAL_ERROR",
                    error_message=str(response),
                )
            else:
                results[ai_id] = response

        return results

    async def stop_generation(self, ai_id: str) -> None:
        """Stop generation for a specific AI."""
        adapter = self._provider_manager.get(ai_id)
        if adapter:
            await adapter.stop_generation()
