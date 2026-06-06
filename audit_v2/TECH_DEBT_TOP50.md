# 技术债 Top 50

## P0 — 必须立即修复 (5 项)

### 1. 内存泄漏: SchedulerCenter._tasks 无限增长
- **文件**: `backend/engine/layers/layer2_scheduler/scheduler_center.py:57`
- **原因**: `_tasks` dict 永不清理。`cleanup_old_tasks()` 方法存在但从未被调用
- **影响**: 长时间运行后 OOM。每个任务约 200 字节，高频使用下数小时即可积累数千条
- **修复**: 在 lifespan 中添加定时任务调用 `cleanup_old_tasks()`，或在任务完成时自动清理
- **工作量**: 0.5h

### 2. 内存泄漏: ResultCollector._contexts 无限增长
- **文件**: `backend/engine/layers/layer3_collector/result_collector.py:35`
- **原因**: `_contexts` dict 存储所有 RoundContext，永不清理
- **影响**: 每个 RoundContext 包含完整的 AI 响应文本（可能数 KB），长期运行后 OOM
- **修复**: 添加 LRU 淘汰或定时清理
- **工作量**: 0.5h

### 3. 内存泄漏: ComparisonEngine._contexts 无限增长
- **文件**: `backend/engine/layers/layer4_comparison/comparison_engine.py:38`
- **原因**: `_contexts` dict 存储所有 ComparisonContext，包含完整的语义单元和相似度矩阵
- **影响**: 每个 ComparisonContext 可能数十 KB，长期运行后 OOM
- **修复**: 添加 LRU 淘汰或定时清理
- **工作量**: 0.5h

### 4. Provider/Adapter 双重架构
- **文件**: `backend/providers/` + `backend/engine/layers/layer1_ai_access/`
- **原因**: Provider 系统（BaseProvider）和 Adapter 系统（AIAdapter）独立存在，同一 AI 的逻辑实现两次
- **影响**: 修改 DeepSeek 行为需要改 `providers/deepseek/provider.py` + `adapters/deepseek_browser.py` + `browser_adapter.py` 三处
- **修复**: 合并为一套系统。Provider 的 `send_message()` 逻辑应迁移到 Adapter
- **工作量**: 8h

### 5. 响应提取逻辑 6 处重复
- **文件**: `providers/deepseek/provider.py:33-77`, `providers/qianwen/provider.py:35-91`, `providers/gemini/provider.py:36-95`, `providers/chatgpt/provider.py:36-105`, `providers/claude/provider.py:33-90`, `browser_adapter.py:171-210`
- **原因**: 每个 Provider 和 Adapter 都独立实现了相同的 "轮询 body 文本 → 找 prompt → 等待空闲" 模式
- **影响**: Bug 修复需要改 6 处，容易遗漏
- **修复**: 提取为 `browser_adapter.py` 中的通用方法，Provider 删除 `send_message()` 实现
- **工作量**: 4h

---

## P1 — 高优先级 (15 项)

### 6. ConflictEngine 未接入运行链路
- **文件**: `backend/engine/conflict/engine.py`
- **原因**: 无任何代码调用 ConflictEngine。依赖旧版类型（`AIResponse` from `..collector.response`）
- **影响**: 前端 ConflictTab 显示空内容，用户看到的功能实际不工作
- **修复**: 要么接入运行链路，要么删除 ConflictTab 和相关代码
- **工作量**: 4h (接入) 或 1h (删除)

### 7. ConsensusEngine 未接入运行链路
- **文件**: `backend/engine/consensus/engine.py`
- **原因**: 同 ConflictEngine
- **影响**: 前端 ConsensusTab 显示空内容
- **修复**: 同上
- **工作量**: 4h (接入) 或 1h (删除)

### 8. JudgeEngine 未接入运行链路
- **文件**: `backend/engine/judge/engine.py`
- **原因**: `_call_api()` 返回 mock 数据，无实际 API 调用
- **影响**: Judge 功能完全不可用
- **修复**: 要么实现 API 调用，要么删除
- **工作量**: 8h (实现) 或 0.5h (删除)

### 9. 无单元测试覆盖
- **文件**: `backend/tests/`
- **原因**: 只有冒烟测试和集成测试，无针对 Layer1-4 的单元测试
- **影响**: 重构无安全网，Bug 难以在开发阶段发现
- **修复**: 为每个 Layer 添加单元测试，目标覆盖率 80%
- **工作量**: 24h

