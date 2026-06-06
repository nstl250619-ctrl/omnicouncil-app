# 实际运行链路分析

## 1. main.py 启动流程

```
main.py (uvicorn)
  └─ app = FastAPI(lifespan=lifespan)
       │
       ├─ lifespan():
       │    ├─ AppState.create()                    # 创建单例
       │    ├─ EventBus()                           # 创建事件总线单例
       │    ├─ load_config()                        # 加载 YAML 配置
       │    ├─ create_default_registry()            # 自动发现 5 个 Provider
       │    ├─ create_engine("embedded", headless)   # 创建 EmbeddedEngine
       │    │    └─ EmbeddedEngine.connect()         # 启动 Playwright
       │    ├─ AIAccessManager(event_bus)
       │    │    ├─ register_adapter(DeepSeekBrowserAdapter)  # 注册适配器
       │    │    ├─ register_adapter(QianwenBrowserAdapter)   # 注册适配器
       │    │    └─ initialize()                     # 初始化所有适配器
       │    ├─ SchedulerCenter(ai_manager, event_bus)
       │    ├─ ResultCollector(event_bus)            # 监听 ai:task:completed/failed
       │    ├─ ComparisonEngine(config, event_bus)
       │    ├─ LocalStorage()
       │    ├─ register_events(ws_manager)           # 注册 Engine→WS 桥接
       │    └─ GlobalExceptionHandler.install()      # 全局异常钩子
       │
       ├─ register_routes(app)                      # HTTP 路由
       └─ app.websocket("/ws")(websocket_endpoint)   # WebSocket 端点
```

## 2. Scheduler 实际实现

**文件**: `engine/layers/layer2_scheduler/scheduler_center.py`

**职责**: 薄编排层 — 验证、可用性检查、并发/重试/超时控制、任务生命周期跟踪

**实际流程**:
```
submit_query(QueryRequest)
  ├─ 验证: query 非空, ai_ids 非空
  ├─ get_available_ais() → 检查 AIStatus.READY
  ├─ 创建 TaskStatusInfo(CREATED)
  ├─ emit("scheduler:task:created")
  ├─ 转换为 DISPATCHED
  ├─ emit("scheduler:task:dispatched")    ← 触发 Layer 3
  ├─ asyncio.create_task(_execute_task_safe)
  └─ 返回 TaskHandle

_execute_task:
  ├─ 转换为 RUNNING
  ├─ TimeoutManager.start()
  ├─ asyncio.gather(*[_send_one(ai_id)])
  │    └─ _send_one:
  │         ├─ ConcurrencyController.acquire()
  │         ├─ _send_with_retry()
  │         │    └─ while True:
  │         │         ├─ AIAccessManager.send_to_ai()
  │         │         ├─ 成功 → return
  │         │         └─ 失败 → RetryManager.should_retry()? 继续/退出
  │         └─ ConcurrencyController.release()
  ├─ TimeoutManager.finish()
  └─ 更新 TaskStatusInfo(COMPLETED/PARTIAL/FAILED)
```

**子模块**:
- `ConcurrencyController`: asyncio.Semaphore(2) + 每 AI 最小间隔
- `RetryManager`: 固定延迟重试，支持退避
- `TimeoutManager`: 软/硬超时跟踪

## 3. Collector 实际实现

**文件**: `engine/layers/layer3_collector/result_collector.py`

**职责**: 数据总线 — 监听 AI 事件，标准化响应，组装 RoundContext

**实际流程**:
```
事件驱动:
  "scheduler:task:dispatched" → _on_task_dispatched()
    └─ 初始化 _pending, _expected, _queries, _modes

  "ai:task:completed" → _on_task_completed()
    ├─ ResponseNormalizer.normalize(content)
    ├─ 创建 AiResult(SUCCESS)
    ├─ 存入 _pending[task_id][ai_id]
    └─ _check_completion()

  "ai:task:failed" → _on_task_failed()
    ├─ 创建 AiResult(ERROR)
    ├─ 存入 _pending[task_id][ai_id]
    └─ _check_completion()

  _check_completion:
    └─ if len(pending) >= expected:
         └─ _assemble_context()
              ├─ 创建 RoundContext
              ├─ emit("collector:context:ready")
              └─ 清理临时状态
```

**关键**: Collector 是被动的 — 它不主动调用任何 AI，只响应事件。

## 4. Comparison 实际实现

**文件**: `engine/layers/layer4_comparison/comparison_engine.py`

**职责**: 6 阶段分析管道

**实际流程**:
```
analyze(RoundContext) → ComparisonContext
  ├─ Stage 1: TextPreprocessor.process()
  │    └─ 提取/清洗段落，过滤短段落
  ├─ Stage 2: SemanticUnitExtractor.extract()
  │    └─ 段落 → SemanticUnit IR
  ├─ Stage 3: SimilarityAnalyzer.analyze()
  │    ├─ TfidfCalculator.fit_transform() → TF-IDF 向量
  │    ├─ cosine_similarity() → 余弦相似度
  │    ├─ lcs_ratio() → LCS 比率
  │    └─ 加权组合: tfidf_weight * cosine + lcs_weight * lcs
  ├─ Stage 4: DifferenceAnalyzer.detect()
  │    ├─ Union-Find 聚类
  │    └─ 跨 AI 差异检测
  ├─ Stage 5: UniqueInsightExtractor.extract()
  │    └─ 找出仅单个 AI 提到的观点
  └─ Stage 6: ComparisonAssembler.assemble()
       └─ 组装 ComparisonContext + 指标
```

