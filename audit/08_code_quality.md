# Code Quality Audit - OmniCouncil App

**Date:** 2026-06-06
**Scope:** `/home/greenpool/omnicouncil-app` (backend Python + frontend TypeScript)

---

## Summary

| Category | Count | Severity |
|----------|-------|----------|
| Oversized files (>400 lines) | 1 | HIGH |
| Duplicate class names (non-test) | 8 | HIGH |
| Parallel module pairs (old + new) | 7 | HIGH |
| Dead code (unused functions) | ~45 | MEDIUM |
| Unused TS exports | 4 | MEDIUM |
| Duplicate code blocks (Python) | 261 | MEDIUM |
| Duplicate code blocks (TypeScript) | 13 | LOW |
| Circular dependencies | 0 | OK |
| Unused Python imports | ~70 | LOW |
| Unused TS imports | 0 | OK |

---

## 1. Oversized Files (>400 lines)

| File | Lines |
|------|-------|
| `backend/main.py` | 684 |

**Recommendation:** Split `main.py` into focused modules:
- `main.py` -- FastAPI app setup and lifespan
- `api/routes.py` -- HTTP endpoint handlers
- `ws/connection.py` -- WebSocket connection manager and handler
- `api/events.py` -- Event callbacks (on_ai_completed, on_ai_failed, etc.)

---

## 2. Duplicate Code

### 2a. Duplicate Class Names (non-test, production code)

Classes with the same name exist in parallel module hierarchies, indicating incomplete migration:

| Class Name | File 1 | File 2 |
|-----------|--------|--------|
| `AIAdapter` | `adapters/base.py:22` | `engine/layers/layer1_ai_access/adapter.py:11` |
| `AIResponse` | `engine/collector/response.py:9` | `shared/types.py:44` |
| `ComparisonEngine` | `engine/comparison/engine.py:16` | `engine/layers/layer4_comparison/comparison_engine.py:28` |
| `DeepSeekAdapter` | `adapters/deepseek.py:12` | `engine/layers/layer1_ai_access/adapters/deepseek.py:24` |
| `QianwenAdapter` | `adapters/qianwen.py:12` | `engine/layers/layer1_ai_access/adapters/qianwen.py:24` |
| `ResultCollector` | `engine/collector/collector.py:14` | `engine/layers/layer3_collector/result_collector.py:25` |
| `TaskStatus` | `engine/scheduler/task.py:11` | `shared/types.py:85` |

### 2b. Parallel Module Pairs (old architecture vs new layer-based architecture)

Both old and new implementations coexist, suggesting incomplete migration:

| Old Module | Lines | New Module | Lines |
|-----------|-------|-----------|-------|
| `adapters/base.py` | 78 | `providers/base/provider.py` | 82 |
| `adapters/registry.py` | 103 | `providers/registry/registry.py` | 98 |
| `adapters/deepseek.py` | 86 | `engine/layers/layer1_ai_access/adapters/deepseek.py` | 160 |
| `adapters/qianwen.py` | 102 | `engine/layers/layer1_ai_access/adapters/qianwen.py` | 158 |
| `engine/comparison/engine.py` | 188 | `engine/layers/layer4_comparison/comparison_engine.py` | 112 |
| `engine/collector/collector.py` | 62 | `engine/layers/layer3_collector/result_collector.py` | 160 |
| `engine/scheduler/scheduler.py` | 121 | `engine/layers/layer2_scheduler/scheduler_center.py` | 296 |

**Recommendation:** Remove the old `adapters/` directory entirely. The new `providers/` and `engine/layers/` modules are the active code path (confirmed by `main.py` imports). The old modules are dead code.

Similarly, remove `engine/comparison/`, `engine/collector/`, `engine/scheduler/` in favor of the `engine/layers/` equivalents.

### 2c. Duplicate Code Blocks

**Python (261 duplicate 5-line block patterns):**

Most significant clusters:
- `_count_words()` duplicated in 6 files across adapters and response_normalizer
- `_load_config()` duplicated in 5 adapter files
- `_find_input()`, `_is_ui_element()`, `_send_async()` duplicated across browser_adapter and browser adapter variants
- `_prewarm_browser()` duplicated in deepseek.py and qianwen.py
- `_send_one()` duplicated in scheduler_center.py and scheduler.py
- `send_message()` duplicated across 9 provider/adapter files (interface implementations)
- Identical import blocks and error handling patterns across all layer1 adapters

