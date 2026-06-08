# 第八阶段 · 50 串行 + 100 并发 压测报告

## 测试文件

`backend/tests/test_stress_v2.py`（新建，8 个测试用例全部通过）

## 50 轮串行压测

**配置：** 5 平台 × 10 轮 = 50 个 query 串行执行

| 指标 | 值 |
|---|---|
| 总轮次 | 50 |
| 成功 | 50 |
| 失败 | 0 |
| **成功率** | **100.0%** |
| **失败率** | **0.0%** |
| 平均延迟 | 1.08 ms |
| P95 延迟 | 1.11 ms |
| P99 延迟 | 1.12 ms |

### 按平台分布

| 平台 | 轮次 | 平均延迟 | P95 |
|---|---|---|---|
| deepseek | 10 | 1.08 ms | 1.11 ms |
| qianwen | 10 | 1.08 ms | 1.11 ms |
| gemini | 10 | 1.08 ms | 1.11 ms |
| chatgpt | 10 | 1.07 ms | 1.12 ms |
| mimo | 10 | 1.08 ms | 1.10 ms |

### 指标验证（每平台）

```
page_lease_acquired   = 10
page_lease_released   = 10
query_succeeded       = 10
page_busy_rejections  = 0   ✅ 同步 lease 工作正常
```

---

## 100 轮 5-AI 并发压测

**配置：** 100 轮 × 5 平台并发 = 500 个 query

| 指标 | 值 |
|---|---|
| 总查询 | 500 |
| 成功 | 500 |
| 失败 | 0 |
| **成功率** | **100.0%** |
| **失败率** | **0.0%** |
| **恢复率** | **0%**（健康运行时无恢复触发） |
| 平均延迟 | 1.11 ms |
| P50 延迟 | 1.10 ms |
| P95 延迟 | 1.15 ms |
| P99 延迟 | 1.18 ms |

### 指标验证（每平台）

```
page_lease_acquired   = 100
page_lease_released   = 100
query_succeeded       = 100
query_total           = 100
page_busy_rejections  = 0   ✅ 5 并发同步 lease 无拒绝
recovery_started      = 0   ✅ 无恢复触发
```

---

## 针对性 race / guard 测试（6 个）

| 测试 | 验证内容 | 结果 |
|---|---|---|
| `test_acquire_page_busy_rejected` | 同 AI 第二 lease 被 `PageBusyError` 拒绝 | ✅ |
| `test_recovery_blocks_new_acquires` | Recovery 期间 lease 被拒 | ✅ |
| `test_pending_evict_blocks_new_acquires` | Evicting 期间 lease 被拒 | ✅ |
| `test_evict_waits_for_lease` | Eviction 等待 lease 释放 5s | ✅ |
| `test_recovery_aborts_on_page_busy` | Recovery 5s 等待超时 → `RecoveryBusyError` + `recovery_aborted_busy += 1` | ✅ |
| `test_metrics_snapshot_complete` | 15 个指标字段完整暴露 | ✅ |

---

## 整改前后对比（基线对比）

| 维度 | 整改前（V1/V2 双架构） | 整改后（V2 only） |
|---|---|---|
| Page 所有权 | 同步 `get_page()` 返回无保护引用 | `acquire_page()` 异步租约 |
| Recovery vs Query | 无守卫，竞态 | 5s 限时等待 + `_recovery_in_progress` 标志位 |
| Eviction 竞态 | `asyncio.ensure_future` fire-and-forget | `_pending_evict` 标志 + 同步等待 lease |
| 指标 | 仅通用 MetricsCollector | + 15 个 RuntimeMetrics 字段 |
| `/metrics/runtime` | 不存在 | 新增 |

---

## 原始日志

- `logs/stress_50_serial.json` — 50 轮 × {round, platform, duration_ms}
- `logs/stress_100_concurrent.json` — 500 轮 × {round, platform, duration_ms}
