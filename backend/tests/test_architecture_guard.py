"""Architecture drift guard — prevents V1 code from re-entering the codebase.

Scans all .py files in backend/ and all .ts/.tsx files in src/ for V1
blacklist import statements.  Also verifies V2 core modules exist.

Run: pytest tests/test_architecture_guard.py -v
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

# ── Paths ───────────────────────────────────────────────────

BACKEND_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_ROOT.parent
SRC_ROOT = PROJECT_ROOT / "src"

# ── V1 Import Patterns (regex) ──────────────────────────────

# Matches: from X import Y  or  import X  where X contains V1 module paths
V1_IMPORT_PATTERNS = [
    re.compile(r"^\s*(from\s+providers\.runtime\s+import|import\s+providers\.runtime)", re.MULTILINE),
    re.compile(r"^\s*(from\s+providers\.registry\s+import|import\s+providers\.registry)", re.MULTILINE),
    re.compile(r"^\s*(from\s+providers\.health_monitor\s+import|import\s+providers\.health_monitor)", re.MULTILINE),
    re.compile(r"^\s*(from\s+providers\.session_manager\s+import|import\s+providers\.session_manager)", re.MULTILINE),
    re.compile(r"^\s*(from\s+providers\.errors\s+import|import\s+providers\.errors)", re.MULTILINE),
    re.compile(r"^\s*(from\s+providers\.event_bus\s+import|import\s+providers\.event_bus)", re.MULTILINE),
    re.compile(r"^\s*(from\s+browser\.embedded_engine\s+import|import\s+browser\.embedded_engine)", re.MULTILINE),
    re.compile(r"^\s*(from\s+browser\.engine\s+import|import\s+browser\.engine)", re.MULTILINE),
    re.compile(r"^\s*(from\s+browser\.factory\s+import|import\s+browser\.factory)", re.MULTILINE),
    re.compile(r"^\s*(from\s+engine\.session\.manager\s+import|import\s+engine\.session\.manager)", re.MULTILINE),
]

# Frontend V1 import patterns
V1_TS_IMPORT_PATTERNS = [
    re.compile(r"import.*SessionManager", re.MULTILINE),
    re.compile(r"import.*BaseProvider", re.MULTILINE),
    re.compile(r"import.*ProviderRuntime", re.MULTILINE),
    re.compile(r"import.*embedded_engine", re.MULTILINE),
    re.compile(r"import.*browser_engine", re.MULTILINE),
    re.compile(r"import.*provider_registry", re.MULTILINE),
]

# ── V2 Core Files ───────────────────────────────────────────

V2_CORE_FILES = [
    "runtime/page_guard.py",
    "runtime/recovery_engine.py",
    "runtime/engine.py",
    "engine/contracts.py",
]


# ============================================================
#  Helpers
# ============================================================

def _collect_py_files() -> list[Path]:
    """Collect all .py files excluding .venv, __pycache__, packages, tests."""
    files = []
    for root, dirs, filenames in os.walk(BACKEND_ROOT):
        dirs[:] = [
            d for d in dirs
            if d not in (".venv", "__pycache__", ".ruff_cache", ".pytest_cache",
                         "egg-info", "packages", ".git")
        ]
        for fname in filenames:
            if fname.endswith(".py"):
                files.append(Path(root) / fname)
    return files


def _collect_ts_files() -> list[Path]:
    """Collect all .ts and .tsx files in src/."""
    files = []
    if not SRC_ROOT.exists():
        return files
    for root, dirs, filenames in os.walk(SRC_ROOT):
        dirs[:] = [d for d in dirs if d not in ("node_modules",)]
        for fname in filenames:
            if fname.endswith((".ts", ".tsx")):
                files.append(Path(root) / fname)
    return files


# ============================================================
#  1. Python端黑名单扫描 (import 语句)
# ============================================================

class TestPythonBlacklist:
    """Scan backend/ .py files for V1 import statements."""

    def test_no_v1_imports_in_production(self):
        """Production .py files must not contain V1 import statements."""
        violations: list[str] = []

        for f in _collect_py_files():
            # Skip test files — they may reference V1 for backward compat
            rel = str(f.relative_to(BACKEND_ROOT))
            if rel.startswith("tests/"):
                continue

            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
                for pattern in V1_IMPORT_PATTERNS:
                    if pattern.search(content):
                        violations.append(f"{rel}: {pattern.pattern}")
            except Exception:
                pass

        assert not violations, f"V1 imports found in production code:\n" + "\n".join(violations)

    def test_no_provider_py_in_platform_dirs(self):
        """V2 platform dirs must only have query_adapter.py, not provider.py."""
        providers_dir = BACKEND_ROOT / "providers"
        if not providers_dir.exists():
            pytest.skip("providers/ directory not found")

        violations = []
        for item in providers_dir.iterdir():
            if item.is_dir() and item.name not in ("__pycache__", "base", "registry"):
                provider_py = item / "provider.py"
                if provider_py.exists():
                    violations.append(str(provider_py.relative_to(BACKEND_ROOT)))

        assert not violations, f"V1 provider.py found in platform dirs: {violations}"


# ============================================================
#  2. 前端端黑名单扫描
# ============================================================

class TestFrontendBlacklist:
    """Scan src/ .ts/.tsx files for V1 imports."""

    def test_no_v1_imports_in_frontend(self):
        """No .ts/.tsx file should contain V1 import statements."""
        violations: list[str] = []

        for f in _collect_ts_files():
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
                for pattern in V1_TS_IMPORT_PATTERNS:
                    match = pattern.search(content)
                    if match:
                        violations.append(
                            f"{f.relative_to(PROJECT_ROOT)}: {match.group()}"
                        )
            except Exception:
                pass

        assert not violations, f"V1 imports found in frontend:\n" + "\n".join(violations)

    def test_error_code_messages_has_page_busy(self):
        """appStore.ts must define PAGE_BUSY and RECOVERY_BUSY error mappings."""
        app_store = SRC_ROOT / "stores" / "appStore.ts"
        if not app_store.exists():
            pytest.skip("appStore.ts not found")

        content = app_store.read_text(encoding="utf-8")
        assert "PAGE_BUSY" in content, "PAGE_BUSY not found in appStore.ts"
        assert "RECOVERY_BUSY" in content, "RECOVERY_BUSY not found in appStore.ts"
        assert "RUNTIME_NOT_READY" in content, "RUNTIME_NOT_READY not found in appStore.ts"


# ============================================================
#  3. V2 核心模块完整性检查
# ============================================================

class TestV2CoreModules:
    """Verify V2 core files exist and are importable."""

    @pytest.mark.parametrize("rel_path", V2_CORE_FILES)
    def test_v2_file_exists(self, rel_path: str):
        """V2 core file must exist on disk."""
        full_path = BACKEND_ROOT / rel_path
        assert full_path.exists(), f"V2 core file missing: {rel_path}"

    def test_page_guard_importable(self):
        """page_guard.py must expose lease, guard_recovery, mark_evict."""
        from runtime.page_guard import PageGuard
        assert hasattr(PageGuard, "lease")
        assert hasattr(PageGuard, "guard_recovery")
        assert hasattr(PageGuard, "mark_evict")
        assert hasattr(PageGuard, "clear_evict")
        assert hasattr(PageGuard, "mark_recovery")
        assert hasattr(PageGuard, "clear_recovery")

    def test_recovery_engine_importable(self):
        """recovery_engine.py must expose recover."""
        from runtime.recovery_engine import RecoveryEngine
        assert hasattr(RecoveryEngine, "recover")

    def test_runtime_engine_importable(self):
        """engine.py must expose acquire_page, guard_recovery, clear_recovery."""
        from runtime.engine import AIRuntimeEngine
        assert hasattr(AIRuntimeEngine, "acquire_page")
        assert hasattr(AIRuntimeEngine, "guard_recovery")
        assert hasattr(AIRuntimeEngine, "clear_recovery")
        assert hasattr(AIRuntimeEngine, "ensure_ready")
        assert hasattr(AIRuntimeEngine, "boot")
        assert hasattr(AIRuntimeEngine, "shutdown")

    def test_contracts_importable(self):
        """contracts.py must define key V2 types."""
        from engine.contracts import (
            PageBusyError,
            PageBusyState,
            RecoveryBusyError,
            RuntimeMetrics,
            RuntimeState,
        )
        # Verify 10 states exist
        assert len(list(RuntimeState)) == 10
        assert hasattr(RuntimeState, "READY")
        assert hasattr(RuntimeState, "RECOVERING")
        assert hasattr(RuntimeState, "LOGIN_REQUIRED")
        assert hasattr(PageBusyState, "LEASED")
        assert hasattr(PageBusyState, "RECOVERING")
        assert hasattr(PageBusyState, "EVICTING")
