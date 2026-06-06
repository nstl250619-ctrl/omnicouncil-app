# 运行时状态流

## 任务生命周期

```
用户提交问题 → Scheduler → Provider → Collector → Comparison → WebSocket → UI
```

## 逐步状态分析

### Step 1: 用户提交问题

**入口**: `ws/connection.py: handle_submit_query()`

**输入状态**:
```
{
  "type": "submit_query",
  "data": {
    "query": "什么是量子计算？",
    "ai_ids": ["deepseek", "qianwen"],
    "mode": "parallel"
  }
}
```

**维护的状态对象**:
- `ConnectionManager.active_connections` — 活跃 WebSocket 连接列表

**输出**: 调用 `scheduler.submit_query(QueryRequest)`

---

### Step 2: Scheduler 接收任务

**入口**: `scheduler_center.py: submit_query()`

**状态转换**:
```
TaskStatusInfo:
  status: CREATED → DISPATCHED
  progress: TaskProgress(total_ais=2, completed_ais=0, failed_ais=0)
  created_at: timestamp
  updated_at: timestamp
```

**维护的状态对象**:
- `SchedulerCenter._tasks: dict[str, TaskStatusInfo]` — 所有任务状态
- `SchedulerCenter._cancel_events: dict[str, asyncio.Event]` — 取消信号

**事件发射**:
1. `emit("scheduler:task:created", task_id, selected_ai_ids, mode, query)`
2. `emit("scheduler:task:dispatched", task_id, selected_ai_ids, query, mode)`

**副作用**:
- `ResultCollector._on_task_dispatched()` 被触发 → 初始化收集器

**输出**: 返回 `TaskHandle(task_id, DISPATCHED)`, 后台启动 `_execute_task`

---

### Step 3: Scheduler 调度执行

**入口**: `scheduler_center.py: _execute_task()`

**状态转换**:
```
TaskStatusInfo:
  status: DISPATCHED → RUNNING
```

**维护的状态对象**:
- `TimeoutManager._start_times` — 记录任务开始时间
- `ConcurrencyController._semaphore` — 并发信号量 (max=2)
- `ConcurrencyController._last_dispatch` — 每 AI 最后调度时间
- `RetryManager._attempt_counts` — 重试计数

**对每个 AI 并行执行**:
```
_send_one(ai_id):
  → ConcurrencyController.acquire(ai_id)   # 等待并发槽 + AI 间隔
  → _send_with_retry(task_id, ai_id, query)
  → ConcurrencyController.release(ai_id)
```

---

### Step 4: AI Access Manager 发送请求

**入口**: `manager.py: send_to_ai()`

**检查链**:
```
1. ProviderManager.get(ai_id) → 获取适配器
2. CircuitBreaker.should_allow() → 熔断检查
3. RateLimiter.allow() → 限流检查
4. BrowserAIAdapter.send_prompt() → 实际发送
```

**维护的状态对象**:
- `ProviderManager._adapters: dict[str, AIAdapter]` — 适配器注册表
- `CircuitBreaker._state` — CLOSED/OPEN/HALF_OPEN
- `CircuitBreaker._consecutive_failures` — 连续失败计数
- `RateLimiter._timestamps` — 请求时间戳列表
- `RateLimiter._cooldown_until` — 冷却截止时间
- `RateLimiter._request_count` — 请求计数（触发冷却）

**状态转换**:
```
AIAdapter._status: INITIALIZING → BUSY → READY (成功)
                                  → BUSY → LOGIN_REQUIRED (需要登录)
                                  → BUSY → READY (失败后恢复)
```

---

### Step 5: Browser 执行请求

**入口**: `browser_adapter.py: send_prompt() → _send_async()`

**执行流程**:
```
1. EmbeddedEngine.get_page(ai_id, url)
   → 维护: _pages[ai_id] = page
   → 维护: _contexts[ai_id] = context

2. EmbeddedEngine.check_auth(ai_id)
   → 检查: page.url 是否包含登录页面标识

3. BrowserAIAdapter._find_input(page)
   → 查找: textarea / contenteditable

4. page.fill(prompt) + page.keyboard.press("Enter")

5. BrowserAIAdapter._extract_response(page, prompt, timeout_ms)
   → 轮询: page.locator("body").inner_text()
   → 检测: 空闲 3 秒 → 返回结果
```

**维护的状态对象**:
- `EmbeddedEngine._playwright` — Playwright 实例
- `EmbeddedEngine._contexts: dict[str, Context]` — 浏览器上下文
- `EmbeddedEngine._pages: dict[str, Page]` — 浏览器页面
- `EmbeddedEngine._authenticated: set[str]` — 已认证 AI 集合
- `EmbeddedEngine._connected: bool` — 连接状态

