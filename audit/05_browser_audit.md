# Browser Automation Audit

Comprehensive audit of all browser-related code in OmniCouncil.

---

## 1. Dependency Overview

**Library:** Patchright (a Playwright fork with anti-detection patches)
**Package:** `patchright>=1.0` (in `backend/requirements.txt`)
**Also listed:** `scrapling[fetchers]>=0.3` (present but not used in any browser code)
**Frontend:** No browser dependencies on the frontend/Tauri side -- all browser automation is in the Python backend.

---

## 2. File-by-File Audit

### 2.1 Core Browser Engine Layer

#### `/home/greenpool/omnicouncil-app/backend/browser/engine.py`
- **Purpose:** Abstract base class defining the browser engine interface.
- **Key classes/enums:**
  - `EngineMode` -- enum: `CDP` ("cdp") or `EMBEDDED` ("embedded")
  - `AuthStatus` -- enum: `AUTHENTICATED`, `EXPIRED`, `NOT_LOGGED_IN`, `CAPTCHA_REQUIRED`, `UNKNOWN`
  - `PageInfo` -- dataclass: per-page metadata (ai_id, url, title, is_logged_in, auth_status)
  - `EngineStatus` -- dataclass: engine-level status (mode, connected, browser_version, active_pages)
  - `BrowserEngine` -- ABC with abstract methods: `connect()`, `disconnect()`, `is_connected()`, `get_page()`, `close_page()`, `check_auth()`, `ensure_logged_in()`, `get_status()`, `save_auth_state()`, `load_auth_state()`
- **Dependencies:** None (pure abstraction)
- **Notes:** `get_page()` returns a raw Playwright `Page` object. `save_auth_state()` / `load_auth_state()` are abstract but have no-op implementations in both engines.

---

#### `/home/greenpool/omnicouncil-app/backend/browser/embedded_engine.py`
- **Purpose:** Primary engine -- launches embedded Chromium with per-AI persistent contexts.
- **Key class:** `EmbeddedEngine(BrowserEngine)`
- **Key methods:**
  - `connect()` -- imports `patchright.async_api.async_playwright`, starts it, scans for saved cookies for 5 known AIs
  - `disconnect()` -- closes all pages, contexts, stops playwright
  - `_get_context(ai_id)` -- creates/returns a persistent context per AI via `chromium.launch_persistent_context(profile_dir, headless, args=["--disable-blink-features=AutomationControlled"])`
  - `get_page(ai_id, url)` -- reuses existing page or creates new one in the AI's context
  - `login(ai_id, url)` -- launches a **visible** (non-headless) persistent browser for manual login, waits for user to close the window, then saves `storage_state()` to `{auth_dir}/{ai_id}.json`
  - `_has_saved_cookies(ai_id)` -- checks for Chromium cookie files at `{profile_dir}/Default/Cookies` or `{profile_dir}/Default/Network/Cookies`
  - `_quick_login_check(ai_id, page)` -- AI-specific URL/element checks to detect if already logged in
  - `check_all_sessions()` -- checks all 5 AIs for saved cookies
  - `get_authenticated_ais()` -- returns list of authenticated AI IDs
- **Dependencies:** `patchright` (async API), `pathlib`, `asyncio`
- **Key config:**
  - `auth_dir` defaults to `"C:\\Users\\green\\.omnicouncil\\auth"` (hardcoded Windows path)
  - `DEBUG_LOG` hardcoded to `"C:\\Users\\green\\.omnicouncil\\login.log"`
  - Supported AI IDs hardcoded: `["deepseek", "qianwen", "gemini", "chatgpt", "claude"]`
- **Browser launch args:** `["--disable-blink-features=AutomationControlled"]` (login adds `"--no-sandbox"` too)
- **Persistent context:** Uses `chromium.launch_persistent_context(profile_dir)` -- cookies and localStorage are automatically persisted to the Chromium profile directory on disk.

---

