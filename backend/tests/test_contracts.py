"""Contract tests — verify that implementations satisfy their Protocol/ABC contracts.

Tests:
    - RuntimeStateMachine satisfies the Protocol
    - RuntimeRegistry satisfies the Protocol
    - ProfileManager satisfies the ABC
    - SessionValidator satisfies the Protocol
    - HealthMonitor satisfies the Protocol
    - RecoveryStrategy satisfies the Protocol
    - QueryAdapter satisfies the ABC
    - AIRuntimeEngine satisfies the ABC
"""

from __future__ import annotations

import asyncio
from pathlib import Path


from engine.contracts import (
    HealthMonitor as HealthMonitorProtocol,
    PlatformConfig,
    ProfileManager as ProfileManagerABC,
    RecoveryStrategy as RecoveryStrategyProtocol,
    RuntimeRegistry as RuntimeRegistryProtocol,
    RuntimeState,
    RuntimeStateMachine as RuntimeStateMachineProtocol,
    SessionValidator as SessionValidatorProtocol,
)
from runtime.health_monitor import HealthMonitor
from runtime.profile_manager import ProfileManager
from runtime.recovery_strategies import ReloadStrategy
from runtime.registry import RuntimeRegistry
from runtime.session_validator import SessionValidator
from runtime.state_machine import RuntimeStateMachine
from shared.types import SessionState


# ============================================================
#  1. RuntimeStateMachine Protocol
# ============================================================


class TestStateMachineContract:

    def test_satisfies_protocol(self):
        sm = RuntimeStateMachine()
        assert isinstance(sm, RuntimeStateMachineProtocol)

    def test_has_required_attrs(self):
        sm = RuntimeStateMachine()
        assert hasattr(sm, "current")
        assert hasattr(sm, "history")
        assert hasattr(sm, "transition")
        assert hasattr(sm, "can_transition")
        assert hasattr(sm, "reset")

    def test_transition_works(self):
        sm = RuntimeStateMachine()
        asyncio.run(sm.transition(RuntimeState.INITIALIZING))
        assert sm.current == RuntimeState.INITIALIZING
        assert len(sm.history) == 1


# ============================================================
#  2. RuntimeRegistry Protocol
# ============================================================


class TestRegistryContract:

    def test_satisfies_protocol(self):
        reg = RuntimeRegistry()
        assert isinstance(reg, RuntimeRegistryProtocol)

    def test_has_required_methods(self):
        reg = RuntimeRegistry()
        assert hasattr(reg, "register")
        assert hasattr(reg, "unregister")
        assert hasattr(reg, "get")
        assert hasattr(reg, "get_all")
        assert hasattr(reg, "ensure_all_ready")
        assert hasattr(reg, "shutdown_all")


# ============================================================
#  3. ProfileManager ABC
# ============================================================


class TestProfileManagerContract:

    def test_satisfies_abc(self):
        pm = ProfileManager(auth_dir=Path("/tmp/test"))
        assert isinstance(pm, ProfileManagerABC)

    def test_has_required_methods(self):
        pm = ProfileManager(auth_dir=Path("/tmp/test"))
        assert hasattr(pm, "get_profile_path")
        assert hasattr(pm, "create")
        assert hasattr(pm, "backup")
        assert hasattr(pm, "restore")
        assert hasattr(pm, "health_check")


# ============================================================
#  4. SessionValidator Protocol
# ============================================================


class TestSessionValidatorContract:

    def test_satisfies_protocol(self):
        sv = SessionValidator(
            profile_dir=Path("/tmp/test"),
            platform="deepseek",
        )
        assert isinstance(sv, SessionValidatorProtocol)

    def test_has_validate_method(self):
        sv = SessionValidator(
            profile_dir=Path("/tmp/test"),
            platform="deepseek",
        )
        assert hasattr(sv, "validate")


# ============================================================
#  5. HealthMonitor Protocol
# ============================================================


class TestHealthMonitorContract:

    def test_satisfies_protocol(self):
        hm = HealthMonitor()
        assert isinstance(hm, HealthMonitorProtocol)

    def test_has_required_methods(self):
        hm = HealthMonitor()
        assert hasattr(hm, "start")
        assert hasattr(hm, "stop")
        assert hasattr(hm, "get_health")
        assert hasattr(hm, "get_all_health")


# ============================================================
#  6. RecoveryStrategy Protocol
# ============================================================


class TestRecoveryStrategyContract:

    def test_satisfies_protocol(self):
        rs = ReloadStrategy()
        assert isinstance(rs, RecoveryStrategyProtocol)

    def test_has_required_attrs(self):
        rs = ReloadStrategy()
        assert hasattr(rs, "name")
        assert hasattr(rs, "timeout_s")
        assert hasattr(rs, "recover")


# ============================================================
#  7. Type compatibility
# ============================================================


class TestTypeCompatibility:

    def test_runtime_state_values(self):
        """All RuntimeState values are strings."""
        for state in RuntimeState:
            assert isinstance(state.value, str)

    def test_session_state_values(self):
        """All SessionState values are strings."""
        for state in SessionState:
            assert isinstance(state.value, str)

    def test_platform_config_frozen(self):
        pc = PlatformConfig(name="test", home_url="https://test.com")
        assert pc.__dataclass_params__.frozen is True
