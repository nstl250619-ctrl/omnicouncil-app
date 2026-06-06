# Login Flow Audit

Complete trace of the login chain from UI button click to browser cookie persistence.

---

## Overview

The login flow has two distinct paths:

1. **Explicit Login (reauth)**: User clicks "Connect" in SetupWizard or AIPlatformManager, triggering a WebSocket `reauth` message that launches a visible browser for manual login.
2. **Implicit Login Check**: On startup, `EmbeddedEngine.connect()` scans the filesystem for saved Chromium cookie files and marks AIs as authenticated without any browser interaction.

There is also a **runtime login detection** path: when `BrowserAIAdapter.send_prompt()` encounters a login-required page, it catches `AILoginRequiredError` and attempts to trigger the login window automatically.

---

## Step 1: Frontend -- Login/Auth Buttons

### 1a. SetupWizard (First Launch)

**File**: `src/components/SetupWizard.tsx`

On first launch, `App.tsx` (line 60) checks `isFirstLaunch || !setupCompleted` and renders `<AIPlatformManager>` in setup mode. The older `SetupWizard` component is also available.

The user selects a browser mode (CDP or Embedded), then sees per-AI connection cards:

```tsx
// SetupWizard.tsx, line 47-48
const handleConnect = (aiId: string) => {
  send('reauth', { ai_id: aiId });
};
```

Each AI card has a "Connect" button (line 155):
```tsx
<button className="setup-next" onClick={() => handleConnect(ai.aiId)}>
  连接 {ai.aiName}
</button>
```

### 1b. AIPlatformManager (Setup + Settings)

**File**: `src/components/AIPlatformManager.tsx`

Used both during first launch (`isSetupMode=true`) and from the settings page (`isSetupMode=false`).

```tsx
// AIPlatformManager.tsx, line 89-93
const handleConnect = (aiId: string) => {
  setPlatforms(prev => prev.map(p =>
    p.aiId === aiId ? { ...p, connecting: true } : p
  ));
  send('reauth', { ai_id: aiId });
};
```

The connect button (line 166):
```tsx
<button className="platform-btn connect" onClick={() => handleConnect(platform.aiId)}>
  🔗 连接
</button>
```

### 1c. ResponsesTab (Retry on Error)

**File**: `src/components/ResponsesTab.tsx`, line 135

When an AI response fails with a login error, the retry button triggers reauth:
```tsx
onRetry={() => send('reauth', { ai_id: aiId })}
```

### 1d. Saved Session Check on Mount

Both `SetupWizard` (line 31-39) and `AIPlatformManager` (line 31-71) check for saved sessions on mount via HTTP:

```tsx
// SetupWizard.tsx, line 31-39
useEffect(() => {
  fetch('http://localhost:8765/api/sessions/status')
    .then(res => res.json())
    .then(data => {
      if (data.sessions) {
        setSavedSessions(data.sessions);
      }
    })
    .catch(() => {});
}, []);
```

`AIPlatformManager` also tries a Tauri config file fallback (line 51-66).

---

## Step 2: WebSocket -- Auth Message Transport

### 2a. useWebSocket Hook

**File**: `src/hooks/useWebSocket.ts`

Connects to `ws://127.0.0.1:8765/ws` (line 4). Provides a `send` function:

```tsx
// useWebSocket.ts, line 68-74
const send = useCallback((type: string, data: Record<string, unknown> = {}) => {
  if (wsRef.current?.readyState === WebSocket.OPEN) {
    wsRef.current.send(JSON.stringify({ type, data }));
  } else {
    console.warn('[WS] Not connected, cannot send');
  }
}, []);
```

When the frontend calls `send('reauth', { ai_id: 'deepseek' })`, it sends:
```json
{ "type": "reauth", "data": { "ai_id": "deepseek" } }
```

### 2b. WebSocket Message Routing (Backend)

**File**: `backend/main.py`, line 396-397

The WebSocket endpoint receives the message and routes by `msg_type`:

```python
elif msg_type == "reauth":
    await handle_reauth(data.get("data", {}))
```

---

## Step 3: Backend Handler -- handle_reauth

