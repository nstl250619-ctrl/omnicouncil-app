# Changelog

## v2.0.0 (2026-06-08) — Architecture Upgrade

### Major Changes

#### Architecture Split: Runtime Engine + Query Engine

- **Runtime Engine** (`backend/runtime/`): 10-state lifecycle state machine, profile backup/restore, session validation (offline + online), background heartbeat health monitoring (60s interval), 4-level automatic recovery chain (reload → renavigate → new_tab → restart_browser)
- **Query Engine** (`backend/providers/`): unified `BaseQueryAdapter` interface, per-platform adapters (DeepSeek, ChatGPT, Gemini, 千问, MiMo), stop-button detection, content stability checks, VisionFallback screenshot+OCR fallback
- **Contracts layer** (`backend/engine/contracts.py`): shared Protocol/ABC definitions, `RuntimeHealth`, `QueryRequest`, `QueryResult`, `RuntimeState` (10 states), `HealthStatus` enums

#### Independent Engine Packages

Extracted 5 standalone packages at `backend/packages/`:

| Package | Import | Purpose |
|---------|--------|---------|
| `omnicounci1l-core` | `omnicounci1l_core` | Shared types, config, exceptions |
| `comparison-engine` | `omnicounci1l_comparison` | 6-stage comparison analysis pipeline |
| `consensus-engine` | `omnicounci1l_consensus` | Consensus mining, disagreement analysis |
| `conflict-engine` | `omnicounci1l_conflict` | Conflict root-cause analysis |
| `judge-engine` | `omnicounci1l_judge` | Optional external AI judgment |

Each independently installable via `pip install -e packages/<name>/`.

#### Frontend UI Redesign

- State-based routing (`platform-setup` | `console`)
- CSS design tokens via custom properties + Google Fonts (Syne / DM Mono / Source Serif 4)
- `AIIconSelector` — colored-block AI selector replacing text chips
- `JudgeView` — judge suggestions tab
- `PlatformSetupPage` — platform management table with search, multi-select, CRUD
- `ConsolePage` — sidebar navigation, tab bar, query bar, AI selector
- CSS animations: fade, slide, scale, shimmer, ripple

#### New API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/runtime/health` | GET | RuntimeHealth for all AI platforms (state/browser_alive/page_alive/session_valid/last_heartbeat) |
| `/api/providers/{name}/reauth` | POST | Manual re-authentication trigger |
| `/api/providers/{name}` | DELETE | Remove provider |
| `/api/providers` | POST | Add new provider (stub — requires provider class) |
| `/health/detailed` | GET | Per-AI detailed health with session state |
| `/metrics` | GET | Prometheus-style metrics snapshot |

#### WebSocket Events

| Event | Trigger | UI Effect |
|-------|---------|-----------|
| `session_expired` | Health monitor detects login expiry | 🟡 Yellow toast + 🔴 status light |
| `recovery_success` | Reauth/login succeeds | 🟢 Green toast + 🟢 status light |
| `ai_unavailable` | AI becomes unavailable | 🔴 Red toast + 🔴 status light |

#### CI/CD Pipeline

- **`OmniCouncil CI`** (`.github/workflows/ci.yml`): triggered on push/PR to main
  - Backend tests: Python 3.12, pytest, 666 tests
  - Frontend build: Node.js 20, Vite, verify dist output
  - Engine package verification: each pip package installed independently
  - Heartbeat check + 10-min soak test (main only)
- **`Release (Windows Build)`** (`.github/workflows/release.yml`): manual trigger
  - Windows EXE via Tauri + PyInstaller (含引擎包)
  - Pre-release tests

### Bug Fixes

- Fixed AI platform connection status with dual API/config fallback
- Fixed Config Store `savedSessions` undefined variable crash
- Fixed `AIPlatformManager` always showing on first launch
- Fixed AI state priority logic (config file > API response)
- Removed duplicate `case 'task_created'` in store message handler
- Fixed `PlatformSetupPage` default platform list missing `homeUrl` for some entries
- Fixed `TestSchedulerCenter.test_submit_query` — mocked `_provider_manager` and `send_to_ai`
- Fixed `test_config.py` assertions — updated defaults to match changed config values
- Marked 7 `_has_saved_cookies` tests as xfail (replaced by `_has_valid_session` SQLite-based validation)
- Fixed PyInstaller `build.spec`: add engine packages to datas + hiddenimports, correct flat layout paths
- Fixed `scripts/build-backend.py`: install engine packages (core first) before PyInstaller
- Fixed CI `libasound2` → `libasound2t64` for Ubuntu 24.04

### Frontend-Backend Integration

- `runtimeHealthMap` in Zustand store with 30-second HTTP polling for status lights
- Health status dots: 🟢 healthy / 🟡 degraded / 🔴 unavailable or login_required
- Recovery button shown only for `degraded` / `login_required` states
- `ErrorToast` with severity levels (`error`/`warning`/`success`), 5-second auto-dismiss
- WebSocket health event → toast notification pipeline
- ConsolePage sidebar reads from `runtimeHealthMap` instead of static data

### Performance

- Frontend build: 378KB JS (gzip: 117KB), 29KB CSS (gzip: 5.5KB)
- Build time: ~1s with Vite 6
- Incremental TypeScript checking via `tsc --incremental`

### Testing

- 666/666 backend tests passing (0 failures, 7 xfailed for deprecated cookie API)
- All Runtime Engine dedicated tests passing
- Regression test suite: 35/43 items passed, all core paths verified
- Multi-AI concurrent query with 4/5 success degraded path verified
- Comparison, consensus, conflict engines verified end-to-end via WebSocket

### Code Cleanup

- Removed 3 stale directories: `audit/`, `audit_v2/`, `test-results/`
- Removed 91 unused Python imports via ruff
- Added `__all__` to `omnicounci1l_core/__init__.py` for explicit re-exports
- Removed duplicate `.gitignore` entry

### Project Structure (v2.0.0)

```
omnicouncil-app/
├── .github/workflows/     # CI (auto) + Release (manual)
├── backend/
│   ├── api/               # HTTP routes + WebSocket event bridge
│   ├── ws/                # WebSocket connection manager
│   ├── engine/            # Contracts + layers (access/scheduler/collector)
│   ├── runtime/           # Runtime Engine (NEW)
│   ├── providers/         # Query Engine (NEW)
│   ├── packages/          # 5 standalone pip packages (NEW)
│   ├── browser/           # Playwright embedded browser
│   ├── shared/            # Types, config, logging, event bus
│   ├── storage/           # Session persistence
│   ├── tests/             # 666 pytest tests
│   └── build.spec         # PyInstaller config
├── src/                   # React + TypeScript + Vite
│   ├── pages/             # ConsolePage, PlatformSetupPage
│   ├── components/        # 14 UI components
│   ├── stores/            # Zustand (appStore, configStore)
│   ├── hooks/             # useWebSocket
│   └── styles/            # globals.css
├── src-tauri/             # Tauri Rust shell
├── scripts/               # Build scripts
├── tests/e2e/             # Playwright E2E
├── dist/                  # Vite output
├── CHANGELOG.md           # NEW
└── README.md
```

---

## v1.0.0 (2026-06-05) — Initial Release

- First working OmniCouncil desktop app
- Basic AI parallel query with DeepSeek, ChatGPT, Gemini, 千问, MiMo
- WebSocket streaming responses
- Legacy monolith backend