**超时**: 120 秒（从 config），轮询间隔 500ms

---

### Step 6: AI 响应返回

**入口**: `manager.py: send_to_ai()` 返回

**成功路径**:
```
1. CircuitBreaker.record_success()
   → _consecutive_failures = 0
   → if HALF_OPEN → transition to CLOSED

2. RateLimiter.record(ai_id)
   → _timestamps[ai_id].append(now)
   → _request_count[ai_id] += 1
   → if count >= cooldown_after_n → 设置冷却

3. emit("ai:task:completed", task_id, ai_id, response)
```

**失败路径**:
```
1. CircuitBreaker.record_failure()
   → _consecutive_failures += 1
   → if >= failure_threshold → transition to OPEN

2. emit("ai:task:failed", task_id, ai_id, error)
```

**维护的状态对象 (AIResponse)**:
```python
AIResponse(
  success=True,
  ai_id="deepseek",
  task_id="task_xxx",
  content="量子计算是...",
  model="deepseek",
  timestamp=1234567890.0,
  duration=15.3,
  word_count=256,
)
```

---

### Step 7: Collector 收集结果

**入口**: `result_collector.py: _on_task_completed()` / `_on_task_failed()`

**状态积累**:
```
_pending[task_id][ai_id] = AiResult(...)
```

**维护的状态对象**:
- `ResultCollector._pending: dict[str, dict[str, AiResult]]` — 待完成结果
- `ResultCollector._expected: dict[str, int]` — 每任务期望结果数
- `ResultCollector._queries: dict[str, str]` — 原始查询
- `ResultCollector._modes: dict[str, TaskMode]` — 执行模式

**标准化**:
```python
AiResult(
  ai_id="deepseek",
  task_id="task_xxx",
  round_number=1,
  status=ResultStatus.SUCCESS,
  raw_text="量子计算是...",
  normalized=NormalizedResponse(
    main_text="量子计算是...",
    code_blocks=[],
    paragraphs=["量子计算是...", "与经典计算不同..."],
    word_count=256,
    detected_language="zh",
    has_markdown=True,
  ),
  start_time=...,
  end_time=...,
  duration=15.3,
  model="deepseek",
)
```

**完成检查**:
```
if len(_pending[task_id]) >= _expected[task_id]:
  → _assemble_context(task_id)
```

---

### Step 8: RoundContext 组装

**入口**: `result_collector.py: _assemble_context()`

**输出状态**:
```python
RoundContext(
  task_id="task_xxx",
  round_number=1,
  query="什么是量子计算？",
  execution_mode=TaskMode.PARALLEL,
  results=[AiResult(...), AiResult(...)],
  summary=RoundContextSummary(
    total_ais=2,
    success_count=2,
    failure_count=0,
    timeout_count=0,
    completed_at=1234567890.0,
  ),
)
```

**维护的状态对象**:
- `ResultCollector._contexts: dict[str, RoundContext]` — 已组装的上下文

**事件发射**:
```
emit("collector:context:ready", context=round_context)
```

**清理**:
```
_pending.pop(task_id)
_expected.pop(task_id)
```

---

### Step 9: WebSocket 广播 + 触发对比

**入口**: `api/events.py: on_context_ready()`

**WebSocket 广播**:
```json
{
  "type": "all_completed",
  "data": {
    "task_id": "task_xxx",
    "summary": {
      "total_ais": 2,
      "success_count": 2,
      "failure_count": 0
    }
  }
}
```

**触发对比**:
```
asyncio.create_task(run_comparison(task_id))
```

**自动保存**:
```
asyncio.create_task(on_all_completed(task_id))
  → LocalStorage.save_session(session_data)
```

---

### Step 10: Comparison 分析

**入口**: `api/events.py: run_comparison() → comparison_engine.analyze()`

**6 阶段管道状态**:

```
Stage 1: TextPreprocessor
  输入: RoundContext
  输出: list[PreprocessedAI(ai_id, clean_paragraphs, original_indices)]
  状态: 无持久状态

Stage 2: SemanticUnitExtractor
  输入: list[PreprocessedAI]
  输出: list[SemanticUnit(unit_id, source_ai_id, content, paragraph_index)]
  状态: 无持久状态

Stage 3: SimilarityAnalyzer
  输入: list[SemanticUnit]
  输出: SimilarityMatrix(ai_ids, pairwise_similarities, unit_matrix, unit_index)
  内部状态: TfidfCalculator._vocabulary, _idf (临时)

Stage 4: DifferenceAnalyzer
  输入: units + matrix
  输出: list[DifferenceItem(id, dimension, involved_ais, strength, diff_type)]
  状态: 无持久状态

Stage 5: UniqueInsightExtractor
  输入: units + matrix
  输出: list[UniqueInsight(unit_id, ai_id, content, novelty_score)]
  状态: 无持久状态

Stage 6: ComparisonAssembler
  输入: 所有上游输出
  输出: ComparisonContext(完整分析结果)
  状态: 无持久状态
```

