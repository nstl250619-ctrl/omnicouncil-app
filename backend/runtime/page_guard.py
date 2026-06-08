"""PageGuard — central page lifecycle guard for AIRuntimeEngine.

Phase 7 remediation (P1-3): the four state fields
(``_lease_lock``, ``_recovery_in_progress``, ``_pending_evict``,
``_query_ref_count``) used to be private attributes on
``AIRuntimeEngine`` that were mutated by both ``acquire_page()`` and
``RecoveryEngine.recover()``.  This is fragile — there was no type
system, no contract, and renaming a field would silently break both
sides.

This module introduces ``PageGuard``, a small stateful object that
encapsulates the four guards and exposes them through a typed API.
Both ``acquire_page()`` and ``RecoveryEngine.recover()`` now go
through ``PageGuard``, so any future change to the guard semantics
happens in one place.

Public surface::

    guard = PageGuard(platform="deepseek", metrics=metrics)

    # Inside acquire_page()
    if not guard.can_acquire():
        raise PageBusyError(...)
    async with guard.lease(timeout=30.0):
        ...

    # Inside RecoveryEngine.recover()
    if not await guard.wait_until_idle(timeout=5.0):
        guard.mark_busy()  # for forward recovery
        raise RecoveryBusyError(...)
    guard.mark_recovery()
    try:
        ...  # strategy chain
    finally:
        guard.clear_recovery()

    # Inside eviction
    guard.mark_evict()
    try:
        ...  # close page
    finally:
        guard.clear_evict()
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import TYPE_CHECKING

from engine.contracts import (
    PageBusyError,
    PageBusyState,
    RecoveryBusyError,
)

if TYPE_CHECKING:
    from engine.contracts import RuntimeMetrics


class PageGuard:
    """Central state machine for a single Page's lease / recovery / evict."""

    def __init__(
        self,
        *,
        platform: str,
        metrics: RuntimeMetrics,
        recovery_busy_timeout_s: float = 5.0,
    ) -> None:
        self._platform = platform
        self._metrics = metrics
        self._recovery_busy_timeout_s = recovery_busy_timeout_s

        # The four guards
        self._lease_lock: asyncio.Lock = asyncio.Lock()
        self._recovery_in_progress: bool = False
        self._pending_evict: bool = False
        self._query_ref_count: int = 0

        # Page state machine (orthogonal to RuntimeState)
        self._state: PageBusyState = PageBusyState.IDLE

    # ── State queries ───────────────────────────────────────

    @property
    def state(self) -> PageBusyState:
        return self._state

    @property
    def query_ref_count(self) -> int:
        return self._query_ref_count

    @property
    def recovery_in_progress(self) -> bool:
        return self._recovery_in_progress

    @property
    def is_leased(self) -> bool:
        return self._lease_lock.locked()

    @property
    def is_pending_evict(self) -> bool:
        return self._pending_evict

    def can_acquire(self) -> bool:
        """True iff a new lease can be issued right now."""
        return (
            not self._recovery_in_progress
            and not self._pending_evict
        )

    # ── Lease API ───────────────────────────────────────────

    @contextlib.asynccontextmanager
    async def lease(self, *, timeout: float = 30.0):
        """Acquire the page lease.  Raises ``PageBusyError`` on failure."""
        if self._recovery_in_progress:
            self._metrics.page_busy_rejections += 1
            raise PageBusyError(self._platform, "runtime is under recovery")
        if self._pending_evict:
            self._metrics.page_busy_rejections += 1
            raise PageBusyError(self._platform, "page is being evicted")
        try:
            await asyncio.wait_for(self._lease_lock.acquire(), timeout=timeout)
        except asyncio.TimeoutError as exc:
            self._metrics.page_busy_rejections += 1
            raise PageBusyError(
                self._platform,
                f"lease acquisition timed out after {timeout:.1f}s",
            ) from exc
        self._query_ref_count += 1
        self._metrics.page_lease_acquired += 1
        self._state = PageBusyState.LEASED
        try:
            yield
        finally:
            self._query_ref_count = max(0, self._query_ref_count - 1)
            self._metrics.page_lease_released += 1
            if self._query_ref_count == 0 and not self._recovery_in_progress:
                self._state = PageBusyState.IDLE
            if self._lease_lock.locked():
                self._lease_lock.release()

    # ── Recovery API ────────────────────────────────────────

    async def wait_until_idle(self, *, timeout: float | None = None) -> bool:
        """Wait for the page to become idle (lease released).

        Returns True if idle, False on timeout.  Recovery uses this
        to ensure no query is in flight before tearing down the page.
        """
        deadline_s = timeout if timeout is not None else self._recovery_busy_timeout_s
        deadline = time.time() + deadline_s
        start = time.time()
        while self._lease_lock.locked() and time.time() < deadline:
            await asyncio.sleep(0.05)
        int((time.time() - start) * 1000)
        if self._lease_lock.locked():
            return False
        return True

    def mark_recovery(self) -> None:
        """Set the recovery flag.  After this, new ``lease()`` calls
        are refused with ``PageBusyError`` until ``clear_recovery()``."""
        if not self._recovery_in_progress:
            self._recovery_in_progress = True
            self._metrics.recovery_started += 1
            self._state = PageBusyState.RECOVERING

    def clear_recovery(self, *, succeeded: bool = True) -> None:
        """Clear the recovery flag.  Increments success/failure metric."""
        if self._recovery_in_progress:
            self._recovery_in_progress = False
            if succeeded:
                self._metrics.recovery_succeeded += 1
            else:
                self._metrics.recovery_failed += 1
            if self._query_ref_count == 0 and not self._pending_evict:
                self._state = PageBusyState.IDLE

    async def guard_recovery(self, *, timeout: float = 5.0) -> None:
        """Combined "wait for idle + mark recovery" operation.

        This is what ``RecoveryEngine.recover()`` calls at the start.
        Raises ``RecoveryBusyError`` if the page is still leased after
        the timeout, otherwise sets the recovery flag.

        Usage::

            await guard.guard_recovery(timeout=5.0)
            try:
                ...  # strategy chain
            finally:
                guard.clear_recovery(succeeded=...)
        """
        waited_ms = 0
        start = time.time()
        deadline = time.time() + timeout
        while self._lease_lock.locked() and time.time() < deadline:
            await asyncio.sleep(0.05)
        waited_ms = int((time.time() - start) * 1000)
        if self._lease_lock.locked():
            # Still busy — abort
            self._metrics.recovery_aborted_busy += 1
            self._metrics.recovery_failed += 1
            raise RecoveryBusyError(self._platform, waited_ms)
        self.mark_recovery()

    # ── Eviction API ────────────────────────────────────────

    def mark_evict(self) -> None:
        """Raise the pending-evict flag.  New ``lease()`` calls are
        refused until ``clear_evict()``."""
        if not self._pending_evict:
            self._pending_evict = True
            self._state = PageBusyState.EVICTING
            self._metrics.eviction_started += 1

    def clear_evict(self) -> None:
        """Lower the pending-evict flag.  Resets state to IDLE."""
        if self._pending_evict:
            self._pending_evict = False
            self._metrics.eviction_completed += 1
            if (
                self._query_ref_count == 0
                and not self._recovery_in_progress
            ):
                self._state = PageBusyState.IDLE
