# 死代码报告

## 1. 未引用文件

### 后端 — 完全未被导入的文件

| 文件 | 行数 | 说明 |
|------|------|------|
| `engine/conflict/engine.py` | 103 | ConflictEngine — 无任何 import |
| `engine/conflict/result.py` | 47 | ConflictPoint, ConflictResult — 仅被 conflict/engine.py 导入 |
| `engine/consensus/engine.py` | 116 | ConsensusEngine — 无任何 import |
| `engine/consensus/result.py` | 30 | ConsensusReport — 仅被 consensus/engine.py 和 judge/engine.py 导入 |
| `engine/judge/engine.py` | 138 | JudgeEngine — 无任何 import |
| `engine/judge/result.py` | 28 | JudgeVerdict — 仅被 judge/engine.py 导入 |
| `engine/session/manager.py` | 48 | SessionManager — 无任何 import |
| `engine/session/storage.py` | 77 | SessionStorage — 仅被 session/manager.py 导入 |
| `browser/cdp_engine.py` | 212 | CDPEngine — 被 factory.py 导入，但 factory 中的 "cdp" 分支从未执行 |
| `engine/layers/layer4_comparison/comparison_config.py` | 5 | 多余的重导出 |

### 前端 — 未被引用的组件

| 文件 | 行数 | 说明 |
|------|------|------|
| `src/components/Header.tsx` | 19 | 未被 App.tsx 或任何组件 import |
| `src/components/SetupWizard.tsx` | 238 | 未被 App.tsx import（AIPlatformManager 替代了它） |
| `src/components/SkeletonLoader.tsx` | 20 | 未被任何组件 import |

## 2. 未实例化类

| 类 | 文件 | 说明 |
|----|------|------|
| `ConflictEngine` | `engine/conflict/engine.py` | 从未被实例化 |
| `ConsensusEngine` | `engine/consensus/engine.py` | 从未被实例化 |
| `JudgeEngine` | `engine/judge/engine.py` | 从未被实例化 |
| `SessionManager` | `engine/session/manager.py` | 从未被实例化 |
| `SessionStorage` | `engine/session/storage.py` | 从未被实例化 |
| `CDPEngine` | `browser/cdp_engine.py` | 被 factory 导入但 `mode="cdp"` 从未被传入 |
| `DeepSeekProvider` | `providers/deepseek/provider.py` | 被自动发现并注册，但 `send_message()`/`check_login()` 从未被调用 |
| `QianwenProvider` | `providers/qianwen/provider.py` | 同上 |
| `GeminiProvider` | `providers/gemini/provider.py` | 同上 |
| `ChatGPTProvider` | `providers/chatgpt/provider.py` | 同上 |
| `ClaudeProvider` | `providers/claude/provider.py` | 同上 |

## 3. 未调用方法

### BrowserEngine 接口方法

| 方法 | 文件 | 说明 |
|------|------|------|
| `ensure_logged_in()` | `browser/embedded_engine.py:348` | EmbeddedEngine 实现返回 `is_authenticated()`，但从未被直接调用 |
| `save_auth_state()` | `browser/embedded_engine.py:342` | 返回 True 的空实现 |
| `load_auth_state()` | `browser/embedded_engine.py:345` | 返回 True 的空实现 |
| `get_status()` | `browser/embedded_engine.py:323` | 未被调用 |

### AIAccessManager 方法

| 方法 | 文件 | 说明 |
|------|------|------|
| `stop_generation()` | `engine/layers/layer1_ai_access/manager.py:192` | 未被 Scheduler 调用 |
| `get_provider_status()` | `engine/layers/layer1_ai_access/manager.py:77` | 未被调用 |

### ResultCollector 方法

| 方法 | 文件 | 说明 |
|------|------|------|
| `get_round_context()` | `engine/layers/layer3_collector/result_collector.py:143` | 仅被 events.py 的 `on_all_completed` 和 `run_comparison` 调用 |
| `get_latest_round_context()` | `engine/layers/layer3_collector/result_collector.py:147` | 未被调用（与 `get_round_context` 完全相同） |
| `get_partial_results()` | `engine/layers/layer3_collector/result_collector.py:151` | 未被调用 |
| `on_context_ready()` | `engine/layers/layer3_collector/result_collector.py:156` | 未被调用 |

### SchedulerCenter 方法

| 方法 | 文件 | 说明 |
|------|------|------|
| `cleanup_old_tasks()` | `engine/layers/layer2_scheduler/scheduler_center.py:277` | 未被调用 — 任务字典无限增长 |

### EventBus 方法

| 方法 | 文件 | 说明 |
|------|------|------|
| `emit_sync()` | `shared/event_bus.py:79` | 未被调用 |
| `off()` | `shared/event_bus.py:51` | 未被调用 |

### ProviderRegistry 方法

| 方法 | 文件 | 说明 |
|------|------|------|
| `unregister()` | `providers/registry/registry.py:30` | 未被调用 |
| `get_enabled()` | `providers/registry/registry.py:41` | 未被调用 |
| `toggle()` | `providers/registry/registry.py:56` | 未被调用 |

### BaseProvider 方法

| 方法 | 文件 | 说明 |
|------|------|------|
| `on_login_start()` | `providers/base/provider.py:64` | 空实现，未被调用 |
| `on_login_success()` | `providers/base/provider.py:68` | 空实现，未被调用 |
| `on_session_expired()` | `providers/base/provider.py:72` | 返回 False，未被调用 |
| `get_input_selector()` | `providers/base/provider.py:76` | 未被调用 |
| `get_submit_selector()` | `providers/base/provider.py:81` | 未被调用 |

