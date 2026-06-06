# Provider Audit — omnicouncil-app/backend

## Summary

The backend contains **three parallel provider/adapter systems** that evolved independently. This is the single biggest architectural finding: the same 5 AIs (DeepSeek, Qianwen, Gemini, ChatGPT, Claude) are implemented three times with different base classes and slightly different interfaces.

---

## System 1: `providers/` — BaseProvider + ProviderRegistry (Primary)

**Purpose:** Page-based Playwright provider. Each provider receives a Playwright `page` object and drives the AI website directly.

### Base Class

| Item | Detail |
|---|---|
| File | `backend/providers/base/provider.py` |
| Class | `BaseProvider(ABC)` |
| Config | `ProviderConfig` dataclass (provider_id, display_name, login_url, chat_url, enabled, icon_color, icon_emoji, max_concurrent, timeout_ms, extra) |
| Abstract methods | `config()`, `check_login(page)`, `send_message(page, message)` |
| Optional hooks | `on_login_start(page)`, `on_login_success(page)`, `on_session_expired(page)` |
| Selector helpers | `get_input_selector()` -> str, `get_submit_selector()` -> str|None |
| Complete | Yes -- all abstract methods defined, hooks with defaults |

### Registry

| Item | Detail |
|---|---|
| File | `backend/providers/registry/registry.py` |
| Class | `ProviderRegistry` |
| Methods | `register`, `unregister`, `get`, `get_all`, `get_enabled`, `get_configs`, `toggle` |
| Auto-discovery | `auto_discover_providers()` scans `providers/` subdirectories for `provider.py` files containing `BaseProvider` subclasses |
| Factory | `create_default_registry()` creates a registry pre-loaded with all discovered providers |
| Call chain | `main.py:lifespan()` -> `create_default_registry()` -> `auto_discover_providers()` -> `ProviderRegistry.register()` |

### Concrete Providers

#### 1. DeepSeekProvider

| Item | Detail |
|---|---|
| File | `backend/providers/deepseek/provider.py` |
| Class | `DeepSeekProvider(BaseProvider)` |
| Methods implemented | `config()`, `check_login(page)`, `send_message(page, message)` |
| Complete | Yes |
| Tests | **None found** |
| Notes | Uses textarea selector; filters UI elements (DeepThink, Search) from response; 3s idle detection |

#### 2. QianwenProvider

| Item | Detail |
|---|---|
| File | `backend/providers/qianwen/provider.py` |
| Class | `QianwenProvider(BaseProvider)` |
| Methods implemented | `config()`, `check_login(page)`, `send_message(page, message)` |
| Complete | Yes |
| Tests | **None found** |
| Notes | Checks for CJK login indicators; tries textarea then contenteditable then role=textbox |

#### 3. GeminiProvider

| Item | Detail |
|---|---|
| File | `backend/providers/gemini/provider.py` |
| Class | `GeminiProvider(BaseProvider)` |
| Methods implemented | `config()`, `check_login(page)`, `send_message(page, message)` |
| Complete | Yes |
| Tests | **None found** |
| Notes | Google account login detection via URL; tries contenteditable then textarea |

#### 4. ChatGPTProvider

| Item | Detail |
|---|---|
| File | `backend/providers/chatgpt/provider.py` |
| Class | `ChatGPTProvider(BaseProvider)` |
| Methods implemented | `config()`, `check_login(page)`, `send_message(page, message)` |
| Complete | Yes |
| Tests | **None found** |
| Notes | Uses `#prompt-textarea` selector; tries send button then Enter; 5s idle detection (longer than others); anti-bot warning in docstring |

#### 5. ClaudeProvider

| Item | Detail |
|---|---|
| File | `backend/providers/claude/provider.py` |
| Class | `ClaudeProvider(BaseProvider)` |
| Methods implemented | `config()`, `check_login(page)`, `send_message(page, message)` |
| Complete | Yes |
| Tests | **None found** |
| Notes | Tries contenteditable then textarea; 3s idle detection |

---

## System 2: `adapters/` — AIAdapter (Legacy/Duplicate)

**Purpose:** Nearly identical to System 1 but with a slightly different interface (`AIAdapter` instead of `BaseProvider`, `AIConfig` instead of `ProviderConfig`).

### Base Class

| Item | Detail |
|---|---|
| File | `backend/adapters/base.py` |
| Class | `AIAdapter(ABC)` |
| Config | `AIConfig` dataclass (ai_id, display_name, login_url, chat_url, enabled, icon_color, extra) |
| Abstract methods | `config()`, `check_login(page)`, `send_message(page, message)` |
| Extra method | `get_response_selector()` -> str|None (not in BaseProvider) |
| Complete | Yes |

### Concrete Adapters

| File | Class | Methods |
|---|---|---|
| `backend/adapters/deepseek.py` | `DeepSeekAdapter(AIAdapter)` | config, check_login, send_message, get_input_selector |
| `backend/adapters/qianwen.py` | `QianwenAdapter(AIAdapter)` | config, check_login, send_message, get_input_selector |

