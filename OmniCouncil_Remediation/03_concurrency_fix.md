# 第三~五阶段 · 并发修复细节

## 阶段 3：Page Lease

### 修复前（V1 风格）
```python
def get_page(self) -> Any:
    if self.state != RuntimeState.READY:
        raise RuntimeNotReadyError(self.state)
    if self._page is None or self._page.is_closed():
        raise RuntimeNotReadyError(self.state)
    self._page_last_used = time.time()
    return self._page
```

**问题：** 同步返回 Page，调用方持 Page 期间可被其他协程 / 事件循环另一拍淘汰。

### 修复后（V2 Page Lease）
```python
@contextlib.asynccontextmanager
async def acquire_page(self, *, timeout: float = 30.0):
    if self._recovery_in_progress:
        self._metrics.page_busy_rejections += 1
        raise PageBusyError(self._platform, "runtime is under recovery")
    if self._pending_evict:
        self._metrics.page_busy_rejections += 1
        raise PageBusyError(self._platform, "page is being evicted")
    if self.state != RuntimeState.READY:
        self._metrics.page_busy_rejections += 1
        raise RuntimeNotReadyError(self.state)
    try:
        await asyncio.wait_for(self._lease_lock.acquire(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        self._metrics.page_busy_rejections += 1
        raise PageBusyError(self._platform, f"lease acquisition timed out after {timeout:.1f}s") from exc
    self._query_ref_count += 1
    self._metrics.page_lease_acquired += 1
    self._page_state = PageBusyState.LEASED
    try:
        yield self._page
    finally:
        self._query_ref_count = max(0, self._query_ref_count - 1)
        self._metrics.page_lease_released += 1
        if self._lease_lock.locked():
            self._lease_lock.release()
```

**三层守卫：**
1. `_recovery_in_progress` — Recovery 期间拒绝新 lease
2. `_pending_evict` — 淘汰进行时拒绝新 lease
3. state != READY — 状态机保护
4. `asyncio.wait_for(lock, timeout)` — 限时等待

---

## 阶段 4：Recovery Busy 守卫

### 修复前
`RecoveryEngine.recover()` 直接开始状态机转换，无 Page 状态检查。

### 修复后
```python
# === Phase 4 guard: page must not be leased by a query ===
page_busy_timeout_s = 5.0
deadline = time.time() + page_busy_timeout_s
while (
    getattr(engine, "_lease_lock", None) is not None
    and engine._lease_lock.locked()
    and time.time() < deadline
):
    await asyncio.sleep(0.05)
if engine._lease_lock.locked():
    # Page still busy — abort this recovery round
    engine._metrics.recovery_aborted_busy += 1
    engine._metrics.recovery_failed += 1
    raise RecoveryBusyError(platform, waited_ms)

# Mark recovery in progress to block new acquire_page() calls
engine._recovery_in_progress = True
engine._metrics.recovery_started += 1
```

**机制：**
- 5 秒限时等待 Page 释放
- 超时则 `RecoveryBusyError` + `recovery_aborted_busy += 1`
- 设置 `_recovery_in_progress = True` 阻断新 lease
- 成功/失败/异常都重置 `_recovery_in_progress = False`

---

## 阶段 5：异步淘汰竞态

### 修复前（V1 风格 — embedded_engine.py 第 220 行）
```python
def _evict_stale_pages(self, max_age: float = 600, max_idle: float = 120) -> int:
    if self._page is None:
        return 0
    now = time.time()
    age = now - self._page_created_at
    idle = now - self._page_last_used
    if age > max_age or (idle > max_idle and self._page_last_used > 0):
        asyncio.ensure_future(self._evict_page(ai_id))  # ⚠️ fire-and-forget
        return 1
```

**问题：** `asyncio.ensure_future` 不等待，`get_page()` 立即返回 Page，下一拍 Page 被 close。

### 修复后（V2 runtime/engine.py）
```python
def _evict_stale_pages(self) -> int:
    if self._page is None:
        return 0
    now = time.time()
    age = now - self._page_created_at
    idle = now - self._page_last_used
    if age > _MAX_PAGE_AGE_S or (idle > _MAX_PAGE_IDLE_S and self._page_last_used > 0):
        self._pending_evict = True                # ⚠️ 标记，acquire_page 拒绝
        self._page_state = PageBusyState.EVICTING
        self._metrics.eviction_started += 1
        if self._evict_task is None or self._evict_task.done():
            self._evict_task = asyncio.create_task(self._evict_page())
        return 1
    return 0

async def _evict_page(self) -> None:
    try:
        if self._lease_lock.locked():
            deadline = time.time() + 5.0
            while self._lease_lock.locked() and time.time() < deadline:
                await asyncio.sleep(0.05)         # ⚠️ 同步等待 lease 释放
        if self._page is not None:
            with contextlib.suppress(Exception):
                await self._page.close()
            self._page = None
        self._metrics.page_destroyed += 1
        self._metrics.eviction_completed += 1
    finally:
        self._pending_evict = False
```

**机制：**
- 淘汰前先 `_pending_evict = True` — `acquire_page()` 立即拒绝
- `_evict_page()` 内同步等待 lease 释放（5s 上限）
- 用 `asyncio.create_task` 替代 `ensure_future`，保留 task 句柄
- `acquire_page()` 通过 `_pending_evict` 守卫，绝不返回即将淘汰的 Page

---

## 测试覆盖

`backend/tests/test_stress_v2.py` 中 8 个针对性测试全部通过：

1. `test_acquire_page_busy_rejected` — 同 AI 第二 lease 被拒
2. `test_recovery_blocks_new_acquires` — Recovery 期间 lease 被拒
3. `test_pending_evict_blocks_new_acquires` — 淘汰期间 lease 被拒
4. `test_evict_waits_for_lease` — Eviction 等待 lease 释放
5. `test_recovery_aborts_on_page_busy` — Recovery 5s 等待超时后 abort
6. `test_metrics_snapshot_complete` — 15 个指标字段完整
7. `test_stress_50_serial` — 5 平台 × 10 轮 = 50 query 100% 成功
8. `test_stress_100_concurrent` — 100 轮 × 5 平台并发 = 500 query 100% 成功
