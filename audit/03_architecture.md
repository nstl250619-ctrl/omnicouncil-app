# 03 架构分析

## 1. FastAPI 入口

**文件**: `backend/main.py`

**调用链**:
```
main.py
  → lifespan(): 初始化 EventBus, BrowserEngine, AIAccessManager, SchedulerCenter, ResultCollector, ComparisonEngine
  → app = FastAPI(lifespan=lifespan)
  → @app.get("/health")
  → @app.get("/api/sessions/status")
  → @app.get("/api/sessions")
  → @app.websocket("/ws")
```

**依赖**:
- `shared.event_bus.EventBus`
- `shared.config.load_config`
- `browser.factory.create_engine`
- `engine.layers.layer1_ai_access.manager.AIAccessManager`
- `engine.layers.layer2_scheduler.scheduler_center.SchedulerCenter`
- `engine.layers.layer3_collector.result_collector.ResultCollector`
- `engine.layers.layer4_comparison.comparison_engine.ComparisonEngine`
- `providers.registry.create_default_registry`

---

## 2. WebSocket 入口

**文件**: `backend/main.py` → `websocket_endpoint()`

**消息路由**:
```
submit_query  → handle_submit_query()
cancel_task   → handle_cancel_task()
get_status    → handle_get_status()
get_ais       → handle_get_ais()
check_sessions → handle_check_sessions()
reauth        → handle_reauth()
ping          → pong
```

**事件广播**:
```
ai:task:completed → ai_completed
ai:task:failed    → ai_failed
collector:progress → progress
collector:context:ready → all_completed → comparison_ready
```

---

## 3. BrowserManager 调用链

```
main.py::lifespan()
  → create_engine("embedded")
  → EmbeddedEngine.connect()
    → async_playwright().start()
    → chromium.launch_persistent_context(profile_dir)
    → 检查已保存的 session

EmbeddedEngine.login()
  → chromium.launch_persistent_context(profile_dir, headless=False)
  → page.goto(url)
  → page.on("close", on_close)
  → 等待用户关闭浏览器
  → browser.storage_state() 保存 Cookie
  → _has_saved_cookies() 检查

EmbeddedEngine.get_page()
  → _get_context(ai_id)
    → chromium.launch_persistent_context(profile_dir, headless=True)
  → context.new_page()
  → page.goto(url)
```

---

## 4. SessionManager 调用链

**文件**: `backend/engine/session/manager.py`

```
SessionManager.__init__()
  → SessionStorage(base_dir)

SessionManager.is_authenticated(ai_id)
SessionManager.set_authenticated(ai_id)
SessionManager.get_profile_dir(ai_id)
  → storage.get_profile_dir(ai_id)

SessionStorage.get_profile_dir(ai_id)
  → ~/.omnicouncil/auth/{ai_id}_profile
SessionStorage.get_auth_path(ai_id)
  → ~/.omnicouncil/auth/{ai_id}.json
SessionStorage.has_session(ai_id)
SessionStorage.save_session(ai_id, data)
SessionStorage.load_session(ai_id)
SessionStorage.delete_session(ai_id)
```

---

## 5. Provider 调用链

**文件**: `backend/providers/registry/registry.py`

```
create_default_registry()
  → auto_discover_providers()
    → 扫描 providers/ 目录
    → importlib.import_module()
    → 找到 BaseAIAdapter 子类
    → 实例化并注册

ProviderRegistry.register(adapter)
ProviderRegistry.get(ai_id)
ProviderRegistry.get_configs() → 前端 AI 列表
ProviderRegistry.toggle(ai_id, enabled)

DeepSeekProvider.config() → AIConfig
DeepSeekProvider.check_login(page) → bool
DeepSeekProvider.send_message(page, message) → str
```

---

## 6. Scheduler 调用链

**文件**: `backend/engine/layers/layer2_scheduler/scheduler_center.py`

```
SchedulerCenter.submit_query(request)
  → AISelector.get_available_ais()
  → DispatchPlanner.plan()
  → asyncio.create_task(_execute_task())

SchedulerCenter._execute_task()
  → for ai_id in ai_ids:
      → ConcurrencyController.acquire(ai_id)
      → _send_with_retry(task_id, ai_id, query)
        → AIAccessManager.send_to_ai(ai_id, query)
      → ConcurrencyController.release(ai_id)

SchedulerCenter.cancel_task()
  → cancel_event.set()
```

---

## 7. Collector 调用链

**文件**: `backend/engine/layers/layer3_collector/result_collector.py`

```
ResultCollector.__init__()
  → event_bus.on("ai:task:completed", _on_task_completed)
  → event_bus.on("ai:task:failed", _on_task_failed)
  → event_bus.on("scheduler:task:dispatched", _on_task_dispatched)

ResultCollector._on_task_completed()
  → ResponseNormalizer.normalize(response)
  → AiResult 创建
  → _check_completion(task_id)

ResultCollector._check_completion()
  → 如果所有 AI 都完成:
    → _assemble_context(task_id)
      → ContextAssembler → RoundContext
      → event_bus.emit("collector:context:ready")
```

---

## 8. Comparison 调用链

**文件**: `backend/engine/layers/layer4_comparison/comparison_engine.py`

```
ComparisonEngine.analyze(round_context)
  → TextPreprocessor.process()
  → SemanticUnitExtractor.extract()
  → SimilarityAnalyzer.analyze()
    → TfidfCalculator.fit_transform()
    → CosineSimilarity.calculate()
    → LcsCalculator.lcs_ratio()
  → DifferenceAnalyzer.detect()
    → UnionFind 聚类
  → UniqueInsightExtractor.extract()
  → ComparisonAssembler.assemble()
  → ComparisonContext 输出
```

---

## 9. Judge 调用链

**文件**: `backend/engine/judge/engine.py`

```
JudgeEngine.__init__(api_keys)
JudgeEngine.has_api_key(provider)
JudgeEngine.set_api_key(provider, api_key)
JudgeEngine.judge(query, responses, consensus, judge_provider)
  → _build_judge_prompt()
  → _call_api(provider, prompt)  # 占位符，未实现
  → JudgeVerdict 输出
```

**注意**: JudgeEngine 的 `_call_api()` 是占位符，返回模拟数据。