**File**: `backend/main.py`, lines 525-557

```python
async def handle_reauth(data: dict):
    ai_id = data.get("ai_id")
    if not ai_id:
        return

    # Get provider from registry
    provider = provider_registry.get(ai_id) if provider_registry else None
    if not provider:
        await ws_manager.broadcast({
            "type": "auth_status",
            "data": {"ai_id": ai_id, "status": "failed", "message": f"未知的 AI: {ai_id}"}
        })
        return

    cfg = provider.config()

    # Notify frontend: connecting
    await ws_manager.broadcast({
        "type": "auth_status",
        "data": {"ai_id": ai_id, "status": "connecting", "message": f"正在打开 {cfg.display_name} 登录窗口..."}
    })

    # Launch login in background task
    asyncio.create_task(_do_login(ai_id, cfg.login_url))
```

Key points:
- Looks up the provider from `ProviderRegistry` to get the `login_url`
- Broadcasts `auth_status` with `status: "connecting"` to the frontend
- Spawns `_do_login` as a background asyncio task (non-blocking)

### 3a. _do_login Background Task

**File**: `backend/main.py`, lines 560-597

```python
async def _do_login(ai_id: str, login_url: str):
    success, error_msg = await browser_engine.login(ai_id, login_url)

    if success:
        await ws_manager.broadcast({
            "type": "auth_status",
            "data": {"ai_id": ai_id, "status": "authenticated", "message": "登录成功"}
        })
    else:
        await ws_manager.broadcast({
            "type": "auth_status",
            "data": {"ai_id": ai_id, "status": "failed", "message": f"登录失败: {error_msg}"}
        })
```

Delegates to `browser_engine.login()` and broadcasts the result.

---

## Step 4: Browser Engine -- login() Method

**File**: `backend/browser/embedded_engine.py`, lines 144-266

This is the core login method. It launches a **visible** (non-headless) Chromium browser using the same persistent profile directory that the work engine uses.

```python
async def login(self, ai_id: str, url: str) -> tuple[bool, str]:
    profile_dir = self._get_profile_dir(ai_id)
    Path(profile_dir).mkdir(parents=True, exist_ok=True)

    # Close existing context for this AI
    if ai_id in self._contexts:
        await self._contexts[ai_id].close()
        del self._contexts[ai_id]
        self._pages.pop(ai_id, None)

    browser = await self._playwright.chromium.launch_persistent_context(
        profile_dir,
        headless=False,           # VISIBLE browser for user interaction
        no_viewport=True,         # Prevents small window (Gemini fix)
        args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
    )

    page = browser.pages[0] if browser.pages else await browser.new_page()

    # Detect user closing the browser window
    page_closed = asyncio.Event()
    page.on("close", lambda *args: page_closed.set())

    await page.goto(url, wait_until="commit", timeout=45000)
    await asyncio.sleep(3)

    # Check if already logged in from previous session
    already_logged_in = await self._quick_login_check(ai_id, page)
    if already_logged_in:
        await browser.storage_state(path=str(auth_json))
        self._authenticated.add(ai_id)
        await browser.close()
        return True, ""

    # Wait for user to close browser (up to 5 minutes)
    await asyncio.wait_for(page_closed.wait(), timeout=300)

    # Save auth state after user closes browser
    await browser.storage_state(path=str(auth_json))
    await asyncio.sleep(2)

    # Verify cookies were saved
    has_cookies = self._has_saved_cookies(ai_id)
    if has_cookies:
        self._authenticated.add(ai_id)
        return True, ""

    return False, "未检测到登录状态"
```

### 4a. Profile Directory Structure

**File**: `backend/browser/embedded_engine.py`, line 48-49

```python
def _get_profile_dir(self, ai_id: str) -> str:
    return str(Path(self._auth_dir) / f"{ai_id}_profile")
```

Default `auth_dir` is `~/.omnicouncil/auth`. Each AI gets its own profile:
- `~/.omnicouncil/auth/deepseek_profile/`
- `~/.omnicouncil/auth/qianwen_profile/`
- `~/.omnicouncil/auth/gemini_profile/`
- etc.

