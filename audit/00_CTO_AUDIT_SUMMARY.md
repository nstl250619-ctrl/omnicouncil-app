# OmniCouncil CTO-Level Code Audit

**Date:** 2026-06-06
**Auditor:** Claude Code (Automated)
**Project:** OmniCouncil — Multi-AI Consensus Desktop App
**Stack:** Tauri (Rust) + React (TypeScript) + FastAPI (Python)

---

## Executive Summary

OmniCouncil is a Tauri desktop app that queries multiple AI platforms (DeepSeek, Qianwen, Gemini, ChatGPT, Claude) via browser automation, then compares/consolidates their responses. The project has **124 source files** (~10,782 lines) across Python, TypeScript, and Rust.

**Verdict: The codebase is in a half-migrated state with significant dead code, but the core architecture is sound. A cleanup pass is needed before V1 can ship.**

### Health Score: 4/10

| Dimension | Score | Notes |
|-----------|-------|-------|
| Architecture | 7/10 | Layered design is good, but migration incomplete |
| Code Quality | 3/10 | Massive duplication, dead code, hardcoded paths |
| Test Coverage | 5/10 | Tests exist but only for browser/session; no unit tests for engine |
| Browser Layer | 6/10 | Works for DeepSeek/Qianwen; others untested |
| Provider System | 4/10 | 2/5 providers actually functional |
| Login Flow | 5/10 | Works but fragile, hardcoded paths, no error recovery |
| Frontend | 6/10 | Clean React+Zustand, but missing backend integrations |

---

## 1. Architecture Overview

### What's Good

The project has a clear **4-layer engine architecture**:

```
Layer 1: AI Access (Provider adapters)
  ↓
Layer 2: Scheduler (Concurrency, retry, timeout)
  ↓
Layer 3: Collector (Result aggregation)
  ↓
Layer 4: Comparison (Similarity, diff, consensus)
```

Plus supporting modules:
- **Browser Engine** — Playwright/Patchright abstraction (CDP + Embedded modes)
- **Session Manager** — Per-AI persistent browser contexts
- **Provider Registry** — Auto-discovery of AI providers
- **Event Bus** — Pub/sub for async communication

### What's Bad

**Two parallel architectures coexist:**

| Old (dead) | New (active) |
|-----------|-------------|
| `adapters/base.py` | `providers/base/provider.py` |
| `adapters/registry.py` | `providers/registry/registry.py` |
| `adapters/deepseek.py` | `engine/layers/layer1_ai_access/adapters/deepseek_browser.py` |
| `adapters/qianwen.py` | `engine/layers/layer1_ai_access/adapters/qianwen_browser.py` |
| `engine/comparison/engine.py` | `engine/layers/layer4_comparison/comparison_engine.py` |
| `engine/collector/collector.py` | `engine/layers/layer3_collector/result_collector.py` |
| `engine/scheduler/scheduler.py` | `engine/layers/layer2_scheduler/scheduler_center.py` |

**Only `main.py` imports from the new path.** The old modules are orphaned but still present, creating confusion.

---

## 2. Critical Findings

### CRITICAL-1: Hardcoded User Paths (4 instances)

```python
# backend/browser/embedded_engine.py:18
DEBUG_LOG = "C:\\Users\\green\\.omnicouncil\\login.log"

# backend/browser/embedded_engine.py:36
self._auth_dir = auth_dir or "C:\\Users\\green\\.omnicouncil\\auth"

# backend/main.py:367
_debug_dir = os.path.join(os.environ.get("USERPROFILE", "C:\\Users\\green"), ".omnicouncil")

# backend/main.py:563
debug_path = "C:\\Users\\green\\.omnicouncil\\login.log"
```

**Impact:** App breaks on any machine that isn't the original developer's Windows box. Completely broken on Linux/Mac.

**Fix:** Use `Path.home() / ".omnicouncil"` consistently. The factory.py already does this correctly.

### CRITICAL-2: main.py is a God Object (684 lines)

`backend/main.py` contains:
- FastAPI app setup and lifespan
- WebSocket connection management
- All HTTP route handlers (health, sessions, status)
- Event callback handlers (ai_completed, ai_failed, progress)
- Login flow logic (`_do_login`)
- Session management endpoints
- Debug logging