**触发方式**: 由 `api/events.py` 的 `on_context_ready` 事件触发，通过 `asyncio.to_thread()` 在后台线程执行。

## 5. Provider 实际实现

**文件**: `providers/*/provider.py`

**双重架构问题**:

| 系统 | 文件 | 实际使用 |
|------|------|----------|
| Provider 系统 | `providers/deepseek/provider.py` | ✅ 被 ProviderRegistry 自动发现 |
| Provider 系统 | `providers/qianwen/provider.py` | ✅ 被 ProviderRegistry 自动发现 |
| Provider 系统 | `providers/gemini/provider.py` | ✅ 被 ProviderRegistry 自动发现 |
| Provider 系统 | `providers/chatgpt/provider.py` | ✅ 被 ProviderRegistry 自动发现 |
| Provider 系统 | `providers/claude/provider.py` | ✅ 被 ProviderRegistry 自动发现 |
| Adapter 系统 | `adapters/deepseek_browser.py` | ✅ 被 AIAccessManager 注册，**实际执行** |
| Adapter 系统 | `adapters/qianwen_browser.py` | ✅ 被 AIAccessManager 注册，**实际执行** |

**Provider 系统** (`BaseProvider`) 只提供配置和 UI 信息（display_name, icon_color, login_url），不参与实际 AI 调用。

**Adapter 系统** (`AIAdapter` → `BrowserAIAdapter`) 才是实际发送请求、提取响应的代码。

**Gemini/ChatGPT/Claude**: Provider 已注册，但无对应 Adapter，无法实际调用。

## 6. Browser 实际实现

**文件**: `browser/*.py`

```
factory.py: create_engine("embedded")
  └─ EmbeddedEngine(auth_dir, headless)
       ├─ connect(): 启动 Playwright Chromium
       ├─ get_page(ai_id, url): 获取/创建页面
       ├─ check_auth(ai_id): 检查登录状态
       └─ login(ai_id, url): 弹出可见浏览器，用户手动登录

CDPEngine: 连接本地 Chrome (localhost:9222)
  └─ 未被使用 — main.py 硬编码 "embedded"
```

**实际使用**: 只有 EmbeddedEngine 被使用。CDPEngine 存在但未接入。

## 7. 未参与运行的模块

### 完全未接入运行链路

| 模块 | 文件 | 原因 |
|------|------|------|
| **ConflictEngine** | `engine/conflict/engine.py` | 无任何调用方。依赖旧版 `ComparisonResult`/`AIResponse` 类型，与当前 `RoundContext`/`ComparisonContext` 不兼容 |
| **ConsensusEngine** | `engine/consensus/engine.py` | 无任何调用方。依赖旧版类型 |
| **JudgeEngine** | `engine/judge/engine.py` | 无任何调用方。`_call_api()` 返回 mock 数据 |
| **SessionManager** | `engine/session/manager.py` | 无任何调用方。登录由 EmbeddedEngine 直接管理 |
| **SessionStorage** | `engine/session/storage.py` | 无任何调用方 |
| **CDPEngine** | `browser/cdp_engine.py` | main.py 硬编码 "embedded" |
| **Gemini Provider** | `providers/gemini/provider.py` | 注册但无对应 Adapter |
| **ChatGPT Provider** | `providers/chatgpt/provider.py` | 注册但无对应 Adapter |
| **Claude Provider** | `providers/claude/provider.py` | 注证但无对应 Adapter |
| **Header.tsx** | `src/components/Header.tsx` | 未被 App.tsx 引用 |
| **SetupWizard.tsx** | `src/components/SetupWizard.tsx` | 未被 App.tsx 引用 |
| **SkeletonLoader.tsx** | `src/components/SkeletonLoader.tsx` | 未被 App.tsx 引用 |

### 部分未使用

| 模块 | 详情 |
|------|------|
| **ProviderRegistry** | 注册了 5 个 Provider，但只有 `get_configs()` 被 WS 调用（发送给前端），Provider 的 `send_message()`/`check_login()` 从未被调用 |
| **comparison_config.py** | 只是重导出 `shared.config.ComparisonConfig`，多余 |
| **gemini.json** | 配置文件存在，但无 Gemini Adapter 使用 |
| **EventBus.emit_sync()** | 定义但未被调用 |

## 8. 实际运行链路总结

```
用户输入 → WebSocket submit_query
  → handle_submit_query()
    → collector.set_query()
    → scheduler.submit_query(QueryRequest)
      → emit("scheduler:task:dispatched")
      → asyncio.create_task(_execute_task)
        → _send_with_retry()
          → AIAccessManager.send_to_ai()
            → CircuitBreaker.check
            → RateLimiter.check
            → BrowserAIAdapter.send_prompt()
              → EmbeddedEngine.get_page()
              → page.fill() + Enter
              → 等待空闲 3 秒 → 提取文本
            → emit("ai:task:completed")
              → ResultCollector._on_task_completed()
                → ResponseNormalizer.normalize()
                → _check_completion()
                  → _assemble_context()
                    → emit("collector:context:ready")
                      → on_context_ready()
                        → broadcast("all_completed")
                        → asyncio.create_task(run_comparison)
                          → ComparisonEngine.analyze()
                            → 6 阶段管道
                          → broadcast("comparison_ready")

                      → _on_context_ready()
                        → asyncio.create_task(on_all_completed)
                          → LocalStorage.save_session()
```

**核心链路**: WebSocket → Scheduler → AIAccessManager → BrowserAIAdapter → EmbeddedEngine → EventBus → Collector → ComparisonEngine → WebSocket → UI