This is the **critical invariant**: `login()` and `get_page()` use the same `_get_profile_dir()` method, so cookies saved during login are automatically available during work.

### 4b. Quick Login Check

**File**: `backend/browser/embedded_engine.py`, lines 282-306

If the user has previously logged in and the persistent context still has valid cookies, the browser may open directly to the chat page (not the login page). The quick check detects this:

```python
async def _quick_login_check(self, ai_id: str, page: Any) -> bool:
    url = page.url
    if ai_id == "deepseek":
        if "/sign_in" not in url and "chat.deepseek.com" in url:
            textarea = page.locator("textarea")
            if await textarea.count() > 0 and await textarea.first.is_visible(timeout=1000):
                return True
    elif ai_id == "qianwen":
        if "login" not in url.lower() and "sign" not in url.lower():
            textarea = page.locator("textarea, [contenteditable='true']")
            if await textarea.count() > 0 and await textarea.first.is_visible(timeout=1000):
                return True
    return False
```

---

## Step 5: Playwright Interaction -- How the Browser Actually Logs In

The login is **entirely manual**. The application:

1. Launches a visible Chromium window (not headless)
2. Navigates to the AI's login URL
3. Waits for the user to manually log in (enter credentials, solve CAPTCHAs, etc.)
4. Detects when the user closes the browser window (page `close` event)
5. Saves the browser state (cookies + localStorage)

The Playwright `storage_state()` call (line 197, 224) persists cookies and localStorage to a JSON file:

```python
auth_json = Path(self._auth_dir) / f"{ai_id}.json"
await browser.storage_state(path=str(auth_json))
```

Additionally, because `launch_persistent_context()` is used, Chromium's own cookie database files are written to the profile directory automatically. The `_has_saved_cookies()` check relies on these Chromium-native files, not the Playwright `storage_state` JSON.

### 5a. Login URLs per AI

| AI | Login URL | Source |
|----|-----------|--------|
| DeepSeek | `https://chat.deepseek.com` | `providers/deepseek/provider.py:17` |
| Qianwen | `https://tongyi.aliyun.com/qianwen` | `providers/qianwen/provider.py:18` |
| ChatGPT | `https://chatgpt.com` | `providers/chatgpt/provider.py:20` |
| Claude | `https://claude.ai` | `providers/claude/provider.py:17` |
| Gemini | `https://gemini.google.com` | `providers/gemini/provider.py:18` |

---

## Step 6: Cookie Management -- Save/Load After Login

### 6a. Cookie Detection

**File**: `backend/browser/embedded_engine.py`, lines 268-280

```python
def _has_saved_cookies(self, ai_id: str) -> bool:
    profile_dir = Path(self._get_profile_dir(ai_id))
    cookie_paths = [
        profile_dir / "Default" / "Cookies",
        profile_dir / "Default" / "Network" / "Cookies",
    ]
    for cookie_file in cookie_paths:
        if cookie_file.exists() and cookie_file.stat().st_size > 0:
            return True
    return False
```

Checks two Chromium cookie file locations (old and new Chromium versions). The file must exist AND be non-empty.

### 6b. Cookie Persistence Mechanism

Cookies persist through two mechanisms:

1. **Chromium Persistent Context**: `launch_persistent_context(profile_dir)` makes Chromium store its entire browser state (cookies, localStorage, cache) in the profile directory. This persists across browser launches because the same directory is reused.

2. **Playwright Storage State**: `browser.storage_state(path=str(auth_json))` saves cookies and localStorage to a separate JSON file (`~/.omnicouncil/auth/{ai_id}.json`). This is a backup/export mechanism but is NOT what `_has_saved_cookies()` checks.

### 6c. Auth State Save/Load (Abstract Interface)

**File**: `backend/browser/engine.py`, lines 104-111

```python
@abstractmethod
async def save_auth_state(self, ai_id: str) -> bool:
    """Save current auth state (cookies, localStorage) for persistence."""

@abstractmethod
async def load_auth_state(self, ai_id: str) -> bool:
    """Load saved auth state."""
```

In `EmbeddedEngine`, these are no-ops (lines 354-358) because the persistent context handles everything automatically:

