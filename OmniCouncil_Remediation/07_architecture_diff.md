# 第九阶段 · 整改前后架构图

## 整改前（V1+V2 双架构并存）

```
┌─────────────────────────────────────────────────────────────────┐
│                    Tauri Desktop Shell                          │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                  React + Vite Frontend                    │  │
│  │   ConsolePage / PlatformSetupPage / AIIconSelector       │  │
│  │   Zustand stores / useWebSocket hook                     │  │
│  └────────────────────┬──────────────────────────────────────┘  │
└───────────────────────┼──────────────────────────────────────────┘
                        │ Tauri 启动 main.py
                        ▼
┌─────────────────────────────────────────────────────────────────┐
│             backend/main.py  (V1 入口, 已被删除)                │
│                                                                 │
│   ├─ providers/runtime.py      (V1 ProviderRuntime OS)          │
│   │    ├─ registry.py           (V1)                            │
│   │    ├─ session_manager.py    (V1)                            │
│   │    ├─ health_monitor.py     (V1)                            │
│   │    └─ event_bus.py          (V1)                            │
│   │                                                             │
│   ├─ providers/base/provider.py (V1 BaseProvider)              │
│   ├─ providers/registry/registry.py (V1)                       │
│   │                                                             │
│   ├─ engine/judge/             (V1 占位)  ← 全删               │
│   ├─ engine/consensus/         (V1)        ← 全删               │
│   ├─ engine/conflict/          (V1)        ← 全删               │
│   ├─ engine/comparison/        (V1)        ← 全删               │
│   │                                                             │
│   ├─ engine/layers/layer1_ai_access/  (V2, 残留 V1 风格)       │
│   │    └─ adapters/{deepseek,qianwen,gemini,chatgpt,claude}_browser.py
│   │                                                             │
│   ├─ runtime/engine.py         (V2 AIRuntimeEngine, 含 V1 风格  │
│   │                              get_page / asyncio.ensure_future 残留)
│   │                                                             │
│   └─ browser/embedded_engine.py (V1 风格 get_page/evict)      │
│                                                                 │
│   ⚠️  main_v2.py  (V2 入口, 存在但 Tauri 未加载)               │
│       └─ RuntimeRegistry + QueryAdapter × 5                    │
└─────────────────────────────────────────────────────────────────┘
```

**问题：**
- Tauri 启动 V1 `main.py`，V2 入口闲置
- 6 处 V1 旧模块与 V2 并存
- `get_page()` 在 `embedded_engine.py` 与 `runtime/engine.py` 各一份
- 5 平台 × 2 实现 (provider.py + query_adapter.py)
- 4 个 engine 子包占位未使用

---

## 整改后（V2 唯一架构）

```
┌─────────────────────────────────────────────────────────────────┐
│                    Tauri Desktop Shell                          │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                  React + Vite Frontend                    │  │
│  │   ConsolePage / PlatformSetupPage / AIIconSelector       │  │
│  │   Zustand stores / useWebSocket hook                     │  │
│  └────────────────────┬──────────────────────────────────────┘  │
└───────────────────────┼──────────────────────────────────────────┘
                        │ Tauri 启动 main.py (V2 内容)
                        ▼
┌─────────────────────────────────────────────────────────────────┐
│             backend/main.py  (V2 唯一入口)                      │
│                                                                 │
│   ├─ RuntimeRegistry                                            │
│   │    └─ AIRuntimeEngine × 5   (deepseek/qianwen/gemini/        │
│   │                              chatgpt/mimo)                   │
│   │         ├─ StateMachine   (10 态)                           │
│   │         ├─ ProfileManager (profile 备份/恢复)                │
│   │         ├─ SessionValidator (offline + online)              │
│   │         ├─ HealthMonitor   (60s heartbeat)                   │
│   │         └─ RecoveryEngine  (4 级策略链 + PageBusy 守卫)     │
│   │                                                             │
│   │   ┌── Page Lease (Phase 3) ─────────────────┐              │
│   │   │  acquire_page() 异步上下文管理器          │              │
│   │   │  - _lease_lock: asyncio.Lock             │              │
│   │   │  - _recovery_in_progress: bool            │              │
│   │   │  - _pending_evict: bool                   │              │
│   │   │  - _query_ref_count: int                  │              │
│   │   │  - _page_state: PageBusyState enum        │              │
│   │   └────────────────────────────────────────────┘              │
│   │                                                             │
│   ├─ SchedulerCenter → QueryAdapter × 5                          │
│   │    └─ BaseQueryAdapter.execute(page, prompt, options)       │
│   │       (page 来自 engine.acquire_page() 上下文)               │
│   │                                                             │
│   ├─ Browser: EmbeddedEngine / CDPEngine                         │
│   │    - 同步化 _evict_page (Phase 5)                            │
│   │    - 等待 lease 释放后再 close page                          │
│   │                                                             │
│   └─ RuntimeMetrics (Phase 7)                                   │
│        - 15 个计数器埋点                                         │
│        - /metrics/runtime HTTP 端点暴露                          │
└─────────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│       backend/packages/  (5 个独立 pip package)                 │
│                                                                 │
│   ├─ omnicounci1l-core            (共享类型/配置/异常)           │
│   ├─ comparison-engine            (6 阶段比较管道)               │
│   ├─ consensus-engine             (共识挖掘 / 异议分析)         │
│   ├─ conflict-engine              (冲突根因分析)                 │
│   └─ judge-engine                 (可选外部 AI 评判)             │
└─────────────────────────────────────────────────────────────────┘
```

**改进：**
- ✅ Tauri 启动 V2 入口（无 V1 残留）
- ✅ 唯一 `RuntimeRegistry` + `AIRuntimeEngine × 5`
- ✅ 唯一 `BaseQueryAdapter` 接口（5 平台）
- ✅ 唯一 `EmbeddedEngine` 浏览器（V1 风格已改造）
- ✅ Page Lease 显式所有权（acquire/release）
- ✅ Recovery 守卫（5s 限时 + abort）
- ✅ Eviction 同步化（_pending_evict 标志 + 同步 wait）
- ✅ 15 个 RuntimeMetrics 计数器
- ✅ 5 个独立 package，pip 可单独安装
