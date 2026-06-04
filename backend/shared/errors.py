"""Unified error types for OmniCouncil."""

from __future__ import annotations


class OmniCouncilError(Exception):
    """Base exception for all OmniCouncil errors."""

    def __init__(self, code: str, message: str, recoverable: bool = False) -> None:
        self.code = code
        self.message = message
        self.recoverable = recoverable
        super().__init__(f"[{code}] {message}")


# ========== Layer 1 Errors ==========

class AIAdapterError(OmniCouncilError):
    """Error from AI adapter operations."""
    pass


class AIConnectionError(AIAdapterError):
    """Failed to connect to AI website."""

    def __init__(self, ai_id: str, message: str) -> None:
        super().__init__("AI_CONNECTION_ERROR", f"{ai_id}: {message}", recoverable=True)


class AITimeoutError(AIAdapterError):
    """AI response timed out."""

    def __init__(self, ai_id: str, timeout_ms: int) -> None:
        super().__init__("AI_TIMEOUT", f"{ai_id}: timed out after {timeout_ms}ms", recoverable=True)


class AILoginRequiredError(AIAdapterError):
    """AI website requires login."""

    def __init__(self, ai_id: str) -> None:
        super().__init__("LOGIN_REQUIRED", f"{ai_id}: login required", recoverable=False)


class AICaptchaError(AIAdapterError):
    """AI website shows captcha."""

    def __init__(self, ai_id: str) -> None:
        super().__init__("CAPTCHA_REQUIRED", f"{ai_id}: captcha detected", recoverable=True)


class CircuitOpenError(AIAdapterError):
    """Circuit breaker is open."""

    def __init__(self, ai_id: str) -> None:
        super().__init__("CIRCUIT_OPEN", f"{ai_id}: circuit breaker is open", recoverable=True)


class RateLimitError(AIAdapterError):
    """Rate limit exceeded."""

    def __init__(self, ai_id: str) -> None:
        super().__init__("RATE_LIMITED", f"{ai_id}: rate limit exceeded", recoverable=True)


class SelectorError(AIAdapterError):
    """All selector fallbacks failed."""

    def __init__(self, ai_id: str, element: str) -> None:
        super().__init__("SELECTOR_ALL_FAILED", f"{ai_id}: could not find {element}", recoverable=False)


# ========== Layer 2 Errors ==========

class SchedulerError(OmniCouncilError):
    """Error from scheduler operations."""
    pass


class TaskValidationError(SchedulerError):
    """Invalid task request."""

    def __init__(self, message: str) -> None:
        super().__init__("TASK_VALIDATION_ERROR", message, recoverable=False)


class NoAvailableAIError(SchedulerError):
    """No AI available for the request."""

    def __init__(self) -> None:
        super().__init__("NO_AVAILABLE_AI", "No AI available", recoverable=False)


# ========== Layer 3 Errors ==========

class CollectorError(OmniCouncilError):
    """Error from result collector."""
    pass


class CollectionTimeoutError(CollectorError):
    """Collection timed out."""

    def __init__(self, task_id: str) -> None:
        super().__init__("COLLECTION_TIMEOUT", f"Task {task_id}: collection timed out", recoverable=True)


# ========== Layer 4 Errors ==========

class AnalysisError(OmniCouncilError):
    """Error from comparison analysis."""
    pass


class InsufficientResultsError(AnalysisError):
    """Not enough AI results for analysis."""

    def __init__(self, success_count: int, min_required: int) -> None:
        super().__init__(
            "INSUFFICIENT_RESULTS",
            f"Need at least {min_required} successful results, got {success_count}",
            recoverable=False,
        )
