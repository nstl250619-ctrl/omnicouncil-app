P0问题编号
P0-1

风险等级
P0

问题描述
SchedulerCenter._tasks 和 SchedulerCenter._cancel_events 字典在任务完成后永不清理。cleanup_old_tasks() 方法已存在（line 277），具备清理能力（移除超过 3600 秒的已完成任务，强制执行 1000 条上限），但该方法在整个代码库中从未被调用。长时间运行后 dict 无限增长，最终导致 OOM。

根因分析
SchedulerCenter.__init__() 创建了两个 dict：
- self._tasks: dict[str, TaskStatusInfo] = {}
- self._cancel_events: dict[str, asyncio.Event] = {}

任务执行流程 _execute_task_safe() 的 finally 块只清理了单个任务的 cancel_event：
```python
finally:
    self._cancel_events.pop(task_id, None)
```
但从未调用 cleanup_old_tasks() 对 _tasks 进行全局清理。cleanup_old_tasks() 方法本身逻辑正确（已验证），问题仅在于无调用入口。

涉及模块
engine/layers/layer2_scheduler

涉及文件
backend/engine/layers/layer2_scheduler/scheduler_center.py

修改文件列表
backend/engine/layers/layer2_scheduler/scheduler_center.py — 1 行新增

修改内容详情
在 _execute_task_safe() 方法的 finally 块末尾添加 self.cleanup_old_tasks() 调用。每个后台任务完成/失败/异常退出后自动触发全局清理。

修改前逻辑
```python
async def _execute_task_safe(self, task_id: str, query: str, ai_ids: list[str]) -> None:
    """Wrapper that catches unhandled exceptions in background tasks."""
    try:
        await self._execute_task(task_id, query, ai_ids)
    except Exception:
        logger.exception("Unhandled error in task %s", task_id)
        if task_id in self._tasks and self._tasks[task_id].status not in (
            TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED
        ):
            self._tasks[task_id] = TaskStatusInfo(
                task_id=task_id,
                status=TaskStatus.FAILED,
                progress=self._tasks[task_id].progress,
                created_at=self._tasks[task_id].created_at,
                updated_at=time.time(),
            )
    finally:
        self._cancel_events.pop(task_id, None)
```
_tasks 永不清理，cancel_events 只清理当前任务。

修改后逻辑
```python
async def _execute_task_safe(self, task_id: str, query: str, ai_ids: list[str]) -> None:
    """Wrapper that catches unhandled exceptions in background tasks."""
    try:
        await self._execute_task(task_id, query, ai_ids)
    except Exception:
        logger.exception("Unhandled error in task %s", task_id)
        if task_id in self._tasks and self._tasks[task_id].status not in (
            TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED
        ):
            self._tasks[task_id] = TaskStatusInfo(
                task_id=task_id,
                status=TaskStatus.FAILED,
                progress=self._tasks[task_id].progress,
                created_at=self._tasks[task_id].created_at,
                updated_at=time.time(),
            )
    finally:
        self._cancel_events.pop(task_id, None)
        self.cleanup_old_tasks()
```
每个后台任务退出时触发全局清理。cleanup_old_tasks() 会：1) 移除超过 3600 秒的已完成/失败/取消任务；2) 若总数超过 _max_stored_tasks(1000)，按 updated_at 淘汰最旧的任务。

潜在影响分析
- 功能影响：无。cleanup_old_tasks() 只清理 COMPLETED/FAILED/CANCELLED 状态的任务，不影响 RUNNING/CREATED/DISPATCHED 状态的任务。
- 性能影响：极低。遍历 dict + 时间比较，O(n) 但 n <= 1000。仅在任务完成时触发，不在热路径上。
- 并发安全：安全。_execute_task_safe 在 asyncio 单线程事件循环中运行，cleanup_old_tasks() 是同步方法，无竞态条件。
- 边界情况：如果清理时恰好有任务正在被 get_task_status() 查询，由于 Python dict 操作的原子性，不会产生中间状态。
- 副作用：无。cleanup_old_tasks() 不发射事件，不修改业务状态。

回归验证步骤
1. 验证 cleanup_old_tasks() 逻辑：创建 1050 个已完成任务，调用 cleanup_old_tasks()，确认清理至 <=1000
2. 验证 _execute_task_safe 的 finally 块：确认 cleanup_old_tasks() 被调用
3. 运行现有 smoke 测试：python -m pytest tests/test_smoke.py -v
4. 运行现有 integration 测试：python -m pytest tests/test_integration.py -v

回归验证结果
1. cleanup_old_tasks() 验证：创建 1050 个已完成任务 → 调用 cleanup → 清理至 0 条（所有任务超过 3600 秒）→ PASS
2. _execute_task_safe finally 块：确认 line 152 存在 self.cleanup_old_tasks() 调用 → PASS
3. smoke 测试：16/16 passed in 0.23s → PASS
4. integration 测试：依赖外部浏览器，跳过 → N/A

PASS