**Fix:** Split into:
- `main.py` — App setup + lifespan (~100 lines)
- `api/routes.py` — HTTP endpoints (~80 lines)
- `ws/handler.py` — WebSocket message routing (~150 lines)
- `ws/events.py` — Event callbacks (~150 lines)
- `services/login.py` — Login flow (~100 lines)

### CRITICAL-3: Only 2/5 Providers Actually Work

| Provider | Status | Browser Adapter | Tested |
|----------|--------|----------------|--------|
| DeepSeek | ✅ Working | `deepseek_browser.py` | ✅ E2E |
| Qianwen | ✅ Working | `qianwen_browser.py` | ✅ E2E |
| Gemini | ❌ No adapter | Config only | ❌ |
| ChatGPT | ❌ No adapter | Provider only | ❌ |
| Claude | ❌ No adapter | Provider only | ❌ |

The `providers/` directory has provider classes for all 5, but only DeepSeek and Qianwen have **browser adapters** that can actually interact with the AI websites. The other 3 are stubs.

### CRITICAL-4: JudgeEngine is a Placeholder

```python
# backend/engine/judge/engine.py
def _call_api(self, provider, prompt):
    # Placeholder — returns mock data
    return JudgeVerdict(...)
```

The judge/consensus system (a core feature of OmniCouncil) is not implemented.

---

## 3. Dead Code Inventory

### Modules to DELETE (old architecture, ~700 lines)

| Module | Lines | Reason |
|--------|-------|--------|
| `backend/adapters/` | ~370 | Replaced by `providers/` |
| `backend/engine/comparison/` | ~190 | Replaced by `engine/layers/layer4_comparison/` |
| `backend/engine/collector/` | ~65 | Replaced by `engine/layers/layer3_collector/` |
| `backend/engine/scheduler/` | ~125 | Replaced by `engine/layers/layer2_scheduler/` |
| `backend/browser/manager/` | ~50 | `BrowserManager` unused anywhere |

### Unused Functions (~45 total)

Key ones:
- `auto_discover_providers()` — never called
- `auto_discover_adapters()` — never called
- `BrowserManager` class — never imported
- `SessionManager` — exists but `EmbeddedEngine` manages its own auth set
- `emit_sync()`, `registered_events()` — unused EventBus methods
- `get_result()`, `get_results()` — unused collector methods

### Unused TypeScript Exports

- `SkeletonLoader`, `Header`, `SetupWizard` components
- `AIConfig`, `ConfigState`, `AppState` type exports

---

## 4. Code Duplication

### Python: 261 duplicate block patterns

Most significant:
- `_count_words()` — duplicated in 6 files
- `_load_config()` — duplicated in 5 adapter files
- `_find_input()`, `_is_ui_element()`, `_send_async()` — duplicated across browser adapters
- `send_message()` — duplicated across 9 provider/adapter files

### TypeScript: 13 duplicate patterns

- `getAIColor()` — copy-pasted in `ConsensusTab.tsx`, `ComparisonTab.tsx`, `ConflictTab.tsx`
- Color map (`deepseek: '#4f8fff'`, etc.) — duplicated in same 3 files

---

## 5. Browser Layer Assessment

### Design: Good

- Clean abstraction: `BrowserEngine` ABC → `EmbeddedEngine` / `CDPEngine`
- Per-AI persistent contexts (login and work share same profile dir)
- Anti-detection: `--disable-blink-features=AutomationControlled`
- Uses Patchright (Playwright fork with anti-detection patches)

### Issues

1. **Hardcoded paths** — breaks portability
2. **No session refresh** — if cookies expire during work, no automatic re-login
3. **No retry on browser disconnect** — if Chromium crashes mid-task, no recovery
4. **`save_auth_state()` / `load_auth_state()` are no-ops** in EmbeddedEngine
5. **`BrowserManager` is dead code** — unused by anything
6. **`SessionManager` is dead code** — EmbeddedEngine manages its own `_authenticated` set

### Login Flow

