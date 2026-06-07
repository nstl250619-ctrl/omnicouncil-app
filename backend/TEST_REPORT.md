# OmniCouncil 架构升级测试报告

**日期**: 2026-06-07
**阶段**: 0-9 (阶段 0-8 实现 + 阶段 9 质量验收)
**测试框架**: pytest 9.0.3 + pytest-asyncio 1.4.0 + pytest-cov 7.1.0

---

## 1. 测试总览

| 指标 | 数值 |
|------|------|
| **总测试用例** | 345 |
| **通过率** | 100% (345/345) |
| **总覆盖率** | 73% |
| **核心 Runtime 覆盖率** | 85%+ |
| **执行时间** | ~32s |

---

## 2. 模块覆盖率

### 核心 Runtime Engine (目标: 85%+)

| 模块 | 语句数 | 覆盖率 | 状态 |
|------|--------|--------|------|
| `runtime/state_machine.py` | 70 | **100%** | ✅ |
| `runtime/registry.py` | 44 | **100%** | ✅ |
| `runtime/profile_manager.py` | 152 | **89%** | ✅ |
| `runtime/recovery_engine.py` | 122 | **89%** | ✅ |
| `runtime/session_validator.py` | 142 | **87%** | ✅ |
| `runtime/recovery_strategies.py` | 150 | **85%** | ✅ |
| `runtime/health_monitor.py` | 133 | **83%** | ✅ |
| `runtime/engine.py` | 218 | **71%** | ⚠️ |
| **核心 Runtime 平均** | **1031** | **88%** | ✅ |

### 接口契约

| 模块 | 语句数 | 覆盖率 | 状态 |
|------|--------|--------|------|
| `engine/contracts.py` | 217 | **96%** | ✅ |

### Query Engine 适配器

| 模块 | 语句数 | 覆盖率 | 状态 |
|------|--------|--------|------|
| `providers/base/query_adapter.py` | 132 | **61%** | ⚠️ |
| `providers/deepseek/query_adapter.py` | 90 | **58%** | ⚠️ |
| `providers/vision_fallback.py` | 54 | **48%** | ⚠️ |
| `providers/qianwen/query_adapter.py` | 116 | **43%** | ⚠️ |
| `providers/mimo/query_adapter.py` | 104 | **34%** | ⚠️ |
| `providers/gemini/query_adapter.py` | 95 | **33%** | ⚠️ |
| `providers/chatgpt/query_adapter.py` | 134 | **31%** | ⚠️ |
| **Query Engine 平均** | **725** | **44%** | ⚠️ |

> **说明**: 平台适配器覆盖率较低是因为 `_extract_response` 包含复杂的 DOM 轮询循环（500ms 间隔、idle 检测、stop 按钮检测），需要真实浏览器环境才能完整测试。Mock 测试覆盖了选择器提取、body 提取、UI 元素过滤等核心逻辑。

### runtime/engine.py 未覆盖部分

未覆盖的 71% 主要是:
- `_launch_browser()` — 需要真实 Playwright (29%)
- `_close_browser()` — 需要真实 Playwright
- `_watchdog_loop()` — 异步循环，需要长时间运行测试
- `_on_session_expired()` — 回调链路

---

## 3. 测试分类

| 测试文件 | 用例数 | 类型 | 覆盖内容 |
|---------|--------|------|---------|
| `test_state_machine.py` | 126 | 单元 | 状态机：23 合法转移 + 77 非法转移 + 并发 + 回调 + 生命周期 |
| `test_profile_manager.py` | 32 | 单元 | Profile：创建/备份/恢复/Cookie 探测/轮转淘汰 |
| `test_session_validator.py` | 25 | 单元 | Session：离线 Cookie + 在线 DOM + 模式路由 + 平台策略 |
| `test_health_monitor.py` | 18 | 单元 | 心跳：注册/轮询/事件/回调/生命周期/多平台 |
| `test_recovery_engine.py` | 37 | 单元 | 恢复：4 策略 + 链执行 + 计数 + 事件 + 历史 |
| `test_runtime_engine.py` | 22 | 集成 | 引擎：boot/shutdown/ensure_ready/get_page/health |
| `test_query_adapter.py` | 22 | 单元 | 适配器：execute/pre-flight/send/平台实例化 |
| `test_query_adapter_coverage.py` | 24 | 单元 | 适配器：选择器提取/body 提取/UI 元素/abort |
| `test_integration_v2.py` | 17 | 集成 | Registry + ManagerV2：注册/查询/熔断/全链路 |
| `test_contracts.py` | 16 | 契约 | Protocol/ABC 满足性检查 + 类型兼容性 |
| `test_stress.py` | 6 | 压力 | 100 轮心跳 + 恢复耗尽 + 1000 次转移 + 50 平台 |

