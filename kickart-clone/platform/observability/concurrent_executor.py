"""
并发执行引擎 - 高性能任务调度
基于 asyncio + 线程池，支持并行任务、进度回调、取消机制
"""
import asyncio
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable, Optional

from logger import get_logger
from metrics import active_workflows, queue_size

logger = get_logger(__name__)


class TaskState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ConcurrentTask:
    """并发任务"""
    task_id: str
    name: str
    func: Callable
    args: tuple = ()
    kwargs: dict = field(default_factory=dict)
    state: TaskState = TaskState.QUEUED
    result: any = None
    error: Optional[str] = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    progress: float = 0.0
    dependencies: list = field(default_factory=list)  # 依赖的 task_id


@dataclass
class ExecutionResult:
    """执行结果"""
    success: bool
    results: dict  # task_id -> result
    errors: dict   # task_id -> error
    total_duration: float
    task_count: int
    success_count: int
    failed_count: int


class ConcurrentExecutor:
    """
    并发执行引擎
    - 支持任务依赖图（DAG）
    - 线程池并发执行
    - 进度回调
    - 取消机制
    """

    def __init__(
        self,
        max_workers: int = 4,
        progress_callback: Optional[Callable] = None,
    ):
        self.max_workers = max_workers
        self.progress_callback = progress_callback
        self.tasks: dict[str, ConcurrentTask] = {}
        self._executor: Optional[ThreadPoolExecutor] = None

    def add_task(
        self,
        name: str,
        func: Callable,
        args: tuple = (),
        kwargs: dict = None,
        dependencies: list = None,
        task_id: str = None,
    ) -> str:
        """添加任务"""
        task_id = task_id or f"task_{uuid.uuid4().hex[:8]}"
        task = ConcurrentTask(
            task_id=task_id,
            name=name,
            func=func,
            args=args,
            kwargs=kwargs or {},
            dependencies=dependencies or [],
        )
        self.tasks[task_id] = task
        queue_size.inc()
        return task_id

    def execute(self) -> ExecutionResult:
        """
        执行所有任务（按依赖顺序，无依赖的并行）

        Returns:
            ExecutionResult
        """
        start_time = time.time()
        active_workflows.inc()

        self._executor = ThreadPoolExecutor(max_workers=self.max_workers)
        results = {}
        errors = {}
        completed = set()

        try:
            # 拓扑排序：按依赖层级执行
            while len(completed) < len(self.tasks):
                # 找出所有依赖已完成的待执行任务
                ready = [
                    t for t in self.tasks.values()
                    if t.task_id not in completed
                    and t.state == TaskState.QUEUED
                    and all(d in completed for d in t.dependencies)
                ]

                if not ready:
                    # 检查是否有死锁
                    pending = [t for t in self.tasks.values() if t.task_id not in completed]
                    if pending:
                        for t in pending:
                            t.state = TaskState.FAILED
                            t.error = "依赖无法满足（可能存在循环依赖）"
                            errors[t.task_id] = t.error
                            completed.add(t.task_id)
                    break

                # 提交本批次任务
                future_to_task = {}
                for task in ready:
                    task.state = TaskState.RUNNING
                    task.started_at = time.time()
                    queue_size.dec()
                    logger.info(f"任务启动: {task.name} ({task.task_id})")

                    future = self._executor.submit(self._run_task, task)
                    future_to_task[future] = task

                # 等待本批次完成
                for future in as_completed(future_to_task):
                    task = future_to_task[future]
                    try:
                        result = future.result()
                        task.result = result
                        task.state = TaskState.SUCCESS
                        task.completed_at = time.time()
                        results[task.task_id] = result
                        logger.info(
                            f"任务完成: {task.name} ({task.task_id}) "
                            f"耗时 {task.completed_at - task.started_at:.2f}s"
                        )
                    except Exception as e:
                        task.state = TaskState.FAILED
                        task.error = str(e)
                        task.completed_at = time.time()
                        errors[task.task_id] = str(e)
                        logger.error(
                            f"任务失败: {task.name} ({task.task_id}) 错误: {e}"
                        )
                    completed.add(task.task_id)

                    # 进度回调
                    if self.progress_callback:
                        progress = len(completed) / len(self.tasks)
                        self.progress_callback(progress, task)

        finally:
            self._executor.shutdown(wait=True)
            active_workflows.dec()

        total_duration = time.time() - start_time
        success_count = len(results)
        failed_count = len(errors)

        logger.info(
            f"并发执行完成: {success_count} 成功, {failed_count} 失败, "
            f"总耗时 {total_duration:.2f}s"
        )

        return ExecutionResult(
            success=failed_count == 0,
            results=results,
            errors=errors,
            total_duration=total_duration,
            task_count=len(self.tasks),
            success_count=success_count,
            failed_count=failed_count,
        )

    def _run_task(self, task: ConcurrentTask):
        """执行单个任务"""
        return task.func(*task.args, **task.kwargs)

    def cancel(self, task_id: str) -> bool:
        """取消任务（仅 QUEUED 状态可取消）"""
        task = self.tasks.get(task_id)
        if task and task.state == TaskState.QUEUED:
            task.state = TaskState.CANCELLED
            queue_size.dec()
            return True
        return False

    def get_status(self) -> dict:
        """获取所有任务状态"""
        return {
            "tasks": [
                {
                    "task_id": t.task_id,
                    "name": t.name,
                    "state": t.state.value,
                    "progress": t.progress,
                    "started_at": datetime.fromtimestamp(t.started_at).isoformat() if t.started_at else None,
                    "completed_at": datetime.fromtimestamp(t.completed_at).isoformat() if t.completed_at else None,
                    "error": t.error,
                }
                for t in self.tasks.values()
            ],
            "total": len(self.tasks),
            "running": sum(1 for t in self.tasks.values() if t.state == TaskState.RUNNING),
            "queued": sum(1 for t in self.tasks.values() if t.state == TaskState.QUEUED),
            "completed": sum(1 for t in self.tasks.values() if t.state in (TaskState.SUCCESS, TaskState.FAILED)),
        }


# ============ 便捷函数 ============

def run_parallel(
    tasks: list[tuple[str, Callable, tuple, dict]],
    max_workers: int = 4,
    progress_callback: Callable = None,
) -> ExecutionResult:
    """
    并行执行多个独立任务

    Args:
        tasks: [(name, func, args, kwargs), ...]
        max_workers: 最大并发数
        progress_callback: 进度回调

    Returns:
        ExecutionResult
    """
    executor = ConcurrentExecutor(max_workers=max_workers, progress_callback=progress_callback)
    for name, func, args, kwargs in tasks:
        executor.add_task(name=name, func=func, args=args, kwargs=kwargs)
    return executor.execute()


def run_pipeline(
    stages: list[tuple[str, Callable, tuple, dict]],
    max_workers: int = 4,
) -> ExecutionResult:
    """
    流水线执行（每个 stage 依赖前一个）

    Args:
        stages: [(name, func, args, kwargs), ...]
        max_workers: 最大并发数（流水线通常为 1）

    Returns:
        ExecutionResult
    """
    executor = ConcurrentExecutor(max_workers=max_workers)
    prev_id = None
    for name, func, args, kwargs in stages:
        deps = [prev_id] if prev_id else []
        task_id = executor.add_task(
            name=name, func=func, args=args, kwargs=kwargs, dependencies=deps
        )
        prev_id = task_id
    return executor.execute()
