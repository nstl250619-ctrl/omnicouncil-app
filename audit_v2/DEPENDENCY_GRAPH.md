# 依赖关系图

## 1. Layer1 ~ Layer4 依赖关系

```
Layer 2 (Scheduler)
  │
  ├─→ Layer 1 (AIAccessManager)         [直接调用 send_to_ai()]
  │     ├─→ BrowserAIAdapter             [直接调用 send_prompt()]
  │     │     └─→ BrowserEngine          [直接调用 get_page(), check_auth()]
  │     ├─→ CircuitBreaker               [直接调用 should_allow(), record_*]
  │     ├─→ RateLimiter                  [直接调用 allow(), record()]
  │     └─→ EventBus                     [emit "ai:task:completed/failed"]
  │
  └─→ EventBus                           [emit "scheduler:task:created/dispatched"]

Layer 3 (Collector)
  │
  ├─→ EventBus                           [监听 "ai:task:completed/failed/dispatched"]
  ├─→ ResponseNormalizer                  [直接调用 normalize()]
  └─→ EventBus                           [emit "collector:context:ready"]

Layer 4 (Comparison)
  │
  └─→ 无直接依赖 — 通过 events.py 间接触发
       events.py:
         ├─→ Collector.get_round_context()  [获取 RoundContext]
         ├─→ ComparisonEngine.analyze()     [执行分析]
         └─→ WebSocketManager.broadcast()   [发送结果]
```

### 层间通信方式

| 连接 | 方式 | 说明 |
|------|------|------|
| Layer 2 → Layer 1 | **直接方法调用** | `ai_manager.send_to_ai()` |
| Layer 2 → Layer 3 | **EventBus 事件** | `scheduler:task:dispatched` |
| Layer 1 → Layer 3 | **EventBus 事件** | `ai:task:completed/failed` |
| Layer 3 → Layer 4 | **直接方法调用** (通过 events.py) | `comparison_engine.analyze(ctx)` |
| Layer 4 → UI | **WebSocket 广播** | `comparison_ready` |

### 问题：层间边界不一致

- Layer 2→1: 直接调用（紧耦合）
- Layer 2→3: 事件（松耦合）
- Layer 3→4: 事件触发后直接调用（混合）
- Layer 4→UI: WebSocket（松耦合）

**没有统一的通信模式**。

## 2. Browser 依赖关系

```
main.py
  └─→ factory.create_engine("embedded")
        └─→ EmbeddedEngine
              ├─→ patchright (Playwright fork)
              ├─→ ~/.omnicouncil/auth/ (profile 目录)
              └─→ BrowserAIAdapter
                    ├─→ get_page() → EmbeddedEngine
                    ├─→ check_auth() → EmbeddedEngine
                    └─→ _send_async() → page 操作

CDPEngine (未使用)
  └─→ patchright
  └─→ Chrome CDP (localhost:9222)
```

### Browser → Provider 关系

```
EmbeddedEngine 不依赖任何 Provider
  └─ login() 方法硬编码了 AI ID 列表: ["deepseek", "qianwen", "gemini", "chatgpt", "claude"]
  └─ _has_saved_cookies() 硬编码了 cookie 路径检查
  └─ _quick_login_check() 硬编码了 deepseek/qianwen 的登录检测
  └─ check_auth() 硬编码了 deepseek/qianwen 的 URL 检查

BrowserAIAdapter 不依赖任何 Provider
  └─ 通过 config dict 配置（从 JSON 文件加载）
  └─ _is_ui_element() 硬编码了 DeepSeek 的 UI 元素
```

**问题**: Browser 层应该只提供通用能力，但实际包含了 AI 特定的逻辑。

## 3. Provider 依赖关系

```
ProviderRegistry
  ├─→ DeepSeekProvider (providers/deepseek/)
  ├─→ QianwenProvider  (providers/qianwen/)
  ├─→ GeminiProvider   (providers/gemini/)
  ├─→ ChatGPTProvider  (providers/chatgpt/)
  └─→ ClaudeProvider   (providers/claude/)

所有 Provider:
  └─→ BaseProvider (providers/base/provider.py)

ProviderRegistry 被以下使用:
  ├─→ main.py (lifespan 中创建)
  ├─→ AppState.provider_registry
  ├─→ ws/connection.py: handle_get_ais() → get_configs()
  └─→ ws/connection.py: handle_reauth() → get(ai_id).config()
```

### Provider 与 Adapter 的关系

```
Provider 和 Adapter 是完全独立的两套系统:

Provider 系统:
  BaseProvider → DeepSeekProvider / QianwenProvider / ...
  被 ProviderRegistry 管理
  只提供: config(), check_login(), send_message()
  实际只用: config() (UI 信息)

Adapter 系统:
  AIAdapter → BrowserAIAdapter → DeepSeekBrowserAdapter / QianwenBrowserAdapter
  被 AIAccessManager → ProviderManager 管理
  提供: send_prompt(), initialize(), destroy()
  实际使用: 全部

两套系统没有代码级别的连接。
Provider.config().provider_id 与 Adapter.ai_id 通过字符串 "deepseek" 关联。
```

## 4. Storage 依赖关系

