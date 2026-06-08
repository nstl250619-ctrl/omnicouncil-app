# 第二阶段 · 迁移方案

## 必须修改文件（10 个）

| 文件 | 改动 |
|---|---|
| `backend/engine/contracts.py` | 新增 `PageBusyError` / `RecoveryBusyError` / `PageBusyState` / `RuntimeMetrics` |
| `backend/runtime/engine.py` | 新增 `acquire_page()` / `metrics()` / `page_state` / 同步化 `_evict_page` |
| `backend/runtime/recovery_engine.py` | `recover()` 入口加 Page Busy 守卫 + `_recovery_in_progress` 锁 |
| `backend/providers/registry.py` | V2-only（来自 registry_v2），移除 V1 BaseProvider 引用 |
| `backend/shared/app_state.py` | 移除 V1 `ProviderRuntime` 字段 |
| `backend/engine/layers/layer1_ai_access/manager.py` | TYPE_CHECKING 从 BaseProvider 改 BaseQueryAdapter |
| `backend/engine/layers/layer1_ai_access/managers/provider_manager.py` | 同上 |
| `backend/api/routes.py` | 新增 `/metrics/runtime` 端点 |
| `backend/providers/{deepseek,chatgpt,qianwen,gemini,mimo,claude}/__init__.py` | 从 provider 改 query_adapter |
| `backend/tests/test_smoke.py` | TestProviderImports 改用 V2 BaseQueryAdapter |
| `backend/tests/test_coverage_boost.py` | 删除 TestProviderRuntimeFull |

## 必须删除文件（19 个 V1 源文件 + 12 个 V1 测试 = 31 个）

### V1 源文件（19）
```
backend/main.py
backend/providers/runtime.py
backend/providers/session_manager.py
backend/providers/health_monitor.py
backend/providers/event_bus.py
backend/providers/vision_fallback.py
backend/providers/errors.py
backend/providers/base/provider.py
backend/providers/registry/__init__.py
backend/providers/registry/registry.py
backend/providers/deepseek/provider.py
backend/providers/chatgpt/provider.py
backend/providers/qianwen/provider.py
backend/providers/gemini/provider.py
backend/providers/mimo/provider.py
backend/providers/claude/provider.py
backend/engine/judge/        (目录)
backend/engine/consensus/    (目录)
backend/engine/conflict/     (目录)
backend/engine/comparison/   (目录)
```

### V1 测试文件（12）
```
backend/tests/test_integration.py
backend/tests/test_query_adapter.py
backend/tests/test_query_adapter_coverage.py
backend/tests/test_runtime_engine.py
backend/tests/test_recovery_engine.py
backend/tests/test_profile_manager.py
backend/tests/test_session_validator.py
backend/tests/test_state_machine.py
backend/tests/test_health_monitor.py
backend/tests/test_stress.py
backend/tests/test_provider_runtime.py
backend/tests/test_provider_base.py
```

## 必须重命名文件（2 个）

| 原 | 新 | 原因 |
|---|---|---|
| `backend/main_v2.py` | `backend/main.py` | V2 升为唯一入口 |
| `backend/providers/registry_v2.py` | `backend/providers/registry.py` | 移除 V2 后缀 |

## 必须保留文件（V2 核心）

- `backend/runtime/` 全部（engine / health_monitor / profile_manager / recovery_engine / recovery_strategies / registry / session_validator / state_machine）
- `backend/packages/` 5 个独立 package
- `backend/engine/contracts.py`
- `backend/engine/layers/layer1_ai_access/adapters/` （5 平台 V2 adapter）
- `backend/engine/layers/layer2_scheduler/` `layer3_collector/`
- `backend/engine/session/manager.py`
- `backend/providers/<platform>/query_adapter.py` × 5
- `backend/api/` `backend/ws/` `backend/shared/` `backend/storage/` `backend/config/` `backend/browser/`
- 全部 V2 测试（test_browser / test_comparison / test_consensus / test_conflict_judge / test_contracts / test_coverage_boost / test_errors / test_event_bus / test_integration_v2 / test_layer1/2/3 / test_login_flow / test_profile_sharing / test_scheduler / test_smoke / test_storage / test_trace_metrics / test_websocket / test_ws_handlers）

## 迁移顺序（执行记录）

1. ✅ 新增 `PageBusyError` / `RecoveryBusyError` / `PageBusyState` / `RuntimeMetrics` 到 contracts.py
2. ✅ 修改 runtime/engine.py（acquire_page / metrics / 同步 evict）
3. ✅ 修改 runtime/recovery_engine.py（busy 守卫）
4. ✅ 删除 V1 providers/ 子模块 + engine/judge/consensus/conflict/comparison
5. ✅ 重命名 main_v2.py → main.py, registry_v2.py → registry.py
6. ✅ 修复 V2 源文件残留 V1 引用（manager / provider_manager / app_state）
7. ✅ 删除 V1 测试文件
8. ✅ 修复 test_smoke / test_coverage_boost 残留 V1 import
9. ✅ 修复 6 个平台 __init__.py 从 provider 改 query_adapter
10. ✅ 新增 test_stress_v2.py (50 串行 + 100 并发)
11. ✅ 新增 /metrics/runtime HTTP 端点