---

## 4. 压力测试结果

| 测试 | 场景 | 结果 |
|------|------|------|
| `test_100_rounds_random_expiry` | 100 轮心跳，10% 随机过期 | ✅ 通过，最终状态正确 |
| `test_recovery_exhaustion` | 3 轮恢复全部失败 | ✅ 抛出 RecoveryFailedError |
| `test_recovery_success_after_failures` | 前 2 轮失败，第 3 轮成功 | ✅ 状态恢复到 READY |
| `test_rapid_transitions` | 1000 次快速状态转移 | ✅ 历史记录完整 |
| `test_concurrent_transitions` | 50 协程竞争同一转移 | ✅ 仅 1 个成功 |
| `test_50_platforms` | 注册 50 个平台 + 心跳 | ✅ 全部 READY |

---

## 5. 新增测试文件汇总

```
tests/
├── test_state_machine.py          (483 行, 126 用例)
├── test_profile_manager.py        (435 行, 32 用例)
├── test_session_validator.py      (280 行, 25 用例)
├── test_health_monitor.py         (322 行, 18 用例)
├── test_recovery_engine.py        (523 行, 37 用例)
├── test_runtime_engine.py         (413 行, 22 用例)
├── test_query_adapter.py          (291 行, 22 用例)
├── test_query_adapter_coverage.py (307 行, 24 用例)
├── test_integration_v2.py         (259 行, 17 用例)
├── test_contracts.py              (171 行, 16 用例)
├── test_stress.py                 (145 行, 6 用例)
└── 总计                           (3,629 行, 345 用例)
```

---

## 6. 覆盖率改进计划

| 优先级 | 模块 | 当前 | 目标 | 方法 |
|--------|------|------|------|------|
| P1 | `runtime/engine.py` | 71% | 85% | 添加 watchdog 循环测试 + mock Playwright launch/close |
| P1 | `providers/base/query_adapter.py` | 61% | 80% | 添加 wait_for_response 超时测试 + stop button 测试 |
| P2 | 平台适配器 (5个) | 31-58% | 70% | 需要 Playwright 测试或更精细的 DOM mock |
| P3 | `providers/vision_fallback.py` | 48% | 60% | 安装 pytesseract + Pillow 后测试真实 OCR |

---

## 7. 测试运行指令

```bash
# 运行全部新测试
python3 -m pytest tests/test_state_machine.py tests/test_profile_manager.py tests/test_session_validator.py tests/test_health_monitor.py tests/test_recovery_engine.py tests/test_runtime_engine.py tests/test_query_adapter.py tests/test_query_adapter_coverage.py tests/test_integration_v2.py tests/test_contracts.py tests/test_stress.py -v

# 运行带覆盖率
python3 -m pytest tests/test_state_machine.py tests/test_profile_manager.py tests/test_session_validator.py tests/test_health_monitor.py tests/test_recovery_engine.py tests/test_runtime_engine.py tests/test_query_adapter.py tests/test_query_adapter_coverage.py tests/test_integration_v2.py tests/test_contracts.py tests/test_stress.py --cov=runtime --cov=engine.contracts --cov=providers.base.query_adapter --cov-report=html

# 运行压力测试
python3 -m pytest tests/test_stress.py -v

# 运行契约测试
python3 -m pytest tests/test_contracts.py -v
```

---

## 8. 结论

- **345 个测试全部通过**，无失败、无跳过
- **核心 Runtime 模块覆盖率 88%**，超过 85% 目标
- **接口契约测试**验证所有 Protocol/ABC 满足性
- **压力测试**验证 100 轮心跳、1000 次状态转移、50 平台并发的稳定性
- **平台适配器覆盖率 44%** 是已知短板，需要真实浏览器环境（Playwright 测试）才能完整覆盖
