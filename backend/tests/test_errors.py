"""Unit tests for shared/errors.py."""

from __future__ import annotations


from shared.errors import (
    OmniCouncilError,
    AIAdapterError,
    AIConnectionError,
    AITimeoutError,
    AILoginRequiredError,
    AICaptchaError,
    CircuitOpenError,
    RateLimitError,
    SelectorError,
    SchedulerError,
    TaskValidationError,
    NoAvailableAIError,
    CollectorError,
    CollectionTimeoutError,
    AnalysisError,
    InsufficientResultsError,
)


class TestOmniCouncilError:
    def test_base_error(self):
        e = OmniCouncilError("CODE", "message", recoverable=True)
        assert e.code == "CODE"
        assert e.message == "message"
        assert e.recoverable is True
        assert "[CODE]" in str(e)


class TestLayer1Errors:
    def test_ai_connection_error(self):
        e = AIConnectionError("deepseek", "connection refused")
        assert e.code == "AI_CONNECTION_ERROR"
        assert e.recoverable is True
        assert "deepseek" in e.message

    def test_ai_timeout_error(self):
        e = AITimeoutError("deepseek", 5000)
        assert e.code == "AI_TIMEOUT"
        assert "5000" in e.message
        assert e.recoverable is True

    def test_ai_login_required_error(self):
        e = AILoginRequiredError("deepseek")
        assert e.code == "LOGIN_REQUIRED"
        assert e.recoverable is False

    def test_ai_captcha_error(self):
        e = AICaptchaError("deepseek")
        assert e.code == "CAPTCHA_REQUIRED"
        assert e.recoverable is True

    def test_circuit_open_error(self):
        e = CircuitOpenError("deepseek")
        assert e.code == "CIRCUIT_OPEN"
        assert e.recoverable is True

    def test_rate_limit_error(self):
        e = RateLimitError("deepseek")
        assert e.code == "RATE_LIMITED"
        assert e.recoverable is True

    def test_selector_error(self):
        e = SelectorError("deepseek", "input box")
        assert e.code == "SELECTOR_ALL_FAILED"
        assert "input box" in e.message
        assert e.recoverable is False


class TestLayer2Errors:
    def test_task_validation_error(self):
        e = TaskValidationError("empty query")
        assert e.code == "TASK_VALIDATION_ERROR"
        assert e.recoverable is False

    def test_no_available_ai_error(self):
        e = NoAvailableAIError()
        assert e.code == "NO_AVAILABLE_AI"
        assert e.recoverable is False


class TestLayer3Errors:
    def test_collection_timeout_error(self):
        e = CollectionTimeoutError("task_123")
        assert e.code == "COLLECTION_TIMEOUT"
        assert "task_123" in e.message
        assert e.recoverable is True


class TestLayer4Errors:
    def test_insufficient_results_error(self):
        e = InsufficientResultsError(1, 2)
        assert e.code == "INSUFFICIENT_RESULTS"
        assert "1" in e.message
        assert "2" in e.message
        assert e.recoverable is False


class TestInheritance:
    def test_ai_errors_inherit_adapter_error(self):
        assert issubclass(AIConnectionError, AIAdapterError)
        assert issubclass(AITimeoutError, AIAdapterError)
        assert issubclass(AILoginRequiredError, AIAdapterError)
        assert issubclass(AICaptchaError, AIAdapterError)

    def test_scheduler_errors_inherit(self):
        assert issubclass(TaskValidationError, SchedulerError)
        assert issubclass(NoAvailableAIError, SchedulerError)

    def test_collector_errors_inherit(self):
        assert issubclass(CollectionTimeoutError, CollectorError)

    def test_analysis_errors_inherit(self):
        assert issubclass(InsufficientResultsError, AnalysisError)
