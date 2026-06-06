# OmniCouncil App -- Directory Tree

Generated: 2026-06-06

> Excludes: `node_modules/`, `target/`, `dist/`, `.venv/`, `.git/`, `__pycache__/`, `.pytest_cache/`, `.claude/`, and browser session cache data under `backend/engine/data/`.

---

## Root Files

```
omnicouncil-app/
├── .gitignore
├── BUILD.md
├── README.md
├── index.html
├── package.json
├── package-lock.json
├── tsconfig.json
└── vite.config.ts
```

## audit/

```
audit/
├── 01_directory_tree.md
├── 02_file_inventory.md
├── 03_architecture.md
└── 04_provider_audit.md
```

## backend/

```
backend/
├── main.py                            # FastAPI entry point
├── pytest.ini
├── requirements.txt
│
├── adapters/                          # AI adapter layer
│   ├── __init__.py
│   ├── base.py                        # BaseProvider base class
│   ├── deepseek.py                    # DeepSeek adapter
│   ├── qianwen.py                     # Qianwen adapter
│   └── registry.py                    # ProviderRegistry auto-discovery
│
├── browser/                           # Browser engine abstraction
│   ├── __init__.py
│   ├── cdp_engine.py                  # CDP Chrome takeover
│   ├── embedded_engine.py             # Embedded Chromium
│   ├── engine.py                      # BrowserEngine abstract base
│   ├── factory.py                     # Engine factory
│   └── manager/
│       ├── __init__.py
│       └── browser_manager.py         # Browser lifecycle management
│
├── config/
│   └── default.yaml
│
├── engine/                            # Core business engine
│   ├── collector/
│   │   ├── __init__.py
│   │   ├── collector.py
│   │   └── response.py
│   ├── comparison/
│   │   ├── __init__.py
│   │   ├── engine.py
│   │   └── result.py
│   ├── conflict/
│   │   ├── __init__.py
│   │   ├── engine.py
│   │   └── result.py
│   ├── consensus/
│   │   ├── __init__.py
│   │   ├── engine.py
│   │   └── result.py
│   ├── judge/
│   │   ├── __init__.py
│   │   ├── engine.py
│   │   └── result.py
│   ├── layers/                        # 4-layer architecture
│   │   ├── __init__.py
│   │   ├── layer1_ai_access/
│   │   │   ├── __init__.py
│   │   │   ├── adapter.py
│   │   │   ├── browser_adapter.py
│   │   │   ├── manager.py
│   │   │   ├── response_normalizer.py
│   │   │   ├── adapters/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── deepseek.py
│   │   │   │   ├── deepseek_browser.py
│   │   │   │   ├── gemini.py
│   │   │   │   ├── qianwen.py
│   │   │   │   └── qianwen_browser.py
│   │   │   ├── config/
│   │   │   │   ├── deepseek.json
│   │   │   │   ├── gemini.json
│   │   │   │   └── qianwen.json
│   │   │   └── managers/
│   │   │       ├── __init__.py
│   │   │       ├── circuit_breaker.py
│   │   │       ├── provider_manager.py
│   │   │       └── rate_limiter.py
│   │   ├── layer2_scheduler/
│   │   │   ├── __init__.py
│   │   │   ├── concurrency_controller.py
│   │   │   ├── retry_manager.py
│   │   │   ├── scheduler_center.py
│   │   │   └── timeout_manager.py
│   │   ├── layer3_collector/
│   │   │   ├── __init__.py
│   │   │   └── result_collector.py
│   │   └── layer4_comparison/
│   │       ├── __init__.py
│   │       ├── comparison_config.py
│   │       ├── comparison_engine.py
│   │       ├── clustering/
│   │       │   └── union_find.py
│   │       ├── pipeline/
│   │       │   ├── __init__.py
│   │       │   ├── comparison_assembler.py
│   │       │   ├── difference_analyzer.py
│   │       │   ├── semantic_unit_extractor.py
│   │       │   ├── similarity_analyzer.py
│   │       │   ├── text_preprocessor.py
│   │       │   └── unique_insight_extractor.py
│   │       └── similarity/
│   │           ├── __init__.py
│   │           ├── cosine_similarity.py
│   │           ├── lcs_calculator.py
│   │           └── tfidf_calculator.py
│   ├── scheduler/
│   │   ├── __init__.py
│   │   ├── scheduler.py
│   │   └── task.py
│   └── session/
│       ├── __init__.py
│       ├── manager.py
│       └── storage.py
│
├── providers/                         # AI provider integrations
│   ├── __init__.py
│   ├── base/
│   │   ├── __init__.py
│   │   └── provider.py
│   ├── chatgpt/
│   │   ├── __init__.py
│   │   └── provider.py
│   ├── claude/
│   │   ├── __init__.py
│   │   └── provider.py
│   ├── deepseek/
│   │   ├── __init__.py
│   │   └── provider.py
│   ├── gemini/
│   │   ├── __init__.py
│   │   └── provider.py
│   ├── qianwen/
│   │   ├── __init__.py
│   │   └── provider.py
│   └── registry/
│       ├── __init__.py
│       └── registry.py
│
├── shared/                            # Shared utilities
│   ├── __init__.py
│   ├── config.py
│   ├── errors.py
│   ├── event_bus.py
│   └── types.py
│
├── storage/                           # Local persistence
│   ├── __init__.py
│   └── local.py
│
└── tests/
    ├── __init__.py
    ├── test_browser_engine.py
    ├── test_login_flow.py
    ├── test_profile_sharing.py
    └── test_websocket.py
```