**TypeScript (13 duplicate block patterns):**
- `getAIColor()` function is copy-pasted identically in `ConsensusTab.tsx`, `ComparisonTab.tsx`, and `ConflictTab.tsx`
- Color map (`deepseek: '#4f8fff', gemini: '#8b5cf6', qianwen: '#f59e0b'`) duplicated in same 3 files

**Recommendation:**
- Extract `_count_words()`, `_load_config()`, `_is_ui_element()` into a shared utility module
- Extract `getAIColor()` into a shared `utils/aiColors.ts` file
- Consider a base browser adapter class to consolidate `_find_input()`, `_send_async()`, `_extract_response()`

---

## 3. Circular Dependencies

**None found.** The import graph is acyclic. The architecture cleanly separates layers.

---

## 4. Dead Code

### 4a. Unused Python Modules (not imported by any other file)

These modules exist but are never imported by any production code:

| Module | Lines |
|--------|-------|
| `engine/layers/layer1_ai_access/adapter.py` | 77 |
| `engine/layers/layer1_ai_access/browser_adapter.py` | 230 |
| `engine/layers/layer1_ai_access/adapters/deepseek.py` | 160 |
| `engine/layers/layer1_ai_access/adapters/gemini.py` | 252 |
| `engine/layers/layer1_ai_access/adapters/qianwen.py` | 158 |
| `engine/layers/layer1_ai_access/managers/circuit_breaker.py` | 84 |
| `engine/layers/layer1_ai_access/managers/provider_manager.py` | 43 |
| `engine/layers/layer1_ai_access/managers/rate_limiter.py` | 76 |
| `engine/layers/layer1_ai_access/response_normalizer.py` | 105 |
| `engine/layers/layer4_comparison/comparison_config.py` | 5 |
| `engine/layers/layer4_comparison/pipeline/comparison_assembler.py` | 89 |
| `engine/layers/layer4_comparison/pipeline/difference_analyzer.py` | 137 |
| `engine/layers/layer4_comparison/pipeline/semantic_unit_extractor.py` | 30 |
| `engine/layers/layer4_comparison/pipeline/similarity_analyzer.py` | 80 |
| `engine/layers/layer4_comparison/pipeline/text_preprocessor.py` | 50 |
| `engine/layers/layer4_comparison/pipeline/unique_insight_extractor.py` | 62 |
| `engine/session/manager.py` | 50 |

**Note:** Some of these may be imported dynamically or via `__init__.py` re-exports. The `engine/layers/` submodules are likely used internally by their parent `__init__.py` files. The old `adapters/` modules are genuinely dead.

### 4b. Unused Functions (defined but never called from outside their file)

| File | Function |
|------|----------|
| `adapters/base.py` | `get_response_selector()` |
| `adapters/registry.py` | `auto_discover_adapters()` |
| `browser/embedded_engine.py` | `on_page_close()` |
| `engine/collector/collector.py` | `get_result()`, `get_results()` |
| `engine/comparison/result.py` | `has_disagreements()` |
| `engine/judge/engine.py` | `has_api_key()`, `set_api_key()` |
| `engine/layers/layer1_ai_access/adapter.py` | `is_ready()` |
| `engine/layers/layer1_ai_access/adapters/gemini.py` | `page_action()` |
| `engine/layers/layer1_ai_access/manager.py` | `get_provider_status()`, `send_to_multiple()` |
| `engine/layers/layer1_ai_access/managers/circuit_breaker.py` | `is_open()` |
| `engine/layers/layer1_ai_access/managers/provider_manager.py` | `registered_ids()` |
| `engine/layers/layer2_scheduler/concurrency_controller.py` | `active_count()`, `available_slots()` |
| `engine/layers/layer2_scheduler/scheduler_center.py` | `cleanup_old_tasks()`, `get_available_ais()`, `get_task_status()` |
| `engine/layers/layer3_collector/result_collector.py` | `get_latest_round_context()`, `get_partial_results()` |
| `engine/layers/layer4_comparison/comparison_engine.py` | `get_comparison_context()`, `on_analysis_completed()` |
| `engine/scheduler/scheduler.py` | `get_all_tasks()` |
| `engine/scheduler/task.py` | `failed_count()` |
| `engine/session/manager.py` | `get_authenticated_providers()`, `has_saved_session()`, `set_authenticated()` |
| `engine/session/storage.py` | `get_auth_path()` |
| `shared/event_bus.py` | `emit_sync()`, `registered_events()` |
| `providers/registry/registry.py` | `auto_discover_providers()` |

