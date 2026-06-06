# Cleanup Candidates Audit

**Date:** 2026-06-06
**Scope:** /home/greenpool/omnicouncil-app

---

## 1. Files Matching Cleanup Patterns

### Pattern: `*old*` — LOG.old files (browser session data)

These are Chromium LevelDB log rotation artifacts from embedded browser sessions. They are safe to delete.

| File | Size Note |
|------|-----------|
| `backend/engine/data/deepseek_session/Default/IndexedDB/https_chat.deepseek.com_0.indexeddb.leveldb/LOG.old` | Session data |
| `backend/engine/data/deepseek_session/Default/Local Storage/leveldb/LOG.old` | Session data |
| `backend/engine/data/deepseek_session/Default/PersistentOriginTrials/LOG.old` | Session data |
| `backend/engine/data/deepseek_session/Default/Session Storage/LOG.old` | Session data |
| `backend/engine/data/deepseek_session/Default/shared_proto_db/LOG.old` | Session data |
| `backend/engine/data/deepseek_session/Default/shared_proto_db/metadata/LOG.old` | Session data |
| `backend/engine/data/qianwen_session/Default/IndexedDB/https_www.qianwen.com_0.indexeddb.leveldb/LOG.old` | Session data |
| `backend/engine/data/qianwen_session/Default/Local Storage/leveldb/LOG.old` | Session data |
| `backend/engine/data/qianwen_session/Default/PersistentOriginTrials/LOG.old` | Session data |
| `backend/engine/data/qianwen_session/Default/Session Storage/LOG.old` | Session data |
| `backend/engine/data/qianwen_session/Default/shared_proto_db/LOG.old` | Session data |
| `backend/engine/data/qianwen_session/Default/shared_proto_db/metadata/LOG.old` | Session data |

**Aggregate sizes:**
- `deepseek_session/` — 5.8 MB
- `qianwen_session/` — 37 MB

### Pattern: `*test*` — Test-related files outside proper test suites

| File | Notes |
|------|-------|
| `scripts/test-e2e.py` | Legitimate E2E test script; not a cleanup candidate |
| `backend/pytest.ini` | Test config; not a cleanup candidate |
| `src-tauri/target/debug/build/ring-*/out/*test*` | Build artifacts inside `target/debug/` (846 MB total); standard Rust build output |

### Pattern: `*debug*` — Debug build artifacts

The entire `src-tauri/target/debug/` directory (846 MB) is a Rust debug build artifact. This is standard and excluded from `.gitignore`, but is the single largest space consumer. Run `cargo clean` in `src-tauri/` to reclaim space when not actively developing the Rust side.

### Pattern: `*bak*`, `*tmp*`, `*draft*`, `*wip*`, `*hack*`, `*todo*`, `*backup*`, `*temp*`

No files found matching these patterns.

---

## 2. TODO Comments

| File | Line | Content |
|------|------|---------|
| `src/components/AIPlatformManager.tsx` | 101 | `// TODO: Call backend to clear cookies` |
| `src/components/AIPlatformManager.tsx` | 106 | `// TODO: Call backend to delete all data for this AI` |

**Context:** Both TODOs are in `handleDisable` and `handleDelete` functions. The UI updates local state but does not yet call the backend to perform the actual cookie/data cleanup. These represent missing functionality.

---

## 3. FIXME Comments

None found.

---

## 4. HACK Comments

None found.

---

## 5. DEBUG Code

| File | Line | Content |
|------|------|---------|
| `backend/browser/embedded_engine.py` | 18 | `DEBUG_LOG = "C:\\Users\\green\\.omnicouncil\\login.log"` |
| `backend/browser/embedded_engine.py` | 25-26 | `os.makedirs(os.path.dirname(DEBUG_LOG), exist_ok=True)` / writes to DEBUG_LOG |

**Issue:** This is a hardcoded debug logging path pointing to a specific Windows user directory (`C:\Users\green\`). It bypasses the standard logging framework and writes directly to a file. This should be removed or made configurable.

---

## 6. Hardcoded User Paths (Related to DEBUG)

| File | Line | Content |
|------|------|---------|
| `backend/browser/embedded_engine.py` | 18 | `DEBUG_LOG = "C:\\Users\\green\\.omnicouncil\\login.log"` |
| `backend/browser/embedded_engine.py` | 36 | `self._auth_dir = auth_dir or "C:\\Users\\green\\.omnicouncil\\auth"` |
| `backend/main.py` | 367 | `_debug_dir = os.path.join(os.environ.get("USERPROFILE", "C:\\Users\\green"), ".omnicouncil")` |
| `backend/main.py` | 563 | `debug_path = "C:\\Users\\green\\.omnicouncil\\login.log"` |

**Issue:** Four instances of hardcoded `C:\Users\green\` paths. These will break on any other user's machine or on Linux. Should use `Path.home()` or environment variables consistently.

---

## 7. console.log Debug Statements (TypeScript)

| File | Line | Content |
|------|------|---------|
| `src/stores/appStore.ts` | 196 | `console.log('[Engine] Status:', data);` |
| `src/stores/appStore.ts` | 209 | `console.log('[Auth]', data.ai_id, data.status, data.message);` |
| `src/hooks/useWebSocket.ts` | 23 | `console.log('[WS] Connected');` |
| `src/hooks/useWebSocket.ts` | 44 | `console.log('[WS] Disconnected');` |
| `src/hooks/useWebSocket.ts` | 50 | `console.log('[WS] Reconnecting...');` |

**Issue:** Five `console.log` calls in production source code. These should be replaced with a proper logger (e.g., `debug` package or a custom logger) that can be silenced in production builds.

---

## 8. print() Debug Statements (Python)

None found in active code (no uncommented `print()` calls outside test files).

---

## 9. Commented-Out Code Blocks

None found.

---

## 10. Log Files

11 `.log` files exist inside `backend/engine/data/*/Default/` directories. These are Chromium LevelDB internal log files (not application logs). They are part of the browser session data.

---

## Summary of Action Items

| Priority | Category | Count | Action |
|----------|----------|-------|--------|
| HIGH | Hardcoded user paths | 4 | Replace `C:\Users\green\` with `Path.home()` or env vars |
| MEDIUM | console.log statements | 5 | Replace with proper logger; disable in production |
| MEDIUM | TODO comments | 2 | Implement backend cookie/data cleanup endpoints |
| MEDIUM | DEBUG_LOG file writer | 1 | Remove or make configurable; use standard logging |
| LOW | LOG.old files | 12 | Safe to delete; auto-generated by LevelDB |
| LOW | Debug build artifacts | 846 MB | Run `cargo clean` to reclaim space if not needed |