**Only 2 of 5 providers implemented.** Gemini, ChatGPT, Claude are missing from this system.

### Registry

| Item | Detail |
|---|---|
| File | `backend/adapters/registry.py` |
| Factory | `create_default_registry()` (parallel to System 1's registry) |
| Tests | **None found** |

---

## System 3: `engine/layers/layer1_ai_access/` — AIAdapter (Engine)

**Purpose:** Browser-engine-based adapter. Each adapter uses a `BrowserEngine` or self-managed Playwright browser. Returns structured `AIResponse` objects instead of raw strings.

### Base Classes

#### AIAdapter (Abstract)

| Item | Detail |
|---|---|
| File | `backend/engine/layers/layer1_ai_access/adapter.py` |
| Class | `AIAdapter(ABC)` |
| Abstract properties | `ai_id`, `ai_name`, `url` |
| Abstract methods | `initialize()`, `destroy()`, `get_status()`, `send_prompt(prompt, options)`, `stop_generation()`, `new_conversation()` |
| Concrete | `is_ready()` |
| Complete | Yes |

#### BrowserAIAdapter (Intermediate)

| Item | Detail |
|---|---|
| File | `backend/engine/layers/layer1_ai_access/browser_adapter.py` |
| Class | `BrowserAIAdapter(AIAdapter)` |
| Purpose | Base for adapters that delegate to `BrowserEngine` |
| Implements | `ai_id`, `ai_name`, `url` (from config dict), `get_status()`, `initialize()`, `destroy()`, `send_prompt()` |
| Template methods | `_find_input(page)` (override point), `_extract_response(page, prompt, timeout_ms)` (override point) |
| Complete | Yes |

### Concrete Adapters

#### 1. DeepSeekAdapter

| Item | Detail |
|---|---|
| File | `backend/engine/layers/layer1_ai_access/adapters/deepseek.py` |
| Class | `DeepSeekAdapter(AIAdapter)` |
| Methods | All 14 AIAdapter methods implemented (init, ai_id, ai_name, url, _load_config, get_status, initialize, _prewarm_browser, destroy, send_prompt, _count_words, _send_async, stop_generation, new_conversation) |
| Complete | Yes |
| Tests | **None found** |

#### 2. QianwenAdapter

| Item | Detail |
|---|---|
| File | `backend/engine/layers/layer1_ai_access/adapters/qianwen.py` |
| Class | `QianwenAdapter(AIAdapter)` |
| Methods | All required methods implemented |
| Complete | Yes |
| Tests | **None found** |

#### 3. GeminiAdapter

| Item | Detail |
|---|---|
| File | `backend/engine/layers/layer1_ai_access/adapters/gemini.py` |
| Class | `GeminiAdapter(AIAdapter)` |
| Methods | All required methods implemented |
| Complete | Yes |
| Tests | **None found** |
| Notes | Uses Scrapling StealthyFetcher instead of Playwright |

#### 4. MockDeepSeekAdapter

| Item | Detail |
|---|---|
| File | `backend/tests/integration/test_pipeline.py:30` |
| Class | `MockDeepSeekAdapter(AIAdapter)` |
| Purpose | Test double for integration tests |
| Tests | Used in integration test pipeline |

### Manager and Registry

#### ProviderManager

| Item | Detail |
|---|---|
| File | `backend/engine/layers/layer1_ai_access/managers/provider_manager.py` |
| Class | `ProviderManager` |
| Methods | `register(adapter)`, `get(ai_id)`, `get_all()`, `get_all_status()`, `get_status(ai_id)`, `registered_ids` property |
| Pattern | Simple dict-based registry, keyed by `adapter.ai_id` |

#### AIAccessManager

| Item | Detail |
|---|---|
| File | `backend/engine/layers/layer1_ai_access/manager.py` |
| Class | `AIAccessManager` |
| Composition | Owns `ProviderManager` + `RateLimiter` + `CircuitBreaker` per adapter |
| Methods | `register_adapter()`, `initialize()`, `destroy()`, `get_ready_ais()`, `get_provider_status()`, `send_to_ai()`, `send_to_multiple()`, `stop_generation()` |
| Call chain | `register_adapter()` -> `ProviderManager.register()` + creates CircuitBreaker |
| Callers | **None found in codegraph** -- likely instantiated at app startup outside indexed scope |

---

## Provider Registry / Factory Pattern

### System 1: ProviderRegistry (providers/)

- **Pattern:** Auto-discovery factory
- `auto_discover_providers()` scans `providers/` subdirectories
- `create_default_registry()` builds a pre-loaded `ProviderRegistry`
- **Caller:** `main.py:lifespan()` at line 250
- Mutation concern: `toggle()` method mutates `ProviderConfig.enabled` in-place (violates immutability principle)

### System 2: create_default_registry (adapters/)

- **Pattern:** Same auto-discovery factory as System 1
- Duplicate of System 1's registry logic
- **Caller:** Not found -- appears unused or called from outside indexed scope

### System 3: ProviderManager (engine/)

- **Pattern:** Manual registration (no auto-discovery)
- Adapters are registered via `AIAccessManager.register_adapter()`
- **Caller:** Not found in codegraph -- likely called from main.py or a startup script

---

## Call Chain Summary

```
main.py:lifespan()
  -> create_default_registry()           [System 1]
       -> auto_discover_providers()
            -> importlib.import_module("providers.{name}.provider")
                 -> DeepSeekProvider / QianwenProvider / GeminiProvider / ChatGPTProvider / ClaudeProvider
                      -> ProviderRegistry.register(provider)

AIAccessManager.__init__()               [System 3]
  -> ProviderManager()
  -> RateLimiter()
  -> CircuitBreaker per adapter

AIAccessManager.register_adapter(adapter)
  -> ProviderManager.register(adapter)
  -> CircuitBreaker(ai_id)

Layer 2 (Scheduler)
  -> AIAccessManager.send_to_ai(ai_id, prompt)
       -> CircuitBreaker.should_allow()
       -> RateLimiter.allow()
       -> AIAdapter.send_prompt(prompt, options)
       -> EventBus.emit("ai:task:completed"|"ai:task:failed")
```

---

## Issues Found

### 1. THREE PARALLEL PROVIDER SYSTEMS (CRITICAL)

The same 5 AIs are implemented across three separate systems with different base classes:

| System | Base Class | Providers | Status |
|---|---|---|---|
| `providers/` | `BaseProvider` | 5/5 (DeepSeek, Qianwen, Gemini, ChatGPT, Claude) | Primary, auto-discovered |
| `adapters/` | `AIAdapter` | 2/5 (DeepSeek, Qianwen) | Incomplete, appears unused |
| `engine/` | `AIAdapter` + `BrowserAIAdapter` | 3/5 (DeepSeek, Qianwen, Gemini) | Used by AIAccessManager |

**Recommendation:** Consolidate to one system. The `engine/` system is the most complete with structured responses, circuit breakers, and rate limiting. The `providers/` system has auto-discovery. The `adapters/` system appears abandoned.

### 2. NO TESTS FOR ANY PROVIDER (HIGH)

Zero unit or integration tests exist for any of the 15 provider/adapter implementations. The only test-related code is `MockDeepSeekAdapter` in integration tests.

### 3. MUTATION IN REGISTRY TOGGLE (MEDIUM)

`ProviderRegistry.toggle()` calls `provider.config().enabled = enabled` which mutates the `ProviderConfig` dataclass in-place. Per project immutability rules, this should create a new config.

### 4. IDENTICAL RESPONSE EXTRACTION LOGIC (MEDIUM)

All providers in System 1 use nearly identical body-text-parsing logic (find prompt in page lines, extract lines after it, idle detection). This should be extracted to a shared utility.

### 5. DEAD CODE IN `adapters/` (LOW)

System 2 (`backend/adapters/`) has only 2 of 5 providers and a separate registry. It appears to be an abandoned intermediate attempt. Should be removed.

### 6. AIAccessManager HAS NO CALLERS (MEDIUM)

`AIAccessManager` (System 3) has no callers found in the code graph. It may be instantiated dynamically or the wiring may be incomplete.

---

## File Inventory

| File | System | Role |
|---|---|---|
| `backend/providers/base/provider.py` | 1 | Base class + config |
| `backend/providers/registry/registry.py` | 1 | Registry + auto-discovery |
| `backend/providers/deepseek/provider.py` | 1 | DeepSeek |
| `backend/providers/qianwen/provider.py` | 1 | Qianwen |
| `backend/providers/gemini/provider.py` | 1 | Gemini |
| `backend/providers/chatgpt/provider.py` | 1 | ChatGPT |
| `backend/providers/claude/provider.py` | 1 | Claude |
| `backend/adapters/base.py` | 2 | Base class + config |
| `backend/adapters/registry.py` | 2 | Registry |
| `backend/adapters/deepseek.py` | 2 | DeepSeek |
| `backend/adapters/qianwen.py` | 2 | Qianwen |
| `backend/engine/layers/layer1_ai_access/adapter.py` | 3 | Base class |
| `backend/engine/layers/layer1_ai_access/browser_adapter.py` | 3 | BrowserEngine base |
| `backend/engine/layers/layer1_ai_access/managers/provider_manager.py` | 3 | Registry |
| `backend/engine/layers/layer1_ai_access/manager.py` | 3 | AIAccessManager |
| `backend/engine/layers/layer1_ai_access/adapters/deepseek.py` | 3 | DeepSeek |
| `backend/engine/layers/layer1_ai_access/adapters/qianwen.py` | 3 | Qianwen |
| `backend/engine/layers/layer1_ai_access/adapters/gemini.py` | 3 | Gemini |
| `backend/tests/integration/test_pipeline.py` | 3 | MockDeepSeekAdapter |
