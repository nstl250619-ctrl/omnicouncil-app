# 第七阶段 · 指标设计

## RuntimeMetrics 数据类

位置：`backend/engine/contracts.py`

```python
@dataclass
class RuntimeMetrics:
    platform: str
    page_created: int = 0
    page_destroyed: int = 0
    page_lease_acquired: int = 0
    page_lease_released: int = 0
    page_busy_rejections: int = 0
    recovery_started: int = 0
    recovery_succeeded: int = 0
    recovery_failed: int = 0
    recovery_aborted_busy: int = 0
    session_expired: int = 0
    query_total: int = 0
    query_succeeded: int = 0
    query_failed: int = 0
    eviction_started: int = 0
    eviction_completed: int = 0
```

## 埋点位置

| 指标 | 位置 | 触发条件 |
|---|---|---|
| `page_created` | `runtime/engine.py` `_launch_browser()` | 每次 `_page` 创建 |
| `page_destroyed` | `runtime/engine.py` `_evict_page()` | 每次 Page 关闭 |
| `page_lease_acquired` | `runtime/engine.py` `acquire_page()` | 成功 acquire |
| `page_lease_released` | `runtime/engine.py` `acquire_page()` 退出 | context manager 退出 |
| `page_busy_rejections` | `runtime/engine.py` `acquire_page()` | 三层守卫拒绝 |
| `recovery_started` | `runtime/recovery_engine.py` `recover()` 入口 | 守卫通过后 |
| `recovery_succeeded` | `runtime/recovery_engine.py` 策略成功 | 4 级策略任一成功 |
| `recovery_failed` | `runtime/recovery_engine.py` 策略失败 | 4 级策略全失败 |
| `recovery_aborted_busy` | `runtime/recovery_engine.py` 守卫超时 | Page lease 5s 内未释放 |
| `session_expired` | `runtime/engine.py` `_on_session_expired` | HealthMonitor 回调 |
| `query_total` | 调用方 `acquire_page` 内 | 每次 query |
| `query_succeeded` | 调用方 `acquire_page` 内 | query 返回成功 |
| `query_failed` | 调用方 `acquire_page` 内 | query 抛异常 |
| `eviction_started` | `runtime/engine.py` `_evict_stale_pages()` | 决定淘汰 |
| `eviction_completed` | `runtime/engine.py` `_evict_page()` | 淘汰完成 |

## HTTP 端点

**新增** `GET /metrics/runtime` — Phase 7 整改新增。

```json
{
  "platforms": {
    "deepseek": {
      "page_created": 1, "page_destroyed": 0,
      "page_lease_acquired": 50, "page_lease_released": 50,
      "page_busy_rejections": 0,
      "recovery_started": 0, "recovery_succeeded": 0,
      "recovery_failed": 0, "recovery_aborted_busy": 0,
      "session_expired": 0,
      "query_total": 50, "query_succeeded": 50, "query_failed": 0,
      "eviction_started": 0, "eviction_completed": 0
    },
    "qianwen": { ... }
  },
  "timestamp": 1749370000.123
}
```

**现有** `GET /metrics` — Prometheus 通用指标（保留）。

## 一致性不变量

| 不变量 | 验证方式 |
|---|---|
| `page_lease_acquired == page_lease_released`（无泄漏） | 压测后断言 |
| `page_busy_rejections == 0`（同步 lease 模式） | 50 串行 + 100 并发 |
| `eviction_started == eviction_completed` | 压测后断言 |
| `query_succeeded + query_failed == query_total` | 任意时刻成立 |
| `recovery_aborted_busy <= recovery_started` | Recovery 期间触发 |