**最终输出状态**:
```python
ComparisonContext(
  task_id="task_xxx",
  round_number=1,
  query="什么是量子计算？",
  source_context_id="task_xxx_r1",
  participant_ais=[("deepseek", 12), ("qianwen", 15)],
  semantic_units=[SemanticUnit(...), ...],
  similarity_matrix=SimilarityMatrix(...),
  differences=[DifferenceItem(...), ...],
  unique_insights=[UniqueInsight(...), ...],
  metrics=ComparisonMetrics(
    total_units=27,
    overall_divergence=0.45,
    pairwise_similarities=[("deepseek", "qianwen", 0.55)],
    top_difference_dimension="计算原理",
  ),
)
```

**持久状态**:
- `ComparisonEngine._contexts: dict[str, ComparisonContext]` — 已分析结果

---

### Step 11: WebSocket 发送分析结果

**入口**: `api/events.py: run_comparison()`

**WebSocket 广播**:
```json
{
  "type": "comparison_ready",
  "data": {
    "task_id": "task_xxx",
    "comparison_context": {
      "task_id": "task_xxx",
      "query": "什么是量子计算？",
      "degraded": null,
      "semantic_units_count": 27,
      "differences": [...],
      "unique_insights": [...],
      "metrics": {
        "total_units": 27,
        "overall_divergence": 0.45,
        "top_difference_dimension": "计算原理"
      }
    }
  }
}
```

---

### Step 12: UI 更新

**入口**: `src/stores/appStore.ts: handleMessage()`

**状态更新**:
```typescript
// all_completed
set({ currentTaskId: data.task_id })

// comparison_ready
set({ comparison: data.comparison_context })
```

**前端维护的状态**:
```typescript
AppState {
  connectionStatus: 'connected' | 'disconnected' | 'reconnecting'
  authStatus: Record<string, { status, message }>
  currentTaskId: string | null
  query: string
  selectedAIs: string[]
  responses: Record<string, AIResponseState>  // 每个 AI 的响应状态
  comparison: Record<string, unknown> | null
  consensus: Record<string, unknown> | null   // 未使用
  conflict: Record<string, unknown> | null    // 未使用
  activeTab: TabId
}
```

---

## 全局状态汇总

### 后端持久状态 (进程生命周期)

| 对象 | 位置 | 类型 | 清理时机 |
|------|------|------|----------|
| `AppState._singleton` | shared/app_state.py | 单例 | lifespan 结束 |
| `EventBus._instance` | shared/event_bus.py | 单例 | EventBus.reset() |
| `SchedulerCenter._tasks` | scheduler_center.py | dict | cleanup_old_tasks() (**从未调用**) |
| `SchedulerCenter._cancel_events` | scheduler_center.py | dict | 任务完成时清理 |
| `ResultCollector._contexts` | result_collector.py | dict | **永不清理** |
| `ComparisonEngine._contexts` | comparison_engine.py | dict | **永不清理** |
| `ConnectionManager.active_connections` | ws/connection.py | list | 断开时清理 |
| `EmbeddedEngine._authenticated` | embedded_engine.py | set | **永不清理** |
| `EmbeddedEngine._pages` | embedded_engine.py | dict | disconnect() 时清理 |
| `EmbeddedEngine._contexts` | embedded_engine.py | dict | disconnect() 时清理 |
| `CircuitBreaker._state` | circuit_breaker.py | 单值 | **永不重置** |
| `RateLimiter._timestamps` | rate_limiter.py | dict | **永不清理** |
| `ProviderManager._adapters` | provider_manager.py | dict | **永不清理** |

### 内存泄漏风险

| 风险 | 严重度 | 原因 |
|------|--------|------|
| `SchedulerCenter._tasks` 无限增长 | **P1** | `cleanup_old_tasks()` 从未被调用 |
| `ResultCollector._contexts` 无限增长 | **P1** | 无清理机制 |
| `ComparisonEngine._contexts` 无限增长 | **P1** | 无清理机制 |
| `RateLimiter._timestamps` 无限增长 | **P2** | 只有 `reset()` 手动清理 |
| `EmbeddedEngine._authenticated` 只增不减 | **P2** | 无过期机制 |