### 10. Browser 硬编码 AI 特定逻辑
- **文件**: `backend/browser/embedded_engine.py:56,122-133,270-307`
- **原因**: `connect()` 硬编码 AI ID 列表，`check_auth()` 硬编码 URL 检查，`_quick_login_check()` 硬编码 deepseek/qianwen 逻辑
- **影响**: 添加新 AI 需要修改 Browser 层代码
- **修复**: 将 AI 特定逻辑移到 Provider/Adapter，Browser 只提供通用能力
- **工作量**: 4h

### 11. EventBus 静默吞掉处理器异常
- **文件**: `backend/shared/event_bus.py:76-77`
- **原因**: `except Exception: logger.exception(...)` — 处理器失败只记录日志，不传播
- **影响**: 事件处理器中的 Bug 被隐藏，系统继续运行但数据可能不一致
- **修复**: 添加可选的错误传播机制，或至少发送错误事件
- **工作量**: 2h

### 12. SessionManager/Storage 完全未使用
- **文件**: `backend/engine/session/manager.py`, `backend/engine/session/storage.py`
- **原因**: 登录由 EmbeddedEngine 直接管理，SessionManager 从未被实例化
- **影响**: 125 行死代码，误导新开发者
- **修复**: 删除整个 `engine/session/` 目录
- **工作量**: 0.5h

### 13. CDPEngine 未使用
- **文件**: `backend/browser/cdp_engine.py`
- **原因**: main.py 硬编码 `browser_mode = "embedded"`
- **影响**: 212 行死代码，CDP 模式完全不可用
- **修复**: 要么通过配置启用，要么删除
- **工作量**: 0.5h (删除) 或 2h (配置化)

### 14. ProviderRegistry 与实际 AI 调用脱节
- **文件**: `backend/providers/registry/registry.py`
- **原因**: ProviderRegistry 注册了 5 个 Provider，但只有 `get_configs()` 被使用（发送 UI 信息）。Provider 的 `send_message()`/`check_login()` 从未被调用
- **影响**: Provider 系统是空壳，实际调用走 Adapter 系统
- **修复**: 统一为一套系统
- **工作量**: 8h

### 15. SchedulerCenter._tasks 无 LRU 淘汰
- **文件**: `backend/engine/layers/layer2_scheduler/scheduler_center.py:59`
- **原因**: `_max_stored_tasks = 1000` 但 `cleanup_old_tasks()` 从未被调用
- **影响**: 任务字典可能增长到数千条
- **修复**: 在 `_execute_task_safe` 的 finally 中调用清理
- **工作量**: 0.5h

### 16. 无前端测试
- **文件**: `src/`
- **原因**: 0 个测试文件
- **影响**: 前端修改无法自动验证
- **修复**: 添加组件测试（Vitest + Testing Library）
- **工作量**: 16h

### 17. RateLimiter._timestamps 无自动清理
- **文件**: `backend/engine/layers/layer1_ai_access/managers/rate_limiter.py:39`
- **原因**: 只在 `allow()` 中清理 60 秒前的时间戳，但如果不再调用 `allow()`，数据永不清理
- **影响**: 长期运行后内存缓慢增长
- **修复**: 添加定期清理或 LRU
- **工作量**: 1h

### 18. 缺少 default.yaml 配置文件
- **文件**: `backend/config/default.yaml` (不存在)
- **原因**: `load_config()` 尝试加载此文件，不存在时回退到默认值
- **影响**: 用户无法通过配置文件自定义行为
- **修复**: 创建 `config/default.yaml` 模板
- **工作量**: 0.5h

### 19. GlobalExceptionHandler 中文硬编码
- **文件**: `backend/ws/connection.py:88-95`
- **原因**: 错误消息和建议硬编码为中文字符串
- **影响**: 无法国际化，错误映射表不完整
- **修复**: 使用错误码 + i18n 文件
- **工作量**: 2h

### 20. WebSocket 消息类型无 Schema 验证
- **文件**: `backend/ws/connection.py:126-155`
- **原因**: 消息类型通过字符串匹配，payload 无 schema 验证
- **影响**: 前后端协议容易不同步，错误输入难以发现
- **修复**: 定义 WebSocket 消息 schema（Pydantic 或 JSON Schema）
- **工作量**: 4h

---

## P2 — 中优先级 (15 项)

### 21. AppState 作为全局服务定位器
- **文件**: `backend/shared/app_state.py`
- **原因**: 所有模块通过 `AppState.instance()` 访问其他模块
- **影响**: 依赖关系不透明，无法独立测试
- **修复**: 使用依赖注入（构造函数注入）
- **工作量**: 8h

