"""Unit tests for Layer 1: AI Access components."""

from __future__ import annotations

import asyncio
import time

import pytest

from shared.types import AIStatus, CircuitState
from engine.layers.layer1_ai_access.managers.circuit_breaker import CircuitBreaker
from engine.layers.layer1_ai_access.managers.rate_limiter import RateLimiter
from engine.layers.layer1_ai_access.managers.provider_manager import ProviderManager
from engine.layers.layer1_ai_access.response_normalizer import ResponseNormalizer


class TestCircuitBreaker:
    def test_initial_state_closed(self):
        cb = CircuitBreaker(ai_id="test")
        assert cb.state == CircuitState.CLOSED
        assert cb.should_allow() is True

    def test_records_failure(self):
        cb = CircuitBreaker(ai_id="test", failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.should_allow() is False

    def test_half_open_after_cooldown(self):
        cb = CircuitBreaker(ai_id="test", failure_threshold=1, cooldown_seconds=0.01)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        time.sleep(0.02)
        assert cb.should_allow() is True
        assert cb.state == CircuitState.HALF_OPEN

    def test_success_closes_circuit(self):
        cb = CircuitBreaker(ai_id="test", failure_threshold=1, cooldown_seconds=0.01)
        cb.record_failure()
        time.sleep(0.02)
        cb.should_allow()  # OPEN → HALF_OPEN
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_reset(self):
        cb = CircuitBreaker(ai_id="test", failure_threshold=1)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        cb.reset()
        assert cb.state == CircuitState.CLOSED

    def test_on_state_change_callback(self):
        transitions = []
        cb = CircuitBreaker(
            ai_id="test",
            failure_threshold=1,
            on_state_change=lambda ai, old, new: transitions.append((old, new)),
        )
        cb.record_failure()
        assert len(transitions) == 1


class TestRateLimiter:
    def test_allows_first_request(self):
        rl = RateLimiter()
        assert rl.allow("test") is True

    def test_respects_max_per_minute(self):
        rl = RateLimiter()
        for _ in range(10):
            rl.record("test")
        assert rl.allow("test") is False

    def test_respects_min_interval(self):
        rl = RateLimiter()
        rl.record("test")
        assert rl.allow("test") is False

    def test_reset(self):
        rl = RateLimiter()
        for _ in range(10):
            rl.record("test")
        rl.reset("test")
        assert rl.allow("test") is True

    def test_independent_per_ai(self):
        rl = RateLimiter()
        for _ in range(10):
            rl.record("ai1")
        assert rl.allow("ai2") is True


class TestProviderManager:
    def test_register_and_get(self):
        pm = ProviderManager()

        class FakeAdapter:
            ai_id = "fake"
            ai_name = "Fake"

            def get_status(self):
                return None

        pm.register(FakeAdapter())
        assert pm.get("fake") is not None
        assert pm.get("nonexistent") is None

    def test_get_all(self):
        pm = ProviderManager()

        class A:
            ai_id = "a"
            ai_name = "A"

            def get_status(self):
                return None

        class B:
            ai_id = "b"
            ai_name = "B"

            def get_status(self):
                return None

        pm.register(A())
        pm.register(B())
        assert len(pm.get_all()) == 2

    def test_registered_ids(self):
        pm = ProviderManager()

        class A:
            ai_id = "a"
            ai_name = "A"

            def get_status(self):
                return None

        pm.register(A())
        assert pm.registered_ids == ["a"]


class TestResponseNormalizer:
    def test_normalize_empty(self):
        rn = ResponseNormalizer()
        result = rn.normalize("")
        assert result.main_text == ""
        assert result.word_count == 0

    def test_normalize_paragraphs(self):
        rn = ResponseNormalizer()
        result = rn.normalize("First paragraph.\n\nSecond paragraph.")
        assert len(result.paragraphs) == 2

    def test_normalize_code_blocks(self):
        rn = ResponseNormalizer()
        result = rn.normalize("Text\n```python\nprint(1)\n```\nMore text")
        assert len(result.code_blocks) == 1
        assert result.code_blocks[0] == ("python", "print(1)")

    def test_normalize_markdown_detection(self):
        rn = ResponseNormalizer()
        result = rn.normalize("# Header\n\n**bold** text")
        assert result.has_markdown is True

    def test_normalize_no_markdown(self):
        rn = ResponseNormalizer()
        result = rn.normalize("Just plain text")
        assert result.has_markdown is False

    def test_count_words_cjk(self):
        rn = ResponseNormalizer()
        result = rn.normalize("量子计算")
        assert result.word_count == 4

    def test_count_words_english(self):
        rn = ResponseNormalizer()
        result = rn.normalize("hello world")
        assert result.word_count == 2

    def test_detect_language_chinese(self):
        rn = ResponseNormalizer()
        result = rn.normalize("量子计算是新型计算方式")
        assert result.detected_language == "zh"

    def test_detect_language_english(self):
        rn = ResponseNormalizer()
        result = rn.normalize("Quantum computing is new")
        assert result.detected_language == "en"

    def test_count_words_public_method(self):
        rn = ResponseNormalizer()
        assert rn.count_words("hello world") == 2
        assert rn.count_words("") == 0