#### `/home/greenpool/omnicouncil-app/backend/browser/cdp_engine.py`
- **Purpose:** Alternative engine -- connects to a locally running Chrome via Chrome DevTools Protocol.
- **Key class:** `CDPEngine(BrowserEngine)`
- **Key methods:**
  - `connect()` -- imports `patchright.async_api.async_playwright`, connects via `chromium.connect_over_cdp(cdp_url)` (default `http://localhost:9222`)
  - `disconnect()` -- closes pages but does NOT close Chrome (it's the user's browser)
  - `get_page(ai_id, url)` -- creates pages in the CDP browser context
  - `save_auth_state()` / `load_auth_state()` -- no-ops (uses Chrome's own cookies)
- **Dependencies:** `patchright` (async API)
- **Notes:** Requires Chrome started with `--remote-debugging-port=9222`. Reuses the user's existing Chrome session (cookies, extensions, Cloudflare bypass). Currently not the default mode.

---

#### `/home/greenpool/omnicouncil-app/backend/browser/factory.py`
- **Purpose:** Factory function to create the appropriate engine.
- **Key function:** `create_engine(mode, auth_dir, cdp_url, headless)` -- returns `CDPEngine` or `EmbeddedEngine` based on mode.
- **Dependencies:** Imports both engine classes.
- **Default auth_dir:** `~/.omnicouncil/auth` (via `Path.home()`)

---

#### `/home/greenpool/omnicouncil-app/backend/browser/manager/browser_manager.py`
- **Purpose:** Standalone browser lifecycle manager (launch, connect, disconnect).
- **Key class:** `BrowserManager`
- **Key methods:**
  - `launch(headless)` -- launches Chromium via `patchright` with `--disable-blink-features=AutomationControlled`
  - `disconnect()` -- closes browser and stops playwright
  - Properties: `playwright`, `browser`, `is_connected`
- **Dependencies:** `patchright` (async API)
- **Notes:** This class is defined but does NOT appear to be used anywhere in the codebase. It was likely an earlier implementation before the engine abstraction was built.

---

### 2.2 Browser-Based AI Adapters

#### `/home/greenpool/omnicouncil-app/backend/engine/layers/layer1_ai_access/browser_adapter.py`
- **Purpose:** Base class for AI adapters that use BrowserEngine for page automation.
- **Key class:** `BrowserAIAdapter(AIAdapter)`
- **Key methods:**
  - `send_prompt(prompt, options)` -- orchestrates: get page -> check auth -> find input -> type + send -> wait -> extract response. On `AILoginRequiredError`, triggers `ensure_logged_in()` and retries.
  - `_send_async(prompt, timeout_ms)` -- core send logic: navigates page, fills textarea, presses Enter, waits for response
  - `_find_input(page)` -- iterates CSS selectors from config to find the input element
  - `_extract_response(page, prompt, timeout_ms)` -- polls body text, finds prompt, extracts lines after it, waits for idle
  - `_is_ui_element(text)` -- filters out UI chrome from response text
  - `new_conversation()` -- closes the page for this AI
- **Dependencies:** `BrowserEngine`, `AILoginRequiredError`
- **Notes:** Uses Playwright page methods directly: `page.locator()`, `page.keyboard.press()`, `page.wait_for_timeout()`, `page.goto()`

---

#### `/home/greenpool/omnicouncil-app/backend/engine/layers/layer1_ai_access/adapters/deepseek_browser.py`
- **Purpose:** DeepSeek-specific browser adapter.
- **Key class:** `DeepSeekBrowserAdapter(BrowserAIAdapter)`
- **Key methods:**
  - `_find_input(page)` -- tries `textarea` and `div[contenteditable='true']`
  - `_is_ui_element(text)` -- filters DeepSeek-specific UI elements (DeepThink, Search, etc.)
- **Config:** Loads from `backend/engine/layers/layer1_ai_access/config/deepseek.json`, falls back to hardcoded defaults
- **URL:** `https://chat.deepseek.com`

---

#### `/home/greenpool/omnicouncil-app/backend/engine/layers/layer1_ai_access/adapters/qianwen_browser.py`
- **Purpose:** Qianwen (千问) specific browser adapter.
- **Key class:** `QianwenBrowserAdapter(BrowserAIAdapter)`
- **Key methods:**
  - `_find_input(page)` -- tries `textarea`, `[contenteditable='true']`, `[role='textbox']`
  - `_extract_response(page, prompt, timeout_ms)` -- handles non-breaking spaces (`\xa0`)
  - `_is_ui_element(text)` -- filters Qianwen-specific UI elements
- **Config:** Loads from `backend/engine/layers/layer1_ai_access/config/qianwen.json`
- **URL:** `https://tongyi.aliyun.com/qianwen`

---

### 2.3 Session / Cookie Management

#### `/home/greenpool/omnicouncil-app/backend/engine/session/manager.py`
- **Purpose:** Coordinates login state across providers.
- **Key class:** `SessionManager`
- **Key methods:**
  - `is_authenticated(provider_id)` -- checks in-memory set
  - `set_authenticated(provider_id, bool)` -- updates set + timestamp
  - `has_saved_session(provider_id)` -- delegates to `SessionStorage`
  - `get_profile_dir(provider_id)` -- delegates to `SessionStorage`
- **Dependencies:** `SessionStorage`

---

#### `/home/greenpool/omnicouncil-app/backend/engine/session/storage.py`
- **Purpose:** Manages session data persistence on disk.
- **Key class:** `SessionStorage`
- **Key methods:**
  - `get_profile_dir(provider_id)` -- returns `{base_dir}/auth/{provider_id}_profile` (creates if needed)
  - `get_auth_path(provider_id)` -- returns `{base_dir}/auth/{provider_id}.json`
  - `has_session(provider_id)` -- checks if profile dir exists and is non-empty
  - `save_session(provider_id, data)` -- writes JSON to auth path
  - `load_session(provider_id)` -- reads JSON from auth path
  - `delete_session(provider_id)` -- removes profile dir and auth file
- **Default base_dir:** `~/.omnicouncil`
- **Notes:** The `save_session`/`load_session` methods store arbitrary JSON data. The profile directories store Chromium's native persistent context data (cookies, localStorage, etc.).

---

### 2.4 Provider Base (Browser-Aware Interface)

#### `/home/greenpool/omnicouncil-app/backend/providers/base/provider.py`
- **Purpose:** Abstract base for all AI providers -- defines the page-level interface.
- **Key class:** `BaseProvider(ABC)`
- **Key methods:**
  - `check_login(page)` -- receives a Playwright Page, returns bool
  - `send_message(page, message)` -- receives a Playwright Page, sends message, returns response
  - `on_login_start(page)` / `on_login_success(page)` / `on_session_expired(page)` -- lifecycle hooks
  - `get_input_selector()` / `get_submit_selector()` -- CSS selectors
- **Dependencies:** None (abstract)
- **Notes:** This is the provider registry interface. The `ProviderConfig` dataclass includes `login_url` and `chat_url` which are used by the browser engine.

---

### 2.5 Configuration Files

#### `/home/greenpool/omnicouncil-app/backend/engine/layers/layer1_ai_access/config/deepseek.json`
- DeepSeek selectors for: loginInput, codeInput, passwordToggle, inputBox, sendButton, responseContainer, responseContent, stopButton, newChatButton
- Timing: typingDelay 30-80ms, afterSendWait 1500ms, maxResponseWait 180000ms
- Detection: idle_timeout strategy, idleTimeoutMs 3000

#### `/home/greenpool/omnicouncil-app/backend/engine/layers/layer1_ai_access/config/qianwen.json`
- Qianwen selectors for: inputBox, sendButton, responseContainer, responseContent
- Timing: afterSendWait 2000ms, maxResponseWait 180000ms
- Login URL: `https://tongyi.aliyun.com`

#### `/home/greenpool/omnicouncil-app/backend/engine/layers/layer1_ai_access/config/gemini.json`
- Gemini selectors for: inputBox, sendButton, responseContainer, responseContent
- Timing: afterSendWait 2000ms, maxResponseWait 180000ms
- Login URL: `https://gemini.google.com`

#### `/home/greenpool/omnicouncil-app/backend/config/default.yaml`
- No browser-specific config. Contains scheduler, comparison, and rate_limit settings.

---

### 2.6 Main Entry Point (Browser Integration)

#### `/home/greenpool/omnicouncil-app/backend/main.py`
- **Browser initialization (lifespan):**
  ```python
  browser_engine = create_engine("embedded", headless=True)
  connected = await browser_engine.connect()
  ```
- **Adapter registration:**
  ```python
  deepseek = DeepSeekBrowserAdapter(browser_engine)
  qianwen = QianwenBrowserAdapter(browser_engine)
  ```
- **Session check endpoint:** `GET /api/sessions/status` -- calls `browser_engine.check_all_sessions()` and `get_authenticated_ais()`
- **Reauth handler:** `_do_login(ai_id, login_url)` -- calls `browser_engine.login()` which opens visible browser for manual login
- **WebSocket message `check_sessions`** -- same as REST endpoint
- **Cleanup:** `await browser_engine.disconnect()` in lifespan shutdown

---

### 2.7 Frontend Browser-Related Code

#### `/home/greenpool/omnicouncil-app/src/stores/configStore.ts`
- Stores `engineMode: 'cdp' | 'embedded'` (default: `'embedded'`)
- `loadConfig()` fetches `GET /api/sessions/status` to check which AIs have saved sessions
- `completeSetup(mode)` saves engine mode selection

#### `/home/greenpool/omnicouncil-app/src/stores/appStore.ts`
- Handles `auth_status` WebSocket messages from backend login flow
- Stores `authStatus: Record<string, { status: string; message: string }>` per AI

---

### 2.8 Test Files

#### `/home/greenpool/omnicouncil-app/backend/tests/test_browser_engine.py`
- Tests factory creation for both CDP and embedded modes
- Tests CDPEngine and EmbeddedEngine initial state
- Tests connect failure handling
- Tests AuthStatus enum values
- Tests EngineStatus and PageInfo dataclasses

#### `/home/greenpool/omnicouncil-app/backend/tests/test_login_flow.py`
- Tests per-AI profile directory isolation
- Tests cookie detection (present, empty, missing)
- Tests authentication state management
- Tests URL-based login detection for DeepSeek and Qianwen
- Tests engine lifecycle (connect/disconnect)
- Uses `tempfile` for isolated test auth directories

#### `/home/greenpool/omnicouncil-app/backend/tests/test_profile_sharing.py`
- Tests the core invariant: login() and get_page() use the same profile directory
- Tests cookie detection logic
- Tests per-AI context creation and reuse
- Tests engine lifecycle

#### `/home/greenpool/omnicouncil-app/scripts/test-e2e.py`
- E2E test that runs against a live backend
- Tests health endpoint, WebSocket connection, query submission
- Not browser-specific but exercises the full pipeline that uses browser automation

---

## 3. How the Browser is Launched

| Mode | Method | Headless | Context Type |
|------|--------|----------|--------------|
| Embedded (default) | `chromium.launch_persistent_context(profile_dir)` | True (work), False (login) | Per-AI persistent context |
| CDP | `chromium.connect_over_cdp("http://localhost:9222")` | N/A (uses existing Chrome) | Shared context |

**Default mode:** `"embedded"` (hardcoded in `main.py` line 267)

**Anti-detection args:** `["--disable-blink-features=AutomationControlled"]` on all launches. Login mode adds `"--no-sandbox"`.

**Library used:** `patchright` (imported as `from patchright.async_api import async_playwright`). Patchright is a Playwright fork that patches browser fingerprints to avoid bot detection.

---

## 4. How Cookies are Stored/Loaded

### Embedded Mode (Persistent Context)

**Storage mechanism:** Chromium's native persistent context. When `launch_persistent_context(profile_dir)` is called, Chromium stores all cookies, localStorage, sessionStorage, and other browser data directly in the `profile_dir` directory.

**Profile directory structure:**
```
~/.omnicouncil/auth/
  deepseek_profile/
    Default/
      Cookies          <-- Chromium cookie DB (SQLite)
      Network/
        Cookies        <-- Alternative location in newer Chromium
      Local Storage/
      Session Storage/
      ...
  qianwen_profile/
    Default/
      Cookies
      ...
```

**Cookie detection:** `_has_saved_cookies(ai_id)` checks for non-empty `Cookies` file at both `Default/Cookies` and `Default/Network/Cookies`.

**Additional storage:** `login()` also calls `browser.storage_state(path="{auth_dir}/{ai_id}.json")` which exports cookies + localStorage to a JSON file.

### CDP Mode

**No explicit cookie management.** The engine uses Chrome's own cookie store. `save_auth_state()` and `load_auth_state()` are no-ops.

---

## 5. How Persistent Sessions Work

### Login Flow

1. Frontend sends `reauth` WebSocket message with `ai_id`
2. Backend calls `_do_login(ai_id, login_url)` in background
3. `EmbeddedEngine.login()` launches a **visible** Chromium window with the same profile directory used for work
4. User manually logs in on the AI website
5. User closes the browser window (detected via page close event)
6. Engine calls `browser.storage_state(path=auth_json)` to export state
7. Engine checks for cookie files via `_has_saved_cookies()`
8. On success, adds AI to `_authenticated` set and broadcasts `auth_status: authenticated`

### Work Session

1. `get_page(ai_id, url)` calls `_get_context(ai_id)` which either returns existing context or creates new persistent context from the same profile directory
2. Since login and work share the same profile directory, cookies are automatically shared
3. Pages are cached in `_pages` dict and reused across requests

### Key Invariant

**Login and work share the same profile directory.** This is the core design -- no explicit cookie transfer is needed because both contexts read from the same on-disk Chromium profile.

---

## 6. Browser-Related Configuration Summary

| Setting | Value | Source |
|---------|-------|--------|
| Default engine mode | `"embedded"` | `main.py` line 267 |
| Auth directory | `~/.omnicouncil/auth` | `factory.py`, `SessionStorage` |
| Headless (work) | `True` | `main.py` line 267 |
| Headless (login) | `False` | `embedded_engine.py` line 169 |
| Login timeout | 300 seconds | `embedded_engine.py` line 213 |
| Anti-detection args | `--disable-blink-features=AutomationControlled` | All engine files |
| CDP URL | `http://localhost:9222` | `factory.py`, `cdp_engine.py` |
| Page navigation timeout | 30000ms (work), 45000ms (login) | engine files |
| Post-navigation wait | 2000ms | engine files |
| Response idle timeout | 3000ms | adapter configs |
| Max response wait | 120000ms (default) | `SubmitOptions.timeout_ms` |

---

## 7. Dependency Graph

```
main.py
  |
  +-- browser/factory.py
  |     +-- browser/embedded_engine.py  (patchright)
  |     +-- browser/cdp_engine.py       (patchright)
  |     +-- browser/engine.py           (abstract base)
  |
  +-- engine/layers/layer1_ai_access/
  |     +-- browser_adapter.py          (uses BrowserEngine)
  |     +-- adapters/deepseek_browser.py (extends BrowserAIAdapter)
  |     +-- adapters/qianwen_browser.py  (extends BrowserAIAdapter)
  |     +-- manager.py                  (orchestrates adapters)
  |
  +-- engine/session/
  |     +-- manager.py                  (SessionManager)
  |     +-- storage.py                  (SessionStorage, disk I/O)
  |
  +-- providers/base/provider.py        (abstract page-level interface)
```

---

## 8. Issues and Observations

### Hardcoded Paths
- `embedded_engine.py` has hardcoded Windows path `"C:\\Users\\green\\.omnicouncil\\auth"` as fallback
- `embedded_engine.py` has hardcoded `DEBUG_LOG = "C:\\Users\\green\\.omnicouncil\\login.log"`
- `main.py` `_do_login()` also hardcodes the same debug path
- `factory.py` uses `Path.home()` which is platform-aware, but the engine overrides it

### Unused Code
- `BrowserManager` in `browser/manager/browser_manager.py` is not imported or used anywhere
- `scrapling[fetchers]` is in requirements.txt but never imported
- `engine/session/manager.py` (`SessionManager`) exists but is not used by any other module -- `EmbeddedEngine` manages its own `_authenticated` set directly

### Incomplete Provider Coverage
- Only DeepSeek and Qianwen have browser adapters implemented
- Gemini, ChatGPT, and Claude are listed in the hardcoded AI ID check list (`connect()` line 58) but have no adapters
- Gemini has a config JSON but no browser adapter class

### Missing Error Recovery
- `save_auth_state()` and `load_auth_state()` in `EmbeddedEngine` are no-ops (always return True)
- No automatic session refresh or re-login on session expiry during work mode
- No retry logic for browser disconnection during active tasks

### Security Notes
- Cookies stored as plain Chromium profile directories on disk (no encryption beyond Chromium's defaults)
- `storage_state()` exports also stored as plain JSON
- `--no-sandbox` flag used during login mode