### 22. EventBus 单例模式
- **文件**: `backend/shared/event_bus.py:24-29`
- **原因**: `__new__` 实现单例，但 `__init__` 每次调用都会重置
- **影响**: 如果在非 lifespan 上下文创建 EventBus，可能覆盖已有实例
- **修复**: 使用 `create()` 类方法模式（同 AppState）
- **工作量**: 1h

### 23. Provider.send_message() 未被使用
- **文件**: `backend/providers/*/provider.py`
- **原因**: 5 个 Provider 的 `send_message()` 从未被调用
- **影响**: 约 300 行死代码
- **修复**: 删除或迁移到 Adapter
- **工作量**: 1h

### 24. Provider.check_login() 未被使用
- **文件**: `backend/providers/*/provider.py`
- **原因**: 5 个 Provider 的 `check_login()` 从未被调用
- **影响**: 约 150 行死代码
- **修复**: 删除或迁移到 Browser 层
- **工作量**: 1h

### 25. EmbeddedEngine._quick_login_check() 硬编码
- **文件**: `backend/browser/embedded_engine.py:270-294`
- **原因**: 硬编码 deepseek/qianwen 的登录检测逻辑
- **影响**: 添加新 AI 需要修改此方法
- **修复**: 通过 Provider 接口提供登录检测
- **工作量**: 2h

### 26. comparison_config.py 多余重导出
- **文件**: `backend/engine/layers/layer4_comparison/comparison_config.py`
- **原因**: 只有一行 `from shared.config import ComparisonConfig`
- **影响**: 多余的间接层
- **修复**: 直接从 `shared.config` 导入
- **工作量**: 0.25h

### 27. Header.tsx 未使用
- **文件**: `src/components/Header.tsx`
- **原因**: 未被 App.tsx 或任何组件引用
- **影响**: 19 行死代码
- **修复**: 删除
- **工作量**: 0.1h

### 28. SetupWizard.tsx 未使用
- **文件**: `src/components/SetupWizard.tsx`
- **原因**: AIPlatformManager 替代了它
- **影响**: 238 行死代码
- **修复**: 删除
- **工作量**: 0.1h

### 29. SkeletonLoader.tsx 未使用
- **文件**: `src/components/SkeletonLoader.tsx`
- **原因**: 未被任何组件引用
- **影响**: 20 行死代码
- **修复**: 删除
- **工作量**: 0.1h

### 30. appStore.ts 中 review/debate Tab 定义
- **文件**: `src/stores/appStore.ts:8`
- **原因**: `TabId` 类型包含 `'review' | 'debate'`，但无对应组件
- **影响**: 类型定义误导
- **修复**: 从 TabId 中移除，或实现对应组件
- **工作量**: 0.25h

### 31. ResultCollector.get_latest_round_context() 冗余
- **文件**: `backend/engine/layers/layer3_collector/result_collector.py:147`
- **原因**: 与 `get_round_context()` 完全相同
- **影响**: 代码冗余
- **修复**: 删除，统一使用 `get_round_context()`
- **工作量**: 0.25h

### 32. ResultCollector.get_partial_results() 未使用
- **文件**: `backend/engine/layers/layer3_collector/result_collector.py:151`
- **原因**: 未被调用
- **影响**: 死代码
- **修复**: 删除或接入（可用于前端实时显示）
- **工作量**: 0.25h

### 33. ResultCollector.on_context_ready() 未使用
- **文件**: `backend/engine/layers/layer3_collector/result_collector.py:156`
- **原因**: 直接通过 EventBus 注册，此方法冗余
- **影响**: 死代码
- **修复**: 删除
- **工作量**: 0.25h

### 34. AIAdapter.stop_generation() 空实现
- **文件**: `backend/engine/layers/layer1_ai_access/browser_adapter.py:223-224`
- **原因**: `pass` — 无法停止正在进行的生成
- **影响**: 用户取消任务后，AI 请求仍在进行
- **修复**: 实现页面级停止（点击停止按钮或关闭页面）
- **工作量**: 4h

### 35. Gemini.json 配置未使用
- **文件**: `backend/engine/layers/layer1_ai_access/config/gemini.json`
- **原因**: 无 Gemini Adapter 使用此配置
- **影响**: 配置文件是死代码
- **修复**: 删除或实现 Gemini Adapter
- **工作量**: 0.1h (删除) 或 8h (实现)

---

## P3 — 低优先级 (15 项)

### 36. 错误码使用字符串而非枚举
- **文件**: `backend/shared/errors.py`, `backend/engine/layers/layer1_ai_access/manager.py`
- **原因**: 错误码如 `"ADAPTER_NOT_FOUND"`, `"CIRCUIT_OPEN"` 是硬编码字符串
- **影响**: 容易拼写错误，无法自动验证
- **修复**: 使用 StrEnum 定义错误码
- **工作量**: 1h

