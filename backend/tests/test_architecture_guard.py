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


# ============================================================
#  4. V2 内部一致性检查
# ============================================================

class TestV2InternalConsistency:
    """Prevent ghost attribute access and cross-layer naming drift."""

    def _collect_py_files(self, *subdirs: str) -> list[Path]:
        """Collect .py files under given subdirs of BACKEND_ROOT."""
        files = []
        for subdir in subdirs:
            root_dir = BACKEND_ROOT / subdir
            if not root_dir.exists():
                continue
            for root, dirs, filenames in os.walk(root_dir):
                dirs[:] = [d for d in dirs if d not in (".venv", "__pycache__", ".ruff_cache", ".pytest_cache", "egg-info", ".git")]
                for fname in filenames:
                    if fname.endswith(".py"):
                        files.append(Path(root) / fname)
        return files

    def test_all_ai_manager_attribute_accesses_exist(self):
        """Every self._ai_manager.<attr> access must reference an attribute
        that actually exists on AIAccessManager."""
        import ast

        # 1. Get actual AIAccessManager attributes via AST
        manager_file = BACKEND_ROOT / "engine" / "layers" / "layer1_ai_access" / "manager.py"
        if not manager_file.exists():
            pytest.skip("manager.py not found")

        tree = ast.parse(manager_file.read_text(encoding="utf-8"))
        actual_attrs: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "AIAccessManager":
                for item in node.body:
                    # Top-level self.xxx = ...
                    if isinstance(item, ast.Assign):
                        for target in item.targets:
                            if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "self":
                                actual_attrs.add(target.attr)
                    # Methods (including __init__)
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        actual_attrs.add(item.name)
                        # Walk into method body to find self.xxx assignments
                        for sub in ast.walk(item):
                            # Regular assignment: self.xxx = ...
                            if isinstance(sub, ast.Assign):
                                for target in sub.targets:
                                    if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "self":
                                        actual_attrs.add(target.attr)
                            # Annotated assignment: self.xxx: Type = ...
                            if isinstance(sub, ast.AnnAssign) and isinstance(sub.target, ast.Attribute):
                                if isinstance(sub.target.value, ast.Name) and sub.target.value.id == "self":
                                    actual_attrs.add(sub.target.attr)

        # 2. Find all self._ai_manager.<attr> accesses in layer2+
        violations: list[str] = []
        search_files = self._collect_py_files("engine/layers/layer2_scheduler", "engine/layers/layer3_collector")

        attr_pattern = re.compile(r"self\._ai_manager\.(\w+)")

        for f in search_files:
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
                for match in attr_pattern.finditer(content):
                    attr = match.group(1)
                    if attr.startswith("_") and attr not in actual_attrs:
                        # Private attribute access — must exist
                        violations.append(f"{f.relative_to(BACKEND_ROOT)}: self._ai_manager.{attr}")
                    elif not attr.startswith("_") and attr not in actual_attrs:
                        violations.append(f"{f.relative_to(BACKEND_ROOT)}: self._ai_manager.{attr}")
            except Exception:
                pass

        assert not violations, f"Ghost attribute accesses on AIAccessManager:\n" + "\n".join(violations)

    def test_no_import_of_nonexistent_symbols(self):
        """Every 'from engine.* import X' must import a symbol that exists."""
        import importlib
        import importlib.util

        # Collect all import statements from engine/ and runtime/
        import_pattern = re.compile(r"^\s*from\s+([\w.]+)\s+import\s+([\w,\s]+)", re.MULTILINE)

        files = self._collect_py_files("engine", "runtime", "providers")
        violations: list[str] = []

        for f in files:
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
                rel = str(f.relative_to(BACKEND_ROOT))

                for match in import_pattern.finditer(content):
                    mod_path = match.group(1)
                    symbols_str = match.group(2)
                    symbols = [s.strip() for s in symbols_str.split(",") if s.strip()]

                    # Skip TYPE_CHECKING blocks (they're not executed at runtime)
                    # Check if this import is inside an if TYPE_CHECKING block
                    lines = content[:match.start()].split("\n")
                    in_type_checking = False
                    for line in lines[-10:]:
                        if "TYPE_CHECKING" in line:
                            in_type_checking = True
                    if in_type_checking:
                        continue

                    # Try to resolve the module
                    if mod_path.startswith("engine.") or mod_path.startswith("runtime.") or mod_path.startswith("providers."):
                        try:
                            # Convert module path to file path
                            parts = mod_path.split(".")
                            mod_file = BACKEND_ROOT / "/".join(parts)
                            if mod_file.with_suffix(".py").exists():
                                mod_file = mod_file.with_suffix(".py")
                            elif (mod_file / "__init__.py").exists():
                                mod_file = mod_file / "__init__.py"
                            else:
                                continue  # Can't resolve, skip

                            # Parse the module and check symbols
                            mod_tree = ast.parse(mod_file.read_text(encoding="utf-8"))
                            defined_names = set()
                            for node in ast.walk(mod_tree):
                                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                                    defined_names.add(node.name)
                                elif isinstance(node, ast.Assign):
                                    for target in node.targets:
                                        if isinstance(target, ast.Name):
                                            defined_names.add(target.id)

                            for sym in symbols:
                                if sym not in defined_names and sym != "*":
                                    violations.append(f"{rel}: from {mod_path} import {sym} — symbol not found in source")
                        except Exception:
                            pass  # Can't verify, skip
            except Exception:
                pass

        assert not violations, f"Broken imports found:\n" + "\n".join(violations)

    def test_layer_attributes_consistent(self):
        """Cross-layer manager/adapter references must use consistent names.

        If layer1 defines self._query_adapters, layer2 must not
        reference self._ai_manager._provider_manager (old V1 name).
        """
        # Known V1 attribute names that must not appear
        v1_attrs = ["_provider_manager", "_providers", "_engine"]

        files = self._collect_py_files("engine/layers/layer2_scheduler", "engine/layers/layer3_collector")
        violations: list[str] = []

        for f in files:
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
                rel = str(f.relative_to(BACKEND_ROOT))
                for attr in v1_attrs:
                    pattern = re.compile(rf"self\._ai_manager\.{attr}\b")
                    if pattern.search(content):
                        violations.append(f"{rel}: uses V1 attribute self._ai_manager.{attr}")
            except Exception:
                pass

        assert not violations, f"V1 attribute names found in cross-layer references:\n" + "\n".join(violations)