```
Frontend: User clicks "Connect" → send('reauth', {ai_id})
  ↓
Backend: handle_reauth() → _do_login(ai_id, url)
  ↓
EmbeddedEngine.login():
  → chromium.launch_persistent_context(profile_dir, headless=False)
  → page.goto(login_url)
  → User manually logs in
  → User closes browser window
  → browser.storage_state() saves cookies
  → _has_saved_cookies() verifies
  → broadcast auth_status: authenticated
```

**Fragility points:**
- No timeout handling if user never closes browser
- No detection of login failure (wrong password, CAPTCHA)
- No retry logic
- Hardcoded debug log path

---

## 6. Frontend Assessment

### What's Good

- Clean React + Zustand state management
- WebSocket hook with reconnect logic
- Tab-based UI for responses/comparison/consensus/conflict
- Setup wizard for first-run configuration

### What's Missing

- `AIPlatformManager.tsx` has 2 TODO comments for backend integration:
  - `// TODO: Call backend to clear cookies`
  - `// TODO: Call backend to delete all data for this AI`
- 5 `console.log` debug statements in production code
- No error boundary components
- No loading states for login flow

---

## 7. Test Coverage

| Area | Tests | Coverage |
|------|-------|----------|
| Browser engine | `test_browser_engine.py` | Factory, enum, dataclass |
| Login flow | `test_login_flow.py` | Profile isolation, cookie detection, auth state |
| Profile sharing | `test_profile_sharing.py` | Login→work profile invariant |
| WebSocket | `test_websocket.py` | Connection, message routing |
| E2E | `scripts/test-e2e.py` | Health, WS, query submission |
| **Provider adapters** | ❌ None | 0% |
| **Scheduler** | ❌ None | 0% |
| **Collector** | ❌ None | 0% |
| **Comparison engine** | ❌ None | 0% |
| **Consensus/Conflict** | ❌ None | 0% |
| **Frontend** | ❌ None | 0% |

**Estimated overall coverage: ~15%**

---

## 8. Recommended Actions

### Phase 1: Emergency Cleanup (1-2 days)

