文件：
backend/engine/layers/layer2_scheduler/scheduler_center.py

修改原因
SchedulerCenter._tasks 和 _cancel_events 字典在任务完成后永不清理。cleanup_old_tasks() 方法存在但从未被调用，导致长时间运行后 OOM。需要在任务执行完成的 finally 块中添加清理调用。

修改前代码
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

修改后代码
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

关键差异说明
在 finally 块的 self._cancel_events.pop(task_id, None) 之后，新增一行 self.cleanup_old_tasks()。

cleanup_old_tasks() 的已有逻辑：
1. 遍历 self._tasks，找出状态为 COMPLETED/FAILED/CANCELLED 且 updated_at 距今超过 3600 秒的任务，删除
2. 若清理后总数仍超过 self._max_stored_tasks(1000)，按 updated_at 排序淘汰最旧的任务
3. 同步清理 self._cancel_events 中对应的 key
4. 返回清理的任务数量

变更量：+1 行。不修改任何现有逻辑，仅在 finally 块末尾添加一个方法调用。
