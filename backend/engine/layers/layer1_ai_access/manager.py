"""AIAccessManager — unified AI access with RuntimeRegistry integration.

This is the *only* AI access interface in V2:
    - Uses ``RuntimeRegistry`` to get ``AIRuntimeEngine`` instances.
    - Calls ``runtime.ensure_ready()`` to get a ``Page``.
    - Passes the ``Page`` to ``QueryAdapter.execute()``.
    - Does NOT handle login recovery (Runtime Engine does that).

Layer 2 (Scheduler) depends ONLY on this class.

Phase 7 remediation (P0-1): the legacy V1 ``AIAccessManager`` (with
``ProviderManager`` / ``BaseProvider``) and the V2 ``AIAccessManagerV2``
have been **merged** into this single ``AIAccessManager`` class.
The "_v2" suffix has been dropped — there is no V1 fallback path.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from shared.event_bus import EventBus
from shared.types import AIResponse, AIStatus, ProviderStatus, SubmitOptions

from .managers.circuit_breaker import CircuitBreaker
from .managers.rate_limiter import RateLimiter

if TYPE_CHECKING:
    from providers.base.query_adapter import BaseQueryAdapter
    from runtime.registry import RuntimeRegistry

logger = logging.getLogger(__name__)


class AIAccessManager:
    """Unified AI access interface (V2-only).

    Provides: send_to_ai, get_ready_ais
    Layer 2 (Scheduler) depends ONLY on this class.
    """

    def __init__(
        self,
        runtime_registry: RuntimeRegistry,
        query_adapters: dict[str, BaseQueryAdapter],
        event_bus: EventBus | None = None,
    ) -> None:
        self._runtime_registry = runtime_registry
        self._query_adapters = query_adapters
        self._rate_limiter = RateLimiter()
        self._circuit_breakers: dict[str, CircuitBreaker] = {}
        self._event_bus = event_bus or EventBus()

        # Initialize circuit breakers for all registered platforms
        for platform in runtime_registry.get_platforms():
            self._circuit_breakers[platform] = CircuitBreaker(
                ai_id=platform,
                on_state_change=lambda ai_id, old, new: logger.info(
                    "Circuit breaker %s: %s -> %s", ai_id, old.value, new.value
                ),
            )

    def get_ready_ais(self) -> list[ProviderStatus]:
        """Get status of all registered AIs."""
        statuses = []
        for platform in self._runtime_registry.get_platforms():
            engine = self._runtime_registry.get(platform)
            if engine is None:
                continue
            from engine.contracts import RuntimeState
            state = engine.state
            if state == RuntimeState.READY:
                ai_status = AIStatus.READY
            elif state == RuntimeState.LOGIN_REQUIRED:
                ai_status = AIStatus.LOGIN_REQUIRED
            elif state == RuntimeState.RECOVERING:
                ai_status = AIStatus.BUSY
            else:
                ai_status = AIStatus.ERROR

            adapter = self._query_adapters.get(platform)
            display_name = adapter.config().display_name if adapter else platform

            statuses.append(ProviderStatus(
                ai_id=platform,
                ai_name=display_name,
                status=ai_status,
            ))
        return statuses

    def get_provider_status(self, ai_id: str) -> ProviderStatus | None:
        """Get status of a specific AI."""
        for s in self.get_ready_ais():
            if s.ai_id == ai_id:
                return s
        return None

    async def send_to_ai(
        self,
        ai_id: str,
        prompt: str,
        options: SubmitOptions | None = None,
        task_id: str = "",
    ) -> AIResponse:
        """Send a prompt to a single AI.

        Flow:
            1. Check circuit breaker.
            2. Check rate limiter.
            3. Get runtime from registry.
            4. Call runtime.ensure_ready() → get Page.
            5. Call query_adapter.execute(page, prompt) → get result.
        """
        # Check circuit breaker
        cb = self._circuit_breakers.get(ai_id)
        if cb and not cb.should_allow():
            return AIResponse(
                success=False, ai_id=ai_id, task_id=task_id,
                content="", error_code="CIRCUIT_OPEN",
                error_message=f"Circuit breaker is open for {ai_id}",
            )

        # Check rate limiter
        if not self._rate_limiter.allow(ai_id):
            return AIResponse(
                success=False, ai_id=ai_id, task_id=task_id,
                content="", error_code="RATE_LIMITED",
                error_message=f"Rate limit exceeded for {ai_id}",
            )

        # Get runtime engine
        engine = self._runtime_registry.get(ai_id)
        if engine is None:
            return AIResponse(
                success=False, ai_id=ai_id, task_id=task_id,
                content="", error_code="RUNTIME_NOT_FOUND",
                error_message=f"No runtime registered for {ai_id}",
            )

        # Get query adapter
        adapter = self._query_adapters.get(ai_id)
        if adapter is None:
            return AIResponse(
                success=False, ai_id=ai_id, task_id=task_id,
                content="", error_code="ADAPTER_NOT_FOUND",
                error_message=f"No query adapter registered for {ai_id}",
            )

        # Ensure runtime is ready (may trigger recovery)
        try:
            from engine.contracts import RuntimeState
            state = await engine.ensure_ready()
            if state != RuntimeState.READY:
                return AIResponse(
                    success=False, ai_id=ai_id, task_id=task_id,
                    content="", error_code="RUNTIME_NOT_READY",
                    error_message=f"Runtime for {ai_id} is in state {state.value}",
                )
        except Exception as exc:
            if cb:
                cb.record_failure()
            return AIResponse(
                success=False, ai_id=ai_id, task_id=task_id,
                content="", error_code="RUNTIME_ERROR",
                error_message=str(exc),
            )

        # Acquire the page via Page Lease (V2)
        try:
            async with engine.acquire_page(timeout=30.0) as page:
                # Execute query via adapter
                try:
                    result = await adapter.execute(page, prompt, options)
                    if result.success:
                        if cb:
                            cb.record_success()
                        self._rate_limiter.record(ai_id)
                        return AIResponse(
                            success=True, ai_id=ai_id, task_id=task_id,
                            content=result.content or "",
                            model=ai_id,
                            duration=result.elapsed_seconds,
                        )
                    else:
                        if cb:
                            cb.record_failure()
                        return AIResponse(
                            success=False, ai_id=ai_id, task_id=task_id,
                            content="", error_code=result.state.value,
                            error_message=result.error or "Query failed",
                        )
                except Exception as exc:
                    if cb:
                        cb.record_failure()
                    logger.exception("Error sending to %s", ai_id)
                    return AIResponse(
                        success=False, ai_id=ai_id, task_id=task_id,
                        content="", error_code="INTERNAL_ERROR",
                        error_message=str(exc),
                    )
        except Exception as exc:
            # PageBusyError, RuntimeNotReadyError, etc.
            from engine.contracts import PageBusyError, RuntimeNotReadyError
            if isinstance(exc, PageBusyError):
                code = "PAGE_BUSY"
            elif isinstance(exc, RuntimeNotReadyError):
                code = "RUNTIME_NOT_READY"
            else:
                code = "PAGE_ERROR"
            if cb:
                cb.record_failure()
            return AIResponse(
                success=False, ai_id=ai_id, task_id=task_id,
                content="", error_code=code,
                error_message=str(exc),
            )

    async def stop_generation(self, ai_id: str) -> None:
        """Stop generation for a specific AI."""
        adapter = self._query_adapters.get(ai_id)
        if adapter:
            engine = self._runtime_registry.get(ai_id)
            if engine:
                try:
                    async with engine.acquire_page(timeout=5.0) as page:
                        await adapter.abort_current(page)
                except Exception:
                    pass
