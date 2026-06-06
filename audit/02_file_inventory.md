# File Inventory Report

**Project:** /home/greenpool/omnicouncil-app
**Generated:** 2026-06-06

---

## 1. File Count by Type

| Category | Extensions | File Count | Line Count |
|----------|-----------|------------|------------|
| Python | `*.py` | 100 | 8,065 |
| TypeScript | `*.ts`, `*.tsx` | 21 | 2,288 |
| Rust | `*.rs` | 3 | 429 |
| **Total Source** | | **124** | **10,782** |
| Other (config, docs) | `*.json`, `*.yaml`, `*.toml`, `*.html`, `*.css`, `*.md`, etc. | 21 | -- |

---

## 2. TOP 50 Largest Source Files (by Line Count)

| Rank | Lines | File |
|------|-------|------|
| 1 | 684 | `backend/main.py` |
| 2 | 361 | `backend/browser/embedded_engine.py` |
| 3 | 296 | `backend/engine/layers/layer2_scheduler/scheduler_center.py` |
| 4 | 265 | `backend/shared/types.py` |
| 5 | 252 | `backend/engine/layers/layer1_ai_access/adapters/gemini.py` |
| 6 | 248 | `src/components/AIPlatformManager.tsx` |
| 7 | 238 | `src/components/SetupWizard.tsx` |
| 8 | 230 | `backend/engine/layers/layer1_ai_access/browser_adapter.py` |
| 9 | 228 | `src/stores/appStore.ts` |
| 10 | 225 | `src-tauri/src/main.rs` |
| 11 | 216 | `backend/browser/cdp_engine.py` |
| 12 | 201 | `src-tauri/src/python_manager.rs` |
| 13 | 197 | `backend/engine/layers/layer1_ai_access/manager.py` |
| 14 | 193 | `src/components/ConflictTab.tsx` |
| 15 | 188 | `scripts/test-e2e.py` |
| 16 | 188 | `backend/engine/comparison/engine.py` |
| 17 | 173 | `src/components/Settings.tsx` |
| 18 | 172 | `backend/tests/test_login_flow.py` |
| 19 | 169 | `backend/tests/test_profile_sharing.py` |
| 20 | 167 | `src/components/ConsensusTab.tsx` |
| 21 | 160 | `src/components/ComparisonTab.tsx` |
| 22 | 160 | `backend/engine/layers/layer3_collector/result_collector.py` |
| 23 | 160 | `backend/engine/layers/layer1_ai_access/adapters/deepseek.py` |
| 24 | 158 | `backend/engine/layers/layer1_ai_access/adapters/qianwen.py` |
| 25 | 140 | `src/components/ResponsesTab.tsx` |
| 26 | 137 | `backend/engine/layers/layer4_comparison/pipeline/difference_analyzer.py` |
| 27 | 136 | `backend/engine/judge/engine.py` |
| 28 | 126 | `src/stores/configStore.ts` |
| 29 | 122 | `backend/shared/errors.py` |
| 30 | 121 | `backend/engine/scheduler/scheduler.py` |
| 31 | 113 | `backend/engine/consensus/engine.py` |
| 32 | 112 | `backend/engine/layers/layer4_comparison/comparison_engine.py` |
| 33 | 111 | `backend/engine/layers/layer1_ai_access/adapters/qianwen_browser.py` |
| 34 | 111 | `backend/browser/engine.py` |
| 35 | 105 | `backend/providers/chatgpt/provider.py` |
| 36 | 105 | `backend/engine/layers/layer1_ai_access/response_normalizer.py` |
| 37 | 104 | `src/App.tsx` |
| 38 | 103 | `backend/tests/test_browser_engine.py` |
| 39 | 103 | `backend/engine/conflict/engine.py` |
| 40 | 103 | `backend/adapters/registry.py` |
| 41 | 102 | `backend/adapters/qianwen.py` |
| 42 | 98 | `backend/providers/registry/registry.py` |
| 43 | 97 | `backend/shared/event_bus.py` |
| 44 | 95 | `backend/providers/gemini/provider.py` |
| 45 | 91 | `src/components/Titlebar.tsx` |
| 46 | 91 | `backend/providers/qianwen/provider.py` |
| 47 | 90 | `backend/providers/claude/provider.py` |
| 48 | 89 | `backend/engine/layers/layer4_comparison/pipeline/comparison_assembler.py` |
| 49 | 86 | `backend/tests/test_websocket.py` |
| 50 | 86 | `backend/storage/local.py` |

---

## 3. Summary

- **Dominant language:** Python (80% of source files, 75% of source lines)
- **Frontend:** TypeScript/React (21 files, 2,288 lines) -- Tauri desktop app shell
- **Native layer:** Rust (3 files, 429 lines) -- Tauri bridge for Python process management
- **Largest file:** `backend/main.py` at 684 lines (FastAPI application entry point)
- **Files exceeding 200 lines:** 13 files (candidates for refactoring)
- **Browser session data:** `backend/engine/data/` contains Chromium session profiles (qianwen, deepseek) with cache/leveldb artifacts -- not source code