**Note:** Some functions in `main.py` (handle_*, lifespan, etc.) are used as FastAPI route handlers or lifespan context managers -- they are referenced by decorator wiring, not by direct call. These are not dead code.

### 4c. Unused TypeScript Exports

| File | Export |
|------|--------|
| `stores/configStore.ts` | `AIConfig`, `ConfigState` |
| `stores/appStore.ts` | `AppState` |
| `components/SkeletonLoader.tsx` | `SkeletonLoader` |
| `components/Header.tsx` | `Header` |
| `components/SetupWizard.tsx` | `SetupWizard` |

### 4d. Unused Python Imports

Significant unused imports (excluding `from __future__ import annotations` which is a style choice):

| File | Unused Import |
|------|--------------|
| `main.py` | `AuthStatus`, `EngineMode` |
| `adapters/registry.py` | `AIConfig` |
| `adapters/qianwen.py` | `asyncio` |
| `adapters/deepseek.py` | `asyncio` |
| `tests/test_login_flow.py` | `AuthStatus` |
| `tests/test_websocket.py` | `MagicMock` |
| `engine/layers/layer4_comparison/comparison_engine.py` | `InsufficientResultsError` |
| `engine/layers/layer4_comparison/pipeline/text_preprocessor.py` | `AiResult` |
| `engine/layers/layer2_scheduler/retry_manager.py` | `asyncio`, `time` |
| `engine/layers/layer2_scheduler/timeout_manager.py` | `asyncio` |
| `engine/layers/layer1_ai_access/manager.py` | `time`, `Any`, `AIAdapterError`, `CircuitOpenError`, `RateLimitError` |
| `engine/layers/layer1_ai_access/browser_adapter.py` | `asyncio`, `json`, `Path` |
| `engine/layers/layer1_ai_access/adapter.py` | `Any` |
| `engine/layers/layer1_ai_access/adapters/qianwen.py` | `asyncio`, `SubmitOptions` |
| `engine/layers/layer1_ai_access/adapters/deepseek.py` | `asyncio`, `SubmitOptions` |
| `engine/layers/layer1_ai_access/managers/provider_manager.py` | `AIStatus` |
| `engine/collector/collector.py` | `Any` |
| `engine/session/manager.py` | `asyncio`, `Any` |
| `engine/comparison/engine.py` | `Counter`, `Any` |
| `browser/cdp_engine.py` | `json` |
| `browser/manager/browser_manager.py` | `Any` |

---

## 5. Architectural Observations

### 5a. Incomplete Migration

The codebase shows a clear migration from a flat `adapters/` + `engine/` structure to a layered `engine/layers/` + `providers/` structure. Both old and new code coexist:

- **Old path:** `adapters/` -> `engine/scheduler/` -> `engine/collector/` -> `engine/comparison/`
- **New path:** `providers/` -> `engine/layers/layer1_ai_access/` -> `engine/layers/layer2_scheduler/` -> `engine/layers/layer3_collector/` -> `engine/layers/layer4_comparison/`

Only `main.py` imports from the new path. The old modules are orphaned.

### 5b. main.py as God Object

At 684 lines, `main.py` contains:
- FastAPI app setup and lifespan
- WebSocket connection management
- All HTTP route handlers
- Event callback handlers
- Login flow logic
- Session management endpoints
- Error handling

This should be decomposed into at least 4 focused modules.

### 5c. Test Code Duplication

`test_profile_sharing.py` (169L) and `test_login_flow.py` (172L) share:
- 4 duplicate test class names
- Near-identical fixtures and test patterns
- Should be consolidated or share a common test base

---

## Recommended Actions (Priority Order)

1. **Remove dead old modules** -- Delete `backend/adapters/`, `backend/engine/comparison/`, `backend/engine/collector/`, `backend/engine/scheduler/` (the old architecture). This eliminates ~700 lines and 8 duplicate class names.

2. **Split main.py** -- Extract routes, WebSocket handler, and event callbacks into separate modules.

3. **Extract shared utilities** -- Create `backend/shared/utils.py` for `_count_words()`, `_load_config()`, `_is_ui_element()`, and other duplicated helpers.

4. **Extract `getAIColor()`** -- Move to `src/utils/aiColors.ts` and import in all 3 tab components.

5. **Clean unused imports** -- Run `autoflake` or `ruff` on Python files; run ESLint `no-unused-vars` on TypeScript.

6. **Remove unused TS exports** -- `SkeletonLoader`, `Header`, `SetupWizard` components and type exports from stores.