## src/ (Frontend -- React + TypeScript)

```
src/
├── main.tsx                           # Entry point
├── App.tsx                            # Root component
│
├── components/
│   ├── AIPlatformManager.tsx          # AI platform management
│   ├── ComparisonTab.tsx              # Comparison analysis tab
│   ├── ConflictTab.tsx                # Conflict analysis tab
│   ├── ConsensusTab.tsx               # Consensus analysis tab
│   ├── ErrorToast.tsx                 # Error notifications
│   ├── Header.tsx                     # App header
│   ├── HistoryView.tsx                # History records tab
│   ├── QueryInput.tsx                 # Input area + AI selection
│   ├── ResponsesTab.tsx               # AI response cards
│   ├── Settings.tsx                   # Settings page
│   ├── SetupWizard.tsx                # First-run wizard
│   ├── SkeletonLoader.tsx             # Skeleton loading UI
│   ├── StatusBar.tsx                  # Status bar
│   ├── TabBar.tsx                     # Tab navigation
│   └── Titlebar.tsx                   # Custom titlebar
│
├── hooks/
│   └── useWebSocket.ts                # WebSocket connection hook
│
├── stores/
│   ├── appStore.ts                    # Application state (Zustand)
│   └── configStore.ts                 # Config persistence
│
└── styles/
    └── globals.css                    # Global styles + tokens
```

## src-tauri/ (Rust -- Tauri Desktop Shell)

```
src-tauri/
├── Cargo.toml
├── Cargo.lock
├── build.rs
├── tauri.conf.json
└── src/
    ├── main.rs                        # Window management + system tray
    └── python_manager.rs              # Python subprocess management
```

## scripts/

```
scripts/
├── build-windows.ps1                  # Windows build script
└── test-e2e.py                        # E2E test runner
```

---

## Summary

| Area | Description | Source Files |
|------|-------------|-------------|
| **Root** | Project config (Vite, TS, package.json, HTML) | 8 |
| **backend/** | Python FastAPI backend | ~75 |
| **backend/engine/layers/** | 4-layer engine (AI access, scheduler, collector, comparison) | ~35 |
| **backend/providers/** | AI provider integrations (ChatGPT, Claude, DeepSeek, Gemini, Qianwen) | ~14 |
| **src/** | React + TypeScript frontend | 19 |
| **src-tauri/** | Rust Tauri desktop shell | 5 |
| **scripts/** | Build and test automation | 2 |
| **audit/** | Audit documentation | 4 |

### File Counts by Language

| Language | Extension | Count |
|----------|-----------|-------|
| Python | `.py` | ~55 |
| TypeScript/TSX | `.ts` / `.tsx` | ~17 |
| Rust | `.rs` | 2 |
| Config | `.json` / `.yaml` / `.toml` | ~8 |
| CSS | `.css` | 1 |
| PowerShell | `.ps1` | 1 |
| Markdown | `.md` | ~6 |