## 4. 重复实现

### 4.1 Provider vs Adapter 双重架构

**最严重的重复**。同一个 DeepSeek 有两套独立实现：

| 维度 | Provider (`providers/deepseek/provider.py`) | Adapter (`adapters/deepseek_browser.py` + `browser_adapter.py`) |
|------|---------------------------------------------|---------------------------------------------------------------|
| 基类 | `BaseProvider` | `AIAdapter` → `BrowserAIAdapter` |
| 职责 | 配置 + `send_message()` + `check_login()` | 配置 + `send_prompt()` + 浏览器自动化 |
| 实际使用 | 仅 `config()` 被调用（UI 信息） | 全部方法被调用 |
| send_message 逻辑 | 独立实现（直接操作 page） | 通过 BrowserEngine 代理 |
| 响应提取 | 独立实现（body 文本解析） | 独立实现（body 文本解析） |

**结果**: DeepSeek 和千问的响应提取逻辑被实现了 3 次：
1. `providers/deepseek/provider.py:send_message()`
2. `adapters/deepseek_browser.py` (继承 BrowserAIAdapter)
3. `providers/qianwen/provider.py:send_message()`

### 4.2 响应提取逻辑重复

所有 Provider 的 `send_message()` 和所有 Adapter 的 `_extract_response()` 都使用相同的模式：
```
while time.time() < deadline:
    body = await page.locator("body").inner_text()
    lines = body.split("\n")
    # 找 prompt_idx → 提取后续行 → 空闲检测
```

这个模式在以下文件中重复出现（6 次）：
- `providers/deepseek/provider.py:33-77`
- `providers/qianwen/provider.py:35-91`
- `providers/gemini/provider.py:36-95`
- `providers/chatgpt/provider.py:36-105`
- `providers/claude/provider.py:33-90`
- `engine/layers/layer1_ai_access/browser_adapter.py:171-210`

### 4.3 登录检测逻辑重复

| 位置 | 逻辑 |
|------|------|
| `providers/deepseek/provider.py:check_login()` | 检查 URL + textarea 可见性 |
| `browser/embedded_engine.py:check_auth()` | 检查 URL |
| `browser/embedded_engine.py:_quick_login_check()` | 检查 URL + textarea 可见性 |
| `browser/cdp_engine.py:check_auth()` | 检查 URL + body 文本 |

### 4.4 UI 元素过滤重复

`_is_ui_element()` 在以下位置独立实现：
- `providers/deepseek/provider.py` — 通过 `ui_skip` set
- `providers/qianwen/provider.py` — 通过行长度过滤
- `providers/gemini/provider.py` — 通过 `skip` 列表
- `providers/chatgpt/provider.py` — 通过 `skip` 列表
- `providers/claude/provider.py` — 通过 `skip` 列表
- `adapters/deepseek_browser.py:_is_ui_element()`
- `browser_adapter.py:_is_ui_element()`

### 4.5 AppState vs SessionManager 状态管理重复

- `AppState` 管理 `browser_engine` 和登录状态（通过 `EmbeddedEngine._authenticated`）
- `SessionManager` 也管理登录状态（通过 `_authenticated` set）
- 两者完全独立，`SessionManager` 从未被使用

### 4.6 配置路径重复

- `LocalStorage` 默认路径: `~/.omnicouncil/sessions/`
- `SessionStorage` 默认路径: `~/.omnicouncil/auth/`
- `EmbeddedEngine` 默认路径: `~/.omnicouncil/auth/`
- `main.py` 中 `load_config()` 路径: `backend/config/default.yaml`

## 5. 废弃架构残留

### 5.1 旧版 Engine 层残留

`engine/conflict/`, `engine/consensus/`, `engine/judge/` 是旧版架构的残留。它们：
- 依赖不存在的类型（`AIResponse` from `..collector.response`, `ComparisonResult` from `..comparison.result`）
- 这些导入路径在当前代码中不存在
- 如果尝试 import 会立即报错
- 说明这些模块是从更早版本的代码遗留下来的，当时有 `collector.response` 和 `comparison.result` 模块

### 5.2 旧版 Session 管理残留

`engine/session/` 是旧版登录管理的残留。当前登录由 `EmbeddedEngine` 直接管理（`login()`, `_has_saved_cookies()`, `_authenticated` set）。

### 5.3 Frontend Tab 定义残留

`appStore.ts` 中 `TabId` 类型定义了 `'review' | 'debate'` 两个 Tab，但：
- 没有对应的组件
- `TabBar.tsx` 中没有渲染这两个 Tab
- 说明这些是已规划但未实现的功能

### 5.4 Tauri Python Manager 残留

`src-tauri/src/python_manager.rs` 存在，但当前架构中 Python 后端通过 uvicorn 独立启动，Tauri 仅作为前端容器。`python_manager.rs` 可能是早期设计中 Tauri 直接管理 Python 进程的残留。

### 5.5 旧版 omnicouncil 目录

`/home/greenpool/omnicouncil/` 是整个项目的旧版本，包含完全不同的目录结构（`backend/layers/` vs `backend/engine/layers/`）。这是一个独立的 git 仓库，但与 `omnicouncil-app` 是同一项目的不同版本。
