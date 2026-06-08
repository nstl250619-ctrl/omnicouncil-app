# 第一阶段 · 最终保留架构决策

## 决策：**保留 V2，删除 V1**

**理由：**

1. **V2 是当前生产路径**：CHANGELOG.md v2.0.0 段已确认 V2 入口 (`main_v2.py`) 是新架构方向，包含 Runtime Engine + Query Engine + 5 个独立 package。
2. **V1 与 V2 双架构并存带来 6 类竞态/重复**：get_page() 在 embedded_engine.py 与 runtime/engine.py 各一份；ProviderRuntime 与 AIRuntimeEngine 职责重叠；registry.py 与 registry_v2.py 命名重复。
3. **历史审计（V2 报告 ARCHITECTURE_AUDIT_V2.md）已建议 V1 下线**：综合评分 4.6/10，主要扣分项均为"双架构并存"。
4. **V2 已具备 V1 全部功能**：5 平台 QueryAdapter 覆盖 V1 5 平台 Provider；AIRuntimeEngine 10 态状态机覆盖 V1 state_machine；SessionValidator 覆盖 V1 session_manager；HealthMonitor 覆盖 V1 health_monitor；recovery_strategies 4 级策略链覆盖 V1 recovery_engine。

## V1 终态

- **入口** `main.py` 被删除
- **Provider 子系统** `providers/runtime.py` / `session_manager.py` / `health_monitor.py` / `event_bus.py` / `errors.py` / `vision_fallback.py` / `base/provider.py` 被删除
- **Registry 子系统** `providers/registry/` 目录被删除，`registry_v2.py` 升级为 `providers/registry.py`
- **Engine 子系统** `engine/judge/` / `engine/consensus/` / `engine/conflict/` / `engine/comparison/` 被删除（V2 已有独立 package）

## V2 终态

- **入口** `main.py` (来自原 main_v2.py)
- **Runtime 引擎** `backend/runtime/` 6 个文件
- **Query 引擎** `backend/providers/<platform>/query_adapter.py` × 5
- **5 个独立 package** `backend/packages/{omnicounci1l-core, comparison-engine, conflict-engine, consensus-engine, judge-engine}`
- **Contract 层** `backend/engine/contracts.py`
- **3 个 Layer** `engine/layers/{layer1_ai_access, layer2_scheduler, layer3_collector}`

## 禁止条款

- **禁止长期双架构并存** — 任何 commit 不得重新引入 V1 模块
- **禁止新增 V1 风格的 `get_page()` 同步返回** — 必须使用 `acquire_page()` 异步上下文管理器
- **禁止 `asyncio.ensure_future(self._evict_page())`** — 同步化或 `await` task
