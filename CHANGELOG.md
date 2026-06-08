# Changelog

## v2.0.0 (2026-06-08) — Architecture Upgrade

### Major Changes

#### Architecture Split: Runtime Engine + Query Engine

- **Runtime Engine** (new `runtime/` module): 10-state lifecycle state machine, profile backup/restore, session validation (offline + online), background heartbeat health monitoring, 4-level automatic recovery chain (reload → renavigate → new_tab → restart_browser)
- **Query Engine** (new `providers/` module): unified `BaseQueryAdapter` interface, per-platform adapters (DeepSeek, ChatGPT, Gemini, 千问, MiMo), stop-button detection, content stability checks, VisionFallback screenshot+OCR fallback
- **Contracts layer** (`engine/contracts.py`): shared Protocol/ABC definitions, `RuntimeHealth`, `QueryRequest`, `QueryResult` types

#### Independent Engine Packages

- Extracted 4 standalone packages under `backend/packages/`:
  - `omnicounci1l-comparison` — 6-stage comparison analysis pipeline
  - `omnicounci1l-consensus` — consensus mining across AI responses
  - `omnicounci1l-conflict` — conflict root-cause analysis
  - `omnicounci1l-judge` — optional external AI judgment for consensus validation
- Each package independently installable via `pip install -e packages/<name>/`

#### Frontend UI Redesign

- State-based routing (`platform-setup` | `console`)
- CSS design tokens + Google Fonts (Syne / DM Mono / Source Serif 4)
- `AIIconSelector` — colored-block AI selector replacing text chips
- `JudgeView` — judge suggestions tab with mock data
- `PlatformSetupPage` — platform management table with search, multi-select, CRUD
- `ConsolePage` — sidebar navigation, tab bar, query bar
- CSS animations: fade, slide, scale, shimmer, ripple

### New API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/runtime/health` | GET | RuntimeHealth for all AI platforms |
| `/api/providers/{name}/reauth` | POST | Manual re-authentication trigger |
| `/api/providers/{name}` | DELETE | Remove provider |
| `/api/providers` | POST | Add new provider (stub) |
| `/health/detailed` | GET | Per-AI detailed health with session state |

### WebSocket Events

- `session_expired` — AI login session expired (→ yellow toast + red status light)
- `recovery_success` — automatic recovery completed (→ green toast + green status light)
- `ai_unavailable` — AI became unavailable (→ red toast + red status light)

### Frontend-Backend Integration

- `runtimeHealthMap` in Zustand store with 30-second HTTP polling for status lights
- Health status dots: 🟢 healthy / 🟡 degraded / 🔴 unavailable or login_required
- Recovery button shown only for `degraded` / `login_required` states
- `ErrorToast` with severity levels (error/warning/success), 5-second auto-dismiss
- WebSocket event → toast notification pipeline

### Bug Fixes

- Fixed AI platform connection status with dual API/config fallback
- Fixed Config Store `savedSessions` undefined variable
- Fixed `AIPlatformManager` always showing on first launch
- Fixed AI state priority logic (config file > API response)
- Removed duplicate `case 'task_created'` in store message handler

### Performance

- Frontend build: 386KB JS (gzip: 117KB), 29KB CSS (gzip: 5.5KB)
- Build time: ~1s with Vite 6
- Incremental TypeScript checking via `tsc --incremental`

### Testing

- 659/659 backend tests passing (0 failures)
- Runtime Engine dedicated tests: 276 cases (42% of total)
- Regression test suite: all core paths verified
- Multi-AI concurrent query with 4/5 success degraded path verified
- Comparison, consensus, conflict engines verified end-to-end

### Code Cleanup

- Removed 3 stale directories (`audit/`, `audit_v2/`, `test-results/`)
- Removed 91 unused Python imports via ruff
- Added `__all__` to `omnicounci1l_core/__init__.py` for explicit re-exports
- Updated 1 TODO comment with version target
- Removed duplicate `.gitignore` entry

### Project Structure

```
omnicouncil-app/
├── backend/                  # Python FastAPI + WebSocket backend
│   ├── runtime/              # NEW — Runtime Engine
│   ├── providers/            # NEW — Query Engine adapters
│   ├── engine/               # Engine contracts + layers
│   ├── packages/             # NEW — standalone pip packages
│   │   ├── comparison-engine/
│   │   ├── consensus-engine/
│   │   ├── conflict-engine/
│   │   └── judge-engine/
│   │   └── omnicounci1l-core/
│   └── tests/                # 659 test cases
├── src/                      # React + TypeScript frontend
│   ├── pages/                # PlatformSetupPage, ConsolePage
│   ├── components/           # UI components (AIIconSelector, JudgeView, ErrorToast)
│   ├── stores/               # Zustand (appStore, configStore)
│   └── hooks/                # useWebSocket
├── dist/                     # Production build output
└── CHANGELOG.md              # NEW
```