1. **Fix hardcoded paths** — Replace all `C:\Users\green\` with `Path.home()`
2. **Delete dead modules** — Remove `adapters/`, old `engine/comparison/`, `engine/collector/`, `engine/scheduler/`, `browser/manager/`
3. **Remove `console.log`** — Replace with proper logger or remove
4. **Remove `DEBUG_LOG`** — Use standard logging framework
5. **Clean unused imports** — Run `autoflake` on Python

### Phase 2: Architecture Stabilization (3-5 days)

6. **Split main.py** — Extract routes, WS handler, events, login service
7. **Extract shared utilities** — `_count_words()`, `_load_config()`, `getAIColor()`
8. **Implement missing provider adapters** — Gemini, ChatGPT, Claude browser adapters
9. **Wire up SessionManager** — Either use it or delete it; current dual approach is confusing
10. **Add error recovery** — Browser disconnect retry, session expiry detection

### Phase 3: Feature Completion (1-2 weeks)

11. **Implement JudgeEngine** — Currently returns mock data
12. **Implement Consensus/Conflict engines** — Core feature of OmniCouncil
13. **Add unit tests** — Target 80% coverage for engine layers
14. **Add frontend tests** — Component tests for key UI flows
15. **Implement TODO items** — Cookie clearing, data deletion endpoints

### Phase 4: Polish (1 week)

16. **Add error boundaries** — Frontend crash recovery
17. **Add loading states** — Login flow, query submission
18. **Add logging framework** — Replace all debug prints
19. **Add CI/CD** — Automated testing and builds
20. **Documentation** — API docs, architecture docs, setup guide

---

## 9. File Deletion List

### Safe to Delete (dead code)

```
backend/adapters/__init__.py
backend/adapters/base.py
backend/adapters/deepseek.py
backend/adapters/qianwen.py
backend/adapters/registry.py
backend/engine/comparison/__init__.py
backend/engine/comparison/engine.py
backend/engine/comparison/result.py
backend/engine/collector/__init__.py
backend/engine/collector/collector.py
backend/engine/collector/response.py
backend/engine/scheduler/__init__.py
backend/engine/scheduler/scheduler.py
backend/engine/scheduler/task.py
backend/browser/manager/__init__.py
backend/browser/manager/browser_manager.py
```

**Total: ~700 lines of dead code**

### Safe to Delete (runtime data, not source)

```
backend/engine/data/  (42MB of Chromium session data)
src-tauri/target/     (846MB of Rust build artifacts)
```

---

## 10. File Retention List

### Must Keep (core architecture)

```
backend/main.py                          # Entry point (needs splitting)
backend/browser/engine.py                # Browser abstraction
backend/browser/embedded_engine.py       # Primary engine
backend/browser/cdp_engine.py            # Alternative engine
backend/browser/factory.py               # Engine factory
backend/providers/base/provider.py       # Provider interface
backend/providers/*/provider.py          # Provider implementations
backend/providers/registry/registry.py   # Auto-discovery
backend/engine/layers/layer1_ai_access/  # AI access layer
backend/engine/layers/layer2_scheduler/  # Scheduler layer
backend/engine/layers/layer3_collector/  # Collector layer
backend/engine/layers/layer4_comparison/ # Comparison layer
backend/engine/session/                  # Session management
backend/shared/                          # Shared utilities
backend/storage/                         # Persistence
src/App.tsx                              # Frontend entry
src/components/*                         # UI components
src/hooks/useWebSocket.ts                # WS connection
src/stores/*                             # State management
src-tauri/src/main.rs                    # Tauri shell
src-tauri/src/python_manager.rs          # Python bridge
```

---

## 11. V2 Architecture Blueprint

If continuing development, the recommended V2 architecture:

```
┌─────────────────────────────────────────────┐
│                  Tauri Shell                 │
│  ┌─────────────────────────────────────────┐ │
│  │           React Frontend                │ │
│  │  ┌─────────┐ ┌──────────┐ ┌─────────┐  │ │
│  │  │ Query   │ │ Response │ │ Settings│  │ │
│  │  │ Input   │ │ Viewer   │ │ Panel   │  │ │
│  │  └────┬────┘ └─────▲────┘ └─────────┘  │ │
│  └───────┼────────────┼────────────────────┘ │
└──────────┼────────────┼──────────────────────┘
           │ WebSocket  │
┌──────────▼────────────┼──────────────────────┐
│           FastAPI Backend                    │
│  ┌─────────────────────────────────────────┐ │
│  │         Provider Registry               │ │
│  │  ┌─────────┐ ┌─────────┐ ┌─────────┐   │ │
│  │  │DeepSeek │ │ Qianwen │ │ Gemini  │   │ │
│  │  └────┬────┘ └────┬────┘ └────┬────┘   │ │
│  └───────┼───────────┼───────────┼─────────┘ │
│  ┌───────▼───────────▼───────────▼─────────┐ │
│  │         Browser Engine (Patchright)     │ │
│  │  ┌──────────────┐ ┌──────────────────┐  │ │
│  │  │   Embedded   │ │       CDP        │  │ │
│  │  └──────────────┘ └──────────────────┘  │ │
│  └─────────────────────────────────────────┘ │
│  ┌─────────────────────────────────────────┐ │
│  │         Engine Pipeline                 │ │
│  │  Scheduler → Collector → Comparison     │ │
│  │  → Consensus → Conflict → Judge         │ │
│  └─────────────────────────────────────────┘ │
└──────────────────────────────────────────────┘
```

---

## 12. Verdict

**Can V1 ship?** Not yet. The critical blockers are:

1. Hardcoded paths (breaks on any other machine)
2. Only 2/5 providers work
3. JudgeEngine is a stub
4. No error recovery in browser layer

**What needs to happen first:**

1. Fix hardcoded paths (1 hour)
2. Delete dead code (2 hours)
3. Decide: ship with 2 providers or implement all 5? (scope decision)
4. Implement JudgeEngine or remove the feature (scope decision)

**If scope is reduced to 2 providers (DeepSeek + Qianwen) and JudgeEngine is removed/stubbed:**
- V1 could ship in 1-2 weeks after cleanup
- The core browser automation + comparison pipeline works
- The frontend is functional

**If all 5 providers are required:**
- 3-4 weeks of additional development
- Each provider needs a browser adapter with site-specific selectors
- Anti-detection tuning per site

---

*End of CTO Audit*