```python
async def save_auth_state(self, ai_id: str) -> bool:
    return True

async def load_auth_state(self, ai_id: str) -> bool:
    return True
```

In `CDPEngine` (lines 210-216), these are also no-ops because CDP mode uses Chrome's own cookies:

```python
async def save_auth_state(self, ai_id: str) -> bool:
    """CDP mode doesn't need to save auth state - it uses Chrome's own cookies."""
    return True
```

### 6d. Cookie File Locations

| Path | Purpose |
|------|---------|
| `~/.omnicouncil/auth/{ai_id}_profile/Default/Cookies` | Chromium cookie DB (old format) |
| `~/.omnicouncil/auth/{ai_id}_profile/Default/Network/Cookies` | Chromium cookie DB (new format) |
| `~/.omnicouncil/auth/{ai_id}.json` | Playwright storage_state export (backup) |

---

## Step 7: Session State -- How Login State is Tracked

### 7a. Backend: In-Memory State

**File**: `backend/browser/embedded_engine.py`, line 42

```python
self._authenticated: set[str] = set()
```

A simple set of AI IDs that have been authenticated. Populated in two places:

1. **On connect** (line 58-61): Scans for saved cookies
```python
for ai_id in ["deepseek", "qianwen", "gemini", "chatgpt", "claude"]:
    if self._has_saved_cookies(ai_id):
        self._authenticated.add(ai_id)
```

2. **On successful login** (line 201, 237, 249): After browser closes and cookies are verified
```python
self._authenticated.add(ai_id)
```

Queried via:
- `is_authenticated(ai_id)` (line 321-322)
- `get_authenticated_ais()` (line 324-326)
- `check_all_sessions()` (line 328-333)

### 7b. Backend: REST API Endpoints

**File**: `backend/main.py`, lines 604-612

```python
@app.get("/api/sessions/status")
async def get_sessions_status():
    sessions = browser_engine.check_all_sessions()
    authenticated = browser_engine.get_authenticated_ais()
    return {"sessions": sessions, "authenticated": authenticated}
```

Returns a dict of `{ ai_id: bool }` indicating which AIs have saved cookie files.

### 7c. Backend: WebSocket Session Check

**File**: `backend/main.py`, lines 503-522

```python
async def handle_check_sessions(websocket: WebSocket):
    sessions = browser_engine.check_all_sessions()
    authenticated = browser_engine.get_authenticated_ais()
    await ws_manager.send_personal(websocket, {
        "type": "sessions_status",
        "data": {"sessions": sessions, "authenticated": authenticated}
    })
```

Triggered by WebSocket message type `"check_sessions"`.

### 7d. Frontend: Zustand Store

**File**: `src/stores/appStore.ts`, lines 22, 64, 207-218

```typescript
// State
authStatus: Record<string, { status: string; message: string }>;

// Initial
authStatus: {},

// Handler for auth_status messages
case 'auth_status':
  set((state) => ({
    authStatus: {
      ...state.authStatus,
      [data.ai_id as string]: {
        status: data.status as string,
        message: data.message as string,
      },
    },
  }));
```

The `authStatus` map tracks per-AI status with values: `"connecting"`, `"authenticated"`, `"failed"`.

### 7e. Frontend: Config Persistence

**File**: `src/stores/configStore.ts`, lines 71-105

On startup, `loadConfig()` reads the Tauri config file AND queries the backend sessions API:

```typescript
const sessionRes = await fetch('http://localhost:8765/api/sessions/status');
const sessionData = await sessionRes.json();
sessions = sessionData.sessions || {};

// Merge: config says authenticated OR backend has cookies
status: ai.status === 'authenticated' ? 'authenticated' : (sessions[ai.aiId] ? 'authenticated' : 'disconnected'),
```

Config is persisted via Tauri's `write_config` invoke to the filesystem.

---

## Complete Flow Diagram

