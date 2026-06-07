"""OmniCouncil unified error classification.

All provider and engine modules should raise exceptions from this hierarchy
so that SessionManager / retry logic / degradation decisions can act on the
**type** of error rather than string-matching ``error_code``.
"""

from __future__ import annotations

from enum import StrEnum


class ErrorSeverity(StrEnum):
    LOW = "low"          # Informational, no user impact
    MEDIUM = "medium"    # Affects one AI, others continue
    HIGH = "high"        # Affects the current task, may need retry
    CRITICAL = "critical"  # System-level, requires restart/re-auth


class OmniError(Exception):
    """Base exception for all OmniCouncil errors."""

    def __init__(self, message: str = "", severity: ErrorSeverity = ErrorSeverity.MEDIUM) -> None:
        self.severity = severity
        super().__init__(message)


class SessionExpiredError(OmniError):
    """Raised when an AI provider's login session has expired.

    Severity: HIGH — the provider cannot accept queries until re-authenticated.
    """

    def __init__(self, provider_id: str, message: str = "") -> None:
        self.provider_id = provider_id
        super().__init__(
            message or f"{provider_id}: login session expired",
            severity=ErrorSeverity.HIGH,
        )


class CloudflareBlockedError(OmniError):
    """Raised when Cloudflare challenge blocks page access."""

    def __init__(self, provider_id: str) -> None:
        self.provider_id = provider_id
        super().__init__(
            f"{provider_id}: blocked by Cloudflare challenge",
            severity=ErrorSeverity.HIGH,
        )


class NavigationError(OmniError):
    """Raised when the browser cannot navigate to the chat URL."""

    def __init__(self, provider_id: str, url: str, detail: str = "") -> None:
        self.provider_id = provider_id
        super().__init__(
            f"{provider_id}: navigation failed to {url} — {detail}",
            severity=ErrorSeverity.HIGH,
        )


class ExtractionError(OmniError):
    """Raised when the AI response could not be extracted from the page."""

    def __init__(self, provider_id: str, detail: str = "") -> None:
        self.provider_id = provider_id
        super().__init__(
            f"{provider_id}: response extraction failed — {detail}",
            severity=ErrorSeverity.MEDIUM,
        )


class ProviderTimeoutError(OmniError):
    """Raised when an AI provider does not respond within the configured timeout."""

    def __init__(self, provider_id: str, timeout_s: int) -> None:
        self.provider_id = provider_id
        super().__init__(
            f"{provider_id}: timed out after {timeout_s}s",
            severity=ErrorSeverity.MEDIUM,
        )


class ProviderUnavailableError(OmniError):
    """Raised when a provider is in a degraded/unhealthy state."""

    def __init__(self, provider_id: str, reason: str = "") -> None:
        self.provider_id = provider_id
        super().__init__(
            f"{provider_id}: unavailable — {reason}",
            severity=ErrorSeverity.HIGH,
        )


__all__ = [
    "ErrorSeverity",
    "OmniError",
    "SessionExpiredError",
    "CloudflareBlockedError",
    "NavigationError",
    "ExtractionError",
    "ProviderTimeoutError",
    "ProviderUnavailableError",
]
