"""Tests for RecoveryEngine and recovery strategies.

Uses mock engine objects to simulate page operations.

Covers:
    - Each strategy: success / failure / timeout
    - Strategy chain execution order
    - Attempt counting and max attempts
    - Cooldown between rounds
    - Event emission (success, failure, ai:unavailable)
    - RecoveryRound / RecoveryAttempt records
    - reset() functionality
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from engine.contracts import (
    RecoveryFailedError,
    RuntimeState,
)
from runtime.recovery_engine import RecoveryAttempt, RecoveryEngine, RecoveryRound
from runtime.recovery_strategies import (
    NewTabStrategy,
    ReloadStrategy,
    RenavigateStrategy,
    RestartBrowserStrategy,
    default_recovery_chain,
)
from shared.types import SessionState

# ============================================================
#  Helpers
# ============================================================


def _mock_engine(
    page_alive: bool = True,
    session_valid: bool = True,
    has_context: bool = True,
    has_playwright: bool = True,
):
    """Create a mock engine object for strategy testing."""
    engine = MagicMock()

    # Page
    page = MagicMock()
    page.is_closed.return_value = not page_alive
    page.reload = AsyncMock()
    page.goto = AsyncMock()
    page.wait_for_timeout = AsyncMock()
    page.close = AsyncMock()
    page.url = "https://chat.deepseek.com"
    engine.get_page.return_value = page

    # Session validator
    sv = MagicMock()
    sv.validate_online = AsyncMock(
        return_value=SessionState.AUTHENTICATED if session_valid else SessionState.LOGIN_REQUIRED
    )
    sv.validate_offline = AsyncMock(
        return_value=SessionState.AUTHENTICATED if session_valid else SessionState.AUTH_EXPIRED
    )
    engine.get_session_validator.return_value = sv

    # Platform config
    config = MagicMock()
    config.home_url = "https://chat.deepseek.com"
    config.headless = True
    config.extra_browser_args = []
    engine.get_platform_config.return_value = config

    # Profile manager
    pm = MagicMock()
    pm.backup = AsyncMock()
    pm.get_profile_path.return_value = MagicMock()
    engine.get_profile_manager.return_value = pm

    # State machine
    sm = MagicMock()
    sm.can_transition.return_value = True
    sm.transition = AsyncMock()
    engine.state_machine = sm

    # Browser context
    if has_context:
        ctx = MagicMock()
        ctx.new_page = AsyncMock(return_value=page)
        ctx.close = AsyncMock()
        engine._context = ctx
    else:
        engine._context = None

    # Playwright
    if has_playwright:
        pw = MagicMock()
        pw.chromium = MagicMock()
        pw.chromium.launch_persistent_context = AsyncMock(return_value=engine._context if has_context else MagicMock())
        engine._playwright = pw
    else:
        engine._playwright = None

    # Internal state
    engine._page = page
    engine._pages = {}

    return engine


# ============================================================
#  1. Individual strategy tests
# ============================================================


class TestReloadStrategy:

    def test_success(self):
        engine = _mock_engine(page_alive=True, session_valid=True)
        strategy = ReloadStrategy()
        result = asyncio.run(strategy.recover(engine, "deepseek"))
        assert result is True

    def test_failure_session_still_invalid(self):
        engine = _mock_engine(page_alive=True, session_valid=False)
        strategy = ReloadStrategy()
        result = asyncio.run(strategy.recover(engine, "deepseek"))
        assert result is False

    def test_failure_page_closed(self):
        engine = _mock_engine(page_alive=False)
        strategy = ReloadStrategy()
        result = asyncio.run(strategy.recover(engine, "deepseek"))
        assert result is False

    def test_timeout(self):
        engine = _mock_engine()
        # Make reload hang
        async def slow_reload(**kwargs):
            await asyncio.sleep(20)
        engine.get_page.return_value.reload = slow_reload
        strategy = ReloadStrategy()
        strategy.timeout_s = 1  # very short timeout
        result = asyncio.run(strategy.recover(engine, "deepseek"))
        assert result is False


class TestRenavigateStrategy:

    def test_success(self):
        engine = _mock_engine(session_valid=True)
        strategy = RenavigateStrategy()
        result = asyncio.run(strategy.recover(engine, "deepseek"))
        assert result is True

    def test_failure(self):
        engine = _mock_engine(session_valid=False)
        strategy = RenavigateStrategy()
        result = asyncio.run(strategy.recover(engine, "deepseek"))
        assert result is False

    def test_page_closed(self):
        engine = _mock_engine(page_alive=False)
        strategy = RenavigateStrategy()
        result = asyncio.run(strategy.recover(engine, "deepseek"))
        assert result is False


class TestNewTabStrategy:

    def test_success(self):
        engine = _mock_engine(has_context=True, session_valid=True)
        strategy = NewTabStrategy()
        result = asyncio.run(strategy.recover(engine, "deepseek"))
        assert result is True

    def test_failure_no_context(self):
        engine = _mock_engine(has_context=False)
        strategy = NewTabStrategy()
        result = asyncio.run(strategy.recover(engine, "deepseek"))
        assert result is False

    def test_failure_session_still_invalid(self):
        engine = _mock_engine(has_context=True, session_valid=False)
        strategy = NewTabStrategy()
        result = asyncio.run(strategy.recover(engine, "deepseek"))
        assert result is False

    def test_swaps_page_on_success(self):
        engine = _mock_engine(has_context=True, session_valid=True)
        old_page = engine.get_page()
        strategy = NewTabStrategy()
        asyncio.run(strategy.recover(engine, "deepseek"))
        # Old page should be closed
        old_page.close.assert_called_once()


class TestRestartBrowserStrategy:

    def test_success(self):
        engine = _mock_engine(has_context=True, has_playwright=True, session_valid=True)
        strategy = RestartBrowserStrategy()
        result = asyncio.run(strategy.recover(engine, "deepseek"))
        assert result is True

    def test_failure_no_playwright(self):
        engine = _mock_engine(has_playwright=False)
        strategy = RestartBrowserStrategy()
        result = asyncio.run(strategy.recover(engine, "deepseek"))
        assert result is False

    def test_failure_session_still_invalid(self):
        engine = _mock_engine(has_context=True, has_playwright=True, session_valid=False)
        strategy = RestartBrowserStrategy()
        result = asyncio.run(strategy.recover(engine, "deepseek"))
        assert result is False

    def test_backs_up_profile(self):
        engine = _mock_engine(has_context=True, has_playwright=True, session_valid=True)
        strategy = RestartBrowserStrategy()
        asyncio.run(strategy.recover(engine, "deepseek"))
        engine.get_profile_manager().backup.assert_called_once_with("deepseek")


# ============================================================
#  2. Default chain
# ============================================================


class TestDefaultChain:

    def test_returns_four_strategies(self):
        chain = default_recovery_chain()
        assert len(chain) == 4
        assert isinstance(chain[0], ReloadStrategy)
        assert isinstance(chain[1], RenavigateStrategy)
        assert isinstance(chain[2], NewTabStrategy)
        assert isinstance(chain[3], RestartBrowserStrategy)

    def test_timeout_values(self):
        chain = default_recovery_chain()
        assert chain[0].timeout_s == 15
        assert chain[1].timeout_s == 20
        assert chain[2].timeout_s == 20
        assert chain[3].timeout_s == 30


# ============================================================
#  3. RecoveryEngine — chain execution
# ============================================================


class TestRecoveryEngine:

    def test_first_strategy_succeeds(self):
        engine = _mock_engine(session_valid=True)
        re = RecoveryEngine(max_attempts=3)
        result = asyncio.run(re.recover(engine, "deepseek"))
        assert result is True
        # Only first strategy should have been tried
        assert len(re.history) == 1
        assert re.history[0].attempts[0].strategy_name == "reload"
        assert re.history[0].attempts[0].success is True

    def test_chain_falls_through(self):
        """All strategies fail → RecoveryFailedError."""
        engine = _mock_engine(session_valid=False, page_alive=False)
        re = RecoveryEngine(max_attempts=1)
        with pytest.raises(RecoveryFailedError):
            asyncio.run(re.recover(engine, "deepseek"))
        assert len(re.history) == 1
        assert len(re.history[0].attempts) == 4  # all 4 tried

    def test_second_strategy_succeeds(self):
        """First strategy fails, second succeeds."""
        engine = _mock_engine(session_valid=True)

        # Make reload fail
        call_count = 0

        async def selective_validate(page):
            nonlocal call_count
            call_count += 1
            if call_count == 1:  # first call (reload) fails
                return SessionState.LOGIN_REQUIRED
            return SessionState.AUTHENTICATED

        engine.get_session_validator().validate_online = selective_validate

        re = RecoveryEngine(max_attempts=3)
        result = asyncio.run(re.recover(engine, "deepseek"))
        assert result is True
        assert re.history[0].attempts[0].success is False
        assert re.history[0].attempts[1].success is True
        assert re.history[0].attempts[1].strategy_name == "renavigate"

    def test_max_attempts_raises(self):
        engine = _mock_engine(session_valid=False, page_alive=False)
        re = RecoveryEngine(max_attempts=2)

        # First round — all fail, returns False
        result = asyncio.run(re.recover(engine, "deepseek"))
        assert result is False

        # Second round — all fail, raises
        with pytest.raises(RecoveryFailedError):
            asyncio.run(re.recover(engine, "deepseek"))

    def test_attempt_counter_resets_on_success(self):
        engine = _mock_engine(session_valid=True)
        re = RecoveryEngine(max_attempts=3)

        asyncio.run(re.recover(engine, "deepseek"))
        assert re.get_attempt_count("deepseek") == 0  # reset on success

    def test_attempt_counter_increments_on_failure(self):
        engine = _mock_engine(session_valid=False, page_alive=False)
        re = RecoveryEngine(max_attempts=3, cooldown_s=0)

        # First round fails
        asyncio.run(re.recover(engine, "deepseek"))
        assert re.get_attempt_count("deepseek") == 1


# ============================================================
#  4. RecoveryEngine — events
# ============================================================


class TestRecoveryEvents:

    def test_emits_succeeded_event(self):
        bus = MagicMock()
        bus.emit = AsyncMock()
        engine = _mock_engine(session_valid=True)
        re = RecoveryEngine(max_attempts=3, event_bus=bus)

        asyncio.run(re.recover(engine, "deepseek"))

        bus.emit.assert_any_call(
            "recovery:succeeded",
            platform="deepseek",
            strategy="reload",
            round_number=1,
        )

    def test_emits_failed_and_unavailable_events(self):
        bus = MagicMock()
        bus.emit = AsyncMock()
        engine = _mock_engine(session_valid=False, page_alive=False)
        re = RecoveryEngine(max_attempts=1, event_bus=bus)

        with pytest.raises(RecoveryFailedError):
            asyncio.run(re.recover(engine, "deepseek"))

        bus.emit.assert_any_call(
            "recovery:failed",
            platform="deepseek",
            attempts=1,
        )
        bus.emit.assert_any_call(
            "ai:unavailable",
            platform="deepseek",
            reason="recovery_exhausted",
        )

    def test_no_event_bus_no_crash(self):
        engine = _mock_engine(session_valid=True)
        re = RecoveryEngine(max_attempts=3, event_bus=None)
        asyncio.run(re.recover(engine, "deepseek"))


# ============================================================
#  5. RecoveryEngine — state transitions
# ============================================================


class TestStateTransitions:

    def test_transitions_to_recovering(self):
        engine = _mock_engine(session_valid=True)
        re = RecoveryEngine(max_attempts=3)
        asyncio.run(re.recover(engine, "deepseek"))

        sm = engine.state_machine
        sm.transition.assert_any_call(
            RuntimeState.RECOVERING, reason="recovery started"
        )

    def test_transitions_to_ready_on_success(self):
        engine = _mock_engine(session_valid=True)
        re = RecoveryEngine(max_attempts=3)
        asyncio.run(re.recover(engine, "deepseek"))

        sm = engine.state_machine
        sm.transition.assert_any_call(
            RuntimeState.READY,
            reason="recovery succeeded via reload",
        )

    def test_transitions_to_unavailable_on_exhaustion(self):
        engine = _mock_engine(session_valid=False, page_alive=False)
        re = RecoveryEngine(max_attempts=1)
        with pytest.raises(RecoveryFailedError):
            asyncio.run(re.recover(engine, "deepseek"))

        sm = engine.state_machine
        sm.transition.assert_any_call(
            RuntimeState.UNAVAILABLE,
            reason="all 1 recovery rounds failed",
        )


# ============================================================
#  6. RecoveryEngine — history
# ============================================================


class TestHistory:

    def test_history_records_rounds(self):
        engine = _mock_engine(session_valid=True)
        re = RecoveryEngine(max_attempts=3)
        asyncio.run(re.recover(engine, "deepseek"))

        assert len(re.history) == 1
        round_rec = re.history[0]
        assert round_rec.platform == "deepseek"
        assert round_rec.round_number == 1
        assert round_rec.succeeded is True
        assert round_rec.final_state == RuntimeState.READY

    def test_history_records_failed_attempts(self):
        engine = _mock_engine(session_valid=False, page_alive=False)
        re = RecoveryEngine(max_attempts=1, cooldown_s=0)
        with pytest.raises(RecoveryFailedError):
            asyncio.run(re.recover(engine, "deepseek"))

        assert len(re.history) == 1
        round_rec = re.history[0]
        assert round_rec.succeeded is False
        assert len(round_rec.attempts) == 4

    def test_history_is_copy(self):
        re = RecoveryEngine()
        h1 = re.history
        h2 = re.history
        assert h1 == h2
        assert h1 is not h2


# ============================================================
#  7. RecoveryEngine — reset
# ============================================================


class TestReset:

    def test_reset_single_platform(self):
        engine = _mock_engine(session_valid=False, page_alive=False)
        re = RecoveryEngine(max_attempts=3, cooldown_s=0)
        asyncio.run(re.recover(engine, "deepseek"))
        assert re.get_attempt_count("deepseek") == 1

        re.reset("deepseek")
        assert re.get_attempt_count("deepseek") == 0

    def test_reset_all(self):
        engine = _mock_engine(session_valid=False, page_alive=False)
        re = RecoveryEngine(max_attempts=3, cooldown_s=0)
        asyncio.run(re.recover(engine, "deepseek"))
        asyncio.run(re.recover(engine, "gemini"))

        re.reset()
        assert re.get_attempt_count("deepseek") == 0
        assert re.get_attempt_count("gemini") == 0


# ============================================================
#  8. RecoveryAttempt / RecoveryRound data classes
# ============================================================


class TestDataClasses:

    def test_recovery_attempt(self):
        attempt = RecoveryAttempt(
            strategy_name="reload",
            platform="deepseek",
            started_at=1.0,
            finished_at=2.0,
            success=True,
        )
        assert attempt.strategy_name == "reload"
        assert attempt.success is True
        assert attempt.timed_out is False

    def test_recovery_round_succeeded(self):
        round_rec = RecoveryRound(
            platform="deepseek",
            round_number=1,
            started_at=1.0,
            attempts=[
                RecoveryAttempt("reload", "deepseek", 1.0, 1.5, False),
                RecoveryAttempt("renavigate", "deepseek", 1.5, 2.5, True),
            ],
        )
        assert round_rec.succeeded is True

    def test_recovery_round_failed(self):
        round_rec = RecoveryRound(
            platform="deepseek",
            round_number=1,
            started_at=1.0,
            attempts=[
                RecoveryAttempt("reload", "deepseek", 1.0, 1.5, False),
                RecoveryAttempt("renavigate", "deepseek", 1.5, 2.5, False),
            ],
        )
        assert round_rec.succeeded is False