```
User clicks "Connect" button
        |
        v
Frontend: send('reauth', { ai_id: 'deepseek' })
        |
        v
WebSocket: { type: 'reauth', data: { ai_id: 'deepseek' } }
        |
        v
backend/main.py: handle_reauth()
  - Looks up provider from ProviderRegistry
  - Gets login_url from provider.config()
  - Broadcasts auth_status: { status: 'connecting' }
  - Spawns asyncio.create_task(_do_login(...))
        |
        v
backend/main.py: _do_login()
  - Calls browser_engine.login(ai_id, login_url)
        |
        v
backend/browser/embedded_engine.py: login()
  - Gets profile_dir via _get_profile_dir(ai_id)
  - Closes existing context for this AI
  - Launches VISIBLE Chromium with persistent context
  - Navigates to login_url
  - Checks if already logged in (_quick_login_check)
    - If yes: save storage_state, return True
    - If no: wait for user to close browser (5 min timeout)
  - After browser closes:
    - Save storage_state to {ai_id}.json
    - Check _has_saved_cookies()
    - If cookies found: add to _authenticated set, return True
    - If no cookies: return False
        |
        v
backend/main.py: _do_login() broadcasts result
  - success: auth_status { status: 'authenticated' }
  - failure: auth_status { status: 'failed', message: '...' }
        |
        v
WebSocket: auth_status message to frontend
        |
        v
Frontend: appStore.handleMessage()
  - Updates authStatus[ai_id] = { status, message }
        |
        v
UI re-renders:
  - SetupWizard shows "已连接" checkmark
  - AIPlatformManager shows "已连接" status
```

---

## Runtime Login Detection (Auto-Reauth)

When a query is sent and the AI page has expired cookies:

```
BrowserAIAdapter.send_prompt()
  -> _send_async()
    -> engine.check_auth(ai_id)
      -> Returns NOT_LOGGED_IN or EXPIRED
    -> Raises AILoginRequiredError
  -> Catches AILoginRequiredError
    -> Sets status = LOGIN_REQUIRED
    -> Calls engine.ensure_logged_in(ai_id)
      -> For EmbeddedEngine: just checks is_authenticated() (returns False)
    -> Returns AIResponse with error_code="LOGIN_REQUIRED"
```

The frontend receives the `ai_failed` WebSocket message and shows a retry button that triggers `reauth`.

---

## Key Files Reference

| File | Role |
|------|------|
| `src/components/SetupWizard.tsx` | First-launch login UI |
| `src/components/AIPlatformManager.tsx` | Login UI (setup + settings) |
| `src/components/ResponsesTab.tsx` | Retry button on login failure |
| `src/hooks/useWebSocket.ts` | WebSocket transport |
| `src/stores/appStore.ts` | Frontend auth state (Zustand) |
| `src/stores/configStore.ts` | Config persistence + session check |
| `src/App.tsx` | Routes to AIPlatformManager on first launch |
| `backend/main.py` | WebSocket handler, REST endpoints, `_do_login` |
| `backend/browser/engine.py` | Abstract BrowserEngine interface |
| `backend/browser/embedded_engine.py` | Login implementation, cookie management |
| `backend/browser/cdp_engine.py` | CDP mode (uses Chrome's own cookies) |
| `backend/browser/factory.py` | Engine factory |
| `backend/providers/base/provider.py` | BaseProvider with check_login |
| `backend/providers/registry/registry.py` | Provider auto-discovery |
| `backend/providers/deepseek/provider.py` | DeepSeek login detection |
| `backend/providers/qianwen/provider.py` | Qianwen login detection |
| `backend/providers/chatgpt/provider.py` | ChatGPT login detection |
| `backend/providers/claude/provider.py` | Claude login detection |
| `backend/providers/gemini/provider.py` | Gemini login detection |
| `backend/adapters/base.py` | Legacy AIAdapter with check_login |
| `backend/adapters/deepseek.py` | Legacy DeepSeek adapter |
| `backend/adapters/qianwen.py` | Legacy Qianwen adapter |
| `backend/engine/layers/layer1_ai_access/browser_adapter.py` | BrowserAIAdapter with login retry |
| `backend/shared/errors.py` | AILoginRequiredError definition |
| `backend/tests/test_login_flow.py` | Login flow integration tests |
| `backend/tests/test_profile_sharing.py` | Profile sharing invariant tests |