### 37. EventBus 事件名使用字符串
- **文件**: 多处
- **原因**: 事件名如 `"ai:task:completed"` 是硬编码字符串
- **影响**: 容易拼写错误
- **修复**: 使用常量或枚举定义事件名
- **工作量**: 1h

### 38. WebSocket 消息类型使用字符串
- **文件**: `backend/ws/connection.py`, `src/stores/appStore.ts`
- **原因**: 消息类型如 `"submit_query"`, `"ai_completed"` 是硬编码字符串
- **影响**: 前后端容易不同步
- **修复**: 共享类型定义
- **工作量**: 2h

### 39. Provider.on_login_start() 空实现
- **文件**: `backend/providers/base/provider.py:64`
- **原因**: 空方法，有 `# noqa: B027` 注释
- **影响**: 代码噪音
- **修复**: 删除或标记为可选
- **工作量**: 0.25h

### 40. Provider.on_login_success() 空实现
- **文件**: `backend/providers/base/provider.py:68`
- **原因**: 同上
- **影响**: 代码噪音
- **修复**: 同上
- **工作量**: 0.25h

### 41. Provider.on_session_expired() 返回 False
- **文件**: `backend/providers/base/provider.py:72`
- **原因**: 硬编码返回 False
- **影响**: 代码噪音
- **修复**: 同上
- **工作量**: 0.25h

### 42. Provider.get_input_selector() 未使用
- **文件**: `backend/providers/base/provider.py:76`
- **原因**: 返回 "textarea"，但实际选择逻辑在 Adapter 中
- **影响**: 死代码
- **修复**: 删除
- **工作量**: 0.25h

### 43. Provider.get_submit_selector() 未使用
- **文件**: `backend/providers/base/provider.py:81`
- **原因**: 返回 None
- **影响**: 死代码
- **修复**: 删除
- **工作量**: 0.25h

### 44. ProviderRegistry.unregister() 未使用
- **文件**: `backend/providers/registry/registry.py:30`
- **原因**: 未被调用
- **影响**: 死代码
- **修复**: 删除或保留（合理的 API）
- **工作量**: 0.1h

### 45. ProviderRegistry.get_enabled() 未使用
- **文件**: `backend/providers/registry/registry.py:41`
- **原因**: 未被调用
- **影响**: 死代码
- **修复**: 删除或保留
- **工作量**: 0.1h

### 46. ProviderRegistry.toggle() 未使用
- **文件**: `backend/providers/registry/registry.py:56`
- **原因**: 未被调用，且实现有问题（修改 frozen dataclass 的字段）
- **影响**: 死代码 + 潜在运行时错误
- **修复**: 删除
- **工作量**: 0.1h

### 47. EventBus.off() 未使用
- **文件**: `backend/shared/event_bus.py:51`
- **原因**: 未被调用
- **影响**: 死代码
- **修复**: 保留（合理的 API）
- **工作量**: 0h

### 48. EventBus.emit_sync() 未使用
- **文件**: `backend/shared/event_bus.py:79`
- **原因**: 未被调用
- **影响**: 死代码
- **修复**: 删除或保留
- **工作量**: 0.1h

### 49. AIAccessManager.stop_generation() 未被调用
- **文件**: `backend/engine/layers/layer1_ai_access/manager.py:192`
- **原因**: Scheduler 未调用此方法
- **影响**: 用户无法停止正在进行的 AI 生成
- **修复**: 在 cancel_task 中调用
- **工作量**: 1h

### 50. AIAccessManager.get_provider_status() 未被调用
- **文件**: `backend/engine/layers/layer1_ai_access/manager.py:77`
- **原因**: 未被调用
- **影响**: 死代码
- **修复**: 删除或接入状态查询
- **工作量**: 0.25h

---

## 汇总

| 等级 | 数量 | 总工作量 |
|------|------|----------|
| P0 | 5 | ~17h |
| P1 | 15 | ~67h |
| P2 | 15 | ~18h |
| P3 | 15 | ~6h |
| **总计** | **50** | **~108h** |

### 建议修复顺序

1. **Week 1**: P0 内存泄漏 (#1-3) + P1 废弃代码清理 (#6-8, 12-13)
2. **Week 2**: P0 统一 Provider/Adapter (#4-5)
3. **Week 3-4**: P1 添加单元测试 (#9) + Browser 去硬编码 (#10)
4. **Week 5**: P1 剩余项 + P2 高价值项
5. **持续**: P2/P3 随开发迭代清理
