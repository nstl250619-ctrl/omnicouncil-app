# 第六阶段 · 删除清单

## V1 源文件（19 个，已删除）

| 路径 | 行数(原) | 所属层 | 删除原因 |
|---|---|---|---|
| `backend/main.py` | 229 | 入口 | V1 入口，Tauri 已切到 V2 |
| `backend/providers/runtime.py` | ~160 | Provider OS | V2 已有 AIRuntimeEngine + RuntimeRegistry |
| `backend/providers/session_manager.py` | ~95 | 会话 | V2 已有 SessionValidator |
| `backend/providers/health_monitor.py` | ~110 | 健康 | V2 已有 runtime/health_monitor.py |
| `backend/providers/event_bus.py` | ~50 | 事件 | V2 已有 shared/event_bus.py |
| `backend/providers/vision_fallback.py` | ~120 | 视觉兜底 | 未接入 V2 |
| `backend/providers/errors.py` | ~50 | 错误类型 | V2 已有 shared/error_types.py |
| `backend/providers/base/provider.py` | ~340 | Provider 基类 | V2 用 BaseQueryAdapter |
| `backend/providers/registry/__init__.py` | 5 | 包入口 | 整目录删除 |
| `backend/providers/registry/registry.py` | ~90 | V1 注册 | V2 用 providers/registry.py |
| `backend/providers/deepseek/provider.py` | ~150 | V1 Provider | V2 用 query_adapter.py |
| `backend/providers/chatgpt/provider.py` | ~150 | V1 Provider | V2 用 query_adapter.py |
| `backend/providers/qianwen/provider.py` | ~150 | V1 Provider | V2 用 query_adapter.py |
| `backend/providers/gemini/provider.py` | ~150 | V1 Provider | V2 用 query_adapter.py |
| `backend/providers/mimo/provider.py` | ~150 | V1 Provider | V2 用 query_adapter.py |
| `backend/providers/claude/provider.py` | ~150 | V1 Provider | V2 用 query_adapter.py |
| `backend/engine/judge/` | 整目录 | V1 Judge 占位 | V2 packages/judge-engine |
| `backend/engine/consensus/` | 整目录 | V1 Consensus | V2 packages/consensus-engine |
| `backend/engine/conflict/` | 整目录 | V1 Conflict | V2 packages/conflict-engine |
| `backend/engine/comparison/` | 整目录 | V1 Comparison | V2 packages/comparison-engine |

**合计约 2,150 行 V1 死代码被删除。**

## V1 测试文件（12 个，已删除）

| 路径 | 原因 |
|---|---|
| `backend/tests/test_integration.py` | V1 集成测试，V2 已有 test_integration_v2.py |
| `backend/tests/test_query_adapter.py` | V1 测试，V2 已有 test_query_adapter_coverage.py |
| `backend/tests/test_query_adapter_coverage.py` | 与上一同名重复，重写为 test_stress_v2.py |
| `backend/tests/test_runtime_engine.py` | V1 Runtime 测试，V2 集成在 test_integration_v2.py |
| `backend/tests/test_recovery_engine.py` | V1 Recovery，V2 集成在 test_integration_v2.py |
| `backend/tests/test_profile_manager.py` | V1 Profile，V2 集成在 test_integration_v2.py |
| `backend/tests/test_session_validator.py` | V1 Session，V2 集成在 test_integration_v2.py |
| `backend/tests/test_state_machine.py` | V1 StateMachine，V2 集成在 test_integration_v2.py |
| `backend/tests/test_health_monitor.py` | V1 Health，V2 集成在 test_integration_v2.py |
| `backend/tests/test_stress.py` | V1 压测，重写为 test_stress_v2.py |
| `backend/tests/test_provider_runtime.py` | V1 ProviderRuntime 测试 |
| `backend/tests/test_provider_base.py` | V1 BaseProvider 测试 |

**合计约 4,800 行 V1 测试被删除，新增 ~430 行 V2 压测。**

## V1 引用清理（4 个文件，已修复）

| 文件 | 改动 |
|---|---|
| `backend/providers/__init__.py` | 移除 `BaseProvider` 导入，改 `BaseQueryAdapter` |
| `backend/providers/base/__init__.py` | 移除 `.provider` 导入，改 `.query_adapter` |
| `backend/providers/{6 平台}/__init__.py` | 移除 `.provider` 导入，改 `.query_adapter` |
| `backend/shared/app_state.py` | 移除 TYPE_CHECKING 导入 `providers.runtime.ProviderRuntime` |
| `backend/engine/layers/layer1_ai_access/manager.py` | TYPE_CHECKING 改 BaseQueryAdapter |
| `backend/engine/layers/layer1_ai_access/managers/provider_manager.py` | 同上 |
| `backend/tests/test_smoke.py` | TestProviderImports 改 V2 |
| `backend/tests/test_coverage_boost.py` | 删除 TestProviderRuntimeFull |

## 验证

```bash
$ grep -rE "providers\.runtime|providers\.session_manager|providers\.health_monitor|providers\.event_bus|providers\.vision_fallback|providers\.errors|providers\.base\.provider\b|from engine\.judge|from engine\.consensus|from engine\.conflict|from engine\.comparison" backend/ src/ src-tauri/ scripts/
# (zero matches)
```
