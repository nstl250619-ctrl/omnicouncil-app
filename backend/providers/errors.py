"""Unified Provider error model."""

from __future__ import annotations


class ProviderError(Exception):
    """Base provider error."""

    def __init__(self, code: str, message: str, provider_id: str = "", recoverable: bool = True) -> None:
        self.code = code
        self.message = message
        self.provider_id = provider_id
        self.recoverable = recoverable
        super().__init__(f"[{code}] {provider_id}: {message}")


class LoginRequiredError(ProviderError):
    def __init__(self, provider_id: str = "") -> None:
        super().__init__("LOGIN_REQUIRED", "Login required", provider_id, recoverable=True)


class ProviderTimeoutError(ProviderError):
    def __init__(self, provider_id: str = "", timeout_ms: int = 0) -> None:
        super().__init__("TIMEOUT", f"Timed out after {timeout_ms}ms", provider_id, recoverable=True)


class ExtractionFailedError(ProviderError):
    def __init__(self, provider_id: str = "", reason: str = "") -> None:
        super().__init__("EXTRACTION_FAILED", f"Response extraction failed: {reason}", provider_id, recoverable=True)


class SessionInvalidError(ProviderError):
    def __init__(self, provider_id: str = "") -> None:
        super().__init__("SESSION_INVALID", "Session expired or invalid", provider_id, recoverable=True)


class ProviderDisabledError(ProviderError):
    def __init__(self, provider_id: str = "") -> None:
        super().__init__("PROVIDER_DISABLED", "Provider is disabled", provider_id, recoverable=False)