```
LocalStorage (backend/storage/local.py)
  ├─→ ~/.omnicouncil/sessions/ (JSON 文件)
  ├─→ 被 main.py lifespan 创建 → AppState.storage
  ├─→ 被 api/routes.py 使用 (CRUD sessions)
  └─→ 被 api/events.py: on_all_completed() 使用 (保存会话)

SessionStorage (backend/engine/session/storage.py)
  ├─→ ~/.omnicouncil/auth/ (JSON 文件 + profile 目录)
  ├─→ 被 SessionManager 使用
  └─→ SessionManager 未被任何代码使用

EmbeddedEngine
  ├─→ ~/.omnicouncil/auth/{ai_id}_profile/ (Chromium profile)
  └─→ ~/.omnicouncil/auth/{ai_id}.json (storage state)
```

**问题**: 三套存储机制，职责重叠：
- `LocalStorage`: 会话历史（JSON 文件）
- `SessionStorage`: 登录状态（JSON 文件 + profile 目录）
- `EmbeddedEngine`: 登录状态（Chromium profile 目录）

## 5. WebSocket 依赖关系

```
ws/connection.py
  ├─→ ConnectionManager (单例 ws_manager)
  │     ├─→ active_connections: list[WebSocket]
  │     ├─→ broadcast() — 发送给所有客户端
  │     └─→ send_personal() — 发送给单个客户端
  │
  ├─→ websocket_endpoint() — FastAPI WebSocket 端点
  │     ├─→ handle_submit_query() → Scheduler.submit_query()
  │     ├─→ handle_cancel_task() → Scheduler.cancel_task()
  │     ├─→ handle_get_status() → AIAccessManager.get_ready_ais()
  │     ├─→ handle_get_ais() → ProviderRegistry.get_configs()
  │     ├─→ handle_check_sessions() → BrowserEngine.check_all_sessions()
  │     ├─→ handle_reauth() → BrowserEngine.login()
  │     └─→ handle ping/pong
  │
  └─→ GlobalExceptionHandler
        └─→ sys.excepthook → broadcast error

api/events.py
  ├─→ register_events(ws_manager)
  │     └─→ 注册 EventBus 事件处理器
  ├─→ on_ai_completed() → ws_manager.broadcast()
  ├─→ on_ai_failed() → ws_manager.broadcast()
  ├─→ on_context_ready() → ws_manager.broadcast() + run_comparison()
  └─→ on_progress() → ws_manager.broadcast()
```

### WebSocket 消息类型 (Backend → Frontend)

| 消息类型 | 来源 | 触发条件 |
|----------|------|----------|
| `engine_status` | websocket_endpoint | 客户端连接时 |
| `progress` | events.py: on_progress | Collector 进度更新 |
| `ai_completed` | events.py: on_ai_completed | 单个 AI 完成 |
| `ai_failed` | events.py: on_ai_failed | 单个 AI 失败 |
| `all_completed` | events.py: on_context_ready | 所有 AI 完成 |
| `comparison_ready` | events.py: run_comparison | 对比分析完成 |
| `task_created` | handle_submit_query | 任务创建成功 |
| `task_cancelled` | handle_cancel_task | 任务取消 |
| `auth_status` | _do_login | 登录状态更新 |
| `error` | 多处 | 错误发生 |
| `status` | handle_get_status | 状态查询响应 |
| `ai_list` | handle_get_ais | AI 列表响应 |
| `sessions_status` | handle_check_sessions | 会话状态响应 |
| `pong` | websocket_endpoint | 心跳响应 |

### WebSocket 消息类型 (Frontend → Backend)

| 消息类型 | 处理器 |
|----------|--------|
| `submit_query` | handle_submit_query |
| `cancel_task` | handle_cancel_task |
| `get_status` | handle_get_status |
| `get_ais` | handle_get_ais |
| `check_sessions` | handle_check_sessions |
| `reauth` | handle_reauth |
| `ping` | pong 响应 |

## 6. 循环依赖分析

### 不存在严格循环依赖

通过 `TYPE_CHECKING` 守卫和运行时导入，项目避免了 Python 层面的循环导入。

### 存在隐式循环

```
EventBus ←→ 所有层
  所有层都依赖 EventBus（通过 AppState.event_bus）
  EventBus 不依赖任何层
  → 无循环

AppState ←→ 所有模块
  所有模块通过 AppState.instance() 访问其他模块
  AppState 通过 TYPE_CHECKING 导入类型
  → 无运行时循环，但有隐式耦合

api/events.py ←→ ws/connection.py
  events.py 需要 ws_manager（通过 register_events 参数传入）
  ws/connection.py 不依赖 events.py
  → 无循环

main.py ←→ 所有模块
  main.py 导入并初始化所有模块
  其他模块不导入 main.py
  → 无循环
```

### 潜在问题：AppState 作为全局服务定位器

```python
# 任何模块都可以这样做:
state = AppState.instance()
state.ai_manager.send_to_ai(...)
state.scheduler.submit_query(...)
state.browser_engine.get_page(...)
```

这实际上是一个**服务定位器模式**，虽然避免了循环依赖，但：
- 所有模块隐式依赖 AppState
- 无法独立测试单个模块
- 依赖关系不透明
