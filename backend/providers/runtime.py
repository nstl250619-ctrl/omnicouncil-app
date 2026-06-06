"""ProviderRuntime — unified provider lifecycle management OS.

Central orchestrator for all provider operations.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from providers.event_bus import (
    PROVIDER_HEALTH_CHANGED,
    PROVIDER_LOGIN_FAILED,
    PROVIDER_LOGIN_SUCCESS,
    PROVIDER_REGISTERED,
    PROVIDER_SESSION_EXPIRED,
    PROVIDER_UNREGISTERED,
    ProviderEventBus,
)
from providers.health_monitor import HealthReport, HealthStatus, ProviderHealthMonitor
from providers.registry_v2 import ProviderRegistryV2
from providers.session_manager import ProviderSessionManager
from shared.types import AIStatus

if TYPE_CHECKING:
    from providers.base.provider import BaseProvider

logger = logging.getLogger(__name__)


class ProviderRuntime:
    """Provider Runtime OS — unified lifecycle management.

    Components:
    - registry: provider registration and lookup
    - session: login persistence and restore
    - health: health monitoring
    - eventbus: provider-level events
    """

    def __init__(self) -> None:
        self.registry = ProviderRegistryV2()
        self.session = ProviderSessionManager()
        self.health = ProviderHealthMonitor()
        self.eventbus = ProviderEventBus()
        self._initialized: set[str] = set()

    # ========== Registration ==========

    async def register(self, provider: BaseProvider) -> None:
        """Register a provider and initialize its lifecycle."""
        pid = provider.ai_id
        self.registry.register(provider)
        self.registry.set_status(pid, AIStatus.INITIALIZING)
        await self.eventbus.emit(PROVIDER_REGISTERED, provider_id=pid)

    async def unregister(self, provider_id: str) -> None:
        """Safely unregister a provider."""
        provider = self.registry.get(provider_id)
        if provider:
            try:
                await provider.destroy()
            except Exception:
                pass
        self.registry.unregister(provider_id)
        self._initialized.discard(provider_id)
        await self.eventbus.emit(PROVIDER_UNREGISTERED, provider_id=provider_id)

    async def reload(self, provider_id: str, new_provider: BaseProvider) -> bool:
        """Hot-swap a provider at runtime."""
        old = self.registry.get(provider_id)
        if old:
            try:
                await old.destroy()
            except Exception:
                pass
        self.registry.register(new_provider)
        self.registry.set_status(provider_id, AIStatus.INITIALIZING)
        try:
            await new_provider.initialize()
            self.registry.set_status(provider_id, AIStatus.READY)
            self._initialized.add(provider_id)
            logger.info("Provider %s: reloaded successfully", provider_id)
            return True
        except Exception as e:
            self.registry.set_status(provider_id, AIStatus.ERROR)
            logger.exception("Provider %s: reload failed", provider_id)
            return False

    # ========== Lifecycle ==========

    async def initialize_all(self) -> None:
        """Initialize all registered providers."""
        for provider in self.registry.get_all():
            await self._initialize_one(provider)

    async def _initialize_one(self, provider: BaseProvider) -> bool:
        pid = provider.ai_id
        try:
            await provider.initialize()
            self.registry.set_status(pid, AIStatus.READY)
            self._initialized.add(pid)
            logger.info("Provider %s: initialized", pid)
            return True
        except Exception as e:
            self.registry.set_status(pid, AIStatus.ERROR)
            logger.exception("Provider %s: initialize failed", pid)
            return False

    async def destroy_all(self) -> None:
        """Destroy all providers."""
        for provider in self.registry.get_all():
            try:
                await provider.destroy()
            except Exception:
                pass
        self._initialized.clear()

    # ========== Send (with lifecycle protection) ==========

    async def send(self, provider_id: str, prompt: str, timeout_ms: int = 120000) -> str:
        """Send prompt through the runtime lifecycle.

        Handles: status check → health check → auto login → send → error isolation.
        """
        provider = self.registry.get(provider_id)
        if not provider:
            raise ValueError(f"Provider {provider_id} not registered")

        # Status check
        status = self.registry.get_status(provider_id)
        if status == AIStatus.ERROR:
            # Try to recover
            if not await self._initialize_one(provider):
                raise RuntimeError(f"Provider {provider_id} in error state")

        # Auto login fallback
        if status == AIStatus.LOGIN_REQUIRED or not provider.is_authenticated():
            login_ok, login_err = await provider.login()
            if login_ok:
                self.registry.set_status(provider_id, AIStatus.READY)
                await self.eventbus.emit(PROVIDER_LOGIN_SUCCESS, provider_id=provider_id)
            else:
                await self.eventbus.emit(PROVIDER_LOGIN_FAILED, provider_id=provider_id, error=login_err)
                raise RuntimeError(f"Provider {provider_id} login failed: {login_err}")

        # Send
        self.registry.set_status(provider_id, AIStatus.BUSY)
        try:
            from shared.types import SubmitOptions
            response = await provider.send_prompt(prompt, SubmitOptions(timeout_ms=timeout_ms))
            if response.success:
                self.registry.set_status(provider_id, AIStatus.READY)
                return response.content
            else:
                self.registry.set_status(provider_id, AIStatus.ERROR)
                raise RuntimeError(f"Provider {provider_id} send failed: {response.error_message}")
        except Exception as e:
            self.registry.set_status(provider_id, AIStatus.ERROR)
            raise

    # ========== Health ==========

    async def health_check(self, provider_id: str) -> HealthReport:
        """Run health check on a single provider."""
        provider = self.registry.get(provider_id)
        if not provider:
            return HealthReport(provider_id=provider_id, status=HealthStatus.FAILED, error="not registered")

        report = await self.health.check(provider)

        # Update status based on health
        if report.status == HealthStatus.FAILED:
            self.registry.set_status(provider_id, AIStatus.ERROR)
            if report.login_valid is False:
                self.registry.set_status(provider_id, AIStatus.LOGIN_REQUIRED)
                await self.eventbus.emit(PROVIDER_SESSION_EXPIRED, provider_id=provider_id)

        return report

    async def health_check_all(self) -> dict[str, HealthReport]:
        """Run health check on all providers."""
        for provider in self.registry.get_all():
            await self.health_check(provider.ai_id)
        return self.health.get_all_reports()

    # ========== Config export ==========

    def get_configs(self) -> list[dict[str, Any]]:
        return self.registry.get_configs()

    def get_ids(self) -> list[str]:
        return self.registry.get_ids()

    def get_all(self) -> list[BaseProvider]:
        return self.registry.get_all()
