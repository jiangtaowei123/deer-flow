"""
异步任务队列 - 生产级任务调度
基于 Redis（优先）或内存队列（回退），支持优先级、重试、超时
"""
import json
import os
import sys
import threading
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

# 添加 observability 路径
_OBS_PATH = Path(__file__).parent.parent / "platform" / "observability"
if str(_OBS_PATH) not in sys.path:
    sys.path.insert(0, str(_OBS_PATH))

from logger import get_logger

logger = get_logger(__name__)


class TaskPriority(int, Enum):
    """任务优先级"""
    LOW = 1
    NORMAL = 5
    HIGH = 10
    URGENT = 20


class QueueTaskState(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"
    RETRYING = "retrying"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass(order=True)
class QueueTask:
    """队列任务"""
    priority: int = field(default=TaskPriority.NORMAL)
    task_id: str = field(default_factory=lambda: f"q_{uuid.uuid4().hex[:12]}")
    name: str = ""
    func_name: str = ""
    args: tuple = ()
    kwargs: dict = field(default_factory=dict)
    state: QueueTaskState = QueueTaskState.QUEUED
    result: any = None
    error: Optional[str] = None
    retries: int = 0
    max_retries: int = 3
    timeout_sec: int = 300
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    tenant_id: str = "default"
    metadata: dict = field(default_factory=dict)


# ============ 存储后端 ============

class MemoryBackend:
    """内存队列后端（回退方案）"""

    def __init__(self):
        self._queues: dict[str, deque] = defaultdict(deque)
        self._tasks: dict[str, QueueTask] = {}
        self._results: dict[str, dict] = {}
        self._lock = threading.Lock()

    def enqueue(self, queue_name: str, task: QueueTask):
        with self._lock:
            self._tasks[task.task_id] = task
            self._queues[queue_name].append(task)

    def dequeue(self, queue_name: str, timeout: float = 1.0) -> Optional[QueueTask]:
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                if self._queues[queue_name]:
                    return self._queues[queue_name].popleft()
            time.sleep(0.05)
        return None

    def get_task(self, task_id: str) -> Optional[QueueTask]:
        with self._lock:
            return self._tasks.get(task_id)

    def update_task(self, task_id: str, **kwargs):
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                for k, v in kwargs.items():
                    setattr(task, k, v)

    def save_result(self, task_id: str, result: dict):
        with self._lock:
            self._results[task_id] = result

    def get_result(self, task_id: str) -> Optional[dict]:
        with self._lock:
            return self._results.get(task_id)

    def list_tasks(self, queue_name: str = None) -> list:
        with self._lock:
            tasks = list(self._tasks.values())
            if queue_name:
                # 内存后端不区分队列
                pass
            return tasks

    def queue_size(self, queue_name: str) -> int:
        with self._lock:
            return len(self._queues[queue_name])


class RedisBackend:
    """Redis 队列后端（生产推荐）"""

    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        import redis
        self.redis = redis.from_url(redis_url, decode_responses=True)
        self.redis.ping()  # 测试连接
        logger.info(f"Redis 队列后端已连接: {redis_url}")

    def _task_key(self, task_id: str) -> str:
        return f"kickart:task:{task_id}"

    def _queue_key(self, queue_name: str) -> str:
        return f"kickart:queue:{queue_name}"

    def _result_key(self, task_id: str) -> str:
        return f"kickart:result:{task_id}"

    def enqueue(self, queue_name: str, task: QueueTask):
        task_data = self._serialize_task(task)
        self.redis.hset(self._task_key(task.task_id), mapping=task_data)
        # 使用 sorted set 实现优先级队列
        self.redis.zadd(self._queue_key(queue_name), {task.task_id: -task.priority})

    def dequeue(self, queue_name: str, timeout: float = 1.0) -> Optional[QueueTask]:
        # BRPOP 不支持 sorted set，使用 ZPOPMIN
        result = self.redis.bzpopmin(self._queue_key(queue_name), timeout=int(timeout))
        if result:
            _, task_id, _ = result
            task_data = self.redis.hgetall(self._task_key(task_id))
            return self._deserialize_task(task_data)
        return None

    def get_task(self, task_id: str) -> Optional[QueueTask]:
        task_data = self.redis.hgetall(self._task_key(task_id))
        if task_data:
            return self._deserialize_task(task_data)
        return None

    def update_task(self, task_id: str, **kwargs):
        task_data = self._serialize_task(QueueTask(task_id=task_id, **{k: v for k, v in kwargs.items() if k in QueueTask.__dataclass_fields__}))
        self.redis.hset(self._task_key(task_id), mapping=task_data)

    def save_result(self, task_id: str, result: dict):
        self.redis.set(self._result_key(task_id), json.dumps(result, default=str))

    def get_result(self, task_id: str) -> Optional[dict]:
        data = self.redis.get(self._result_key(task_id))
        return json.loads(data) if data else None

    def list_tasks(self, queue_name: str = None) -> list:
        if queue_name:
            task_ids = self.redis.zrange(self._queue_key(queue_name), 0, -1)
        else:
            task_ids = self.redis.keys("kickart:task:*")
        tasks = []
        for tid in task_ids:
            tid = tid.replace("kickart:task:", "") if isinstance(tid, str) else tid
            task_data = self.redis.hgetall(self._task_key(tid))
            if task_data:
                tasks.append(self._deserialize_task(task_data))
        return tasks

    def queue_size(self, queue_name: str) -> int:
        return self.redis.zcard(self._queue_key(queue_name))

    def _serialize_task(self, task: QueueTask) -> dict:
        return {
            "task_id": task.task_id,
            "name": task.name,
            "func_name": task.func_name,
            "args": json.dumps(task.args, default=str),
            "kwargs": json.dumps(task.kwargs, default=str),
            "state": task.state.value,
            "retries": str(task.retries),
            "max_retries": str(task.max_retries),
            "timeout_sec": str(task.timeout_sec),
            "created_at": str(task.created_at),
            "started_at": str(task.started_at or ""),
            "completed_at": str(task.completed_at or ""),
            "tenant_id": task.tenant_id,
            "priority": str(task.priority),
        }

    def _deserialize_task(self, data: dict) -> QueueTask:
        return QueueTask(
            task_id=data.get("task_id", ""),
            name=data.get("name", ""),
            func_name=data.get("func_name", ""),
            args=json.loads(data.get("args", "[]")),
            kwargs=json.loads(data.get("kwargs", "{}")),
            state=QueueTaskState(data.get("state", "queued")),
            retries=int(data.get("retries", 0)),
            max_retries=int(data.get("max_retries", 3)),
            timeout_sec=int(data.get("timeout_sec", 300)),
            created_at=float(data.get("created_at", 0)),
            started_at=float(data["started_at"]) if data.get("started_at") else None,
            completed_at=float(data["completed_at"]) if data.get("completed_at") else None,
            tenant_id=data.get("tenant_id", "default"),
            priority=int(data.get("priority", 5)),
        )


# ============ 任务队列 ============

class TaskQueue:
    """
    异步任务队列
    - 优先级调度
    - 自动重试
    - 超时处理
    - 多 worker 并发
    """

    def __init__(
        self,
        backend: str = "auto",
        redis_url: str = "redis://localhost:6379/0",
        queue_name: str = "default",
    ):
        self.queue_name = queue_name
        self._func_registry: dict[str, Callable] = {}

        # 选择后端
        if backend == "redis" or (backend == "auto" and self._redis_available(redis_url)):
            try:
                self.backend = RedisBackend(redis_url)
                logger.info("使用 Redis 后端")
            except Exception as e:
                logger.warning(f"Redis 连接失败，回退到内存: {e}")
                self.backend = MemoryBackend()
        else:
            self.backend = MemoryBackend()
            logger.info("使用内存后端")

        self._workers: list[threading.Thread] = []
        self._running = False

    def _redis_available(self, url: str) -> bool:
        try:
            import redis
            r = redis.from_url(url, decode_responses=True)
            r.ping()
            return True
        except Exception:
            return False

    # ============ 任务注册 ============

    def register_func(self, name: str, func: Callable):
        """注册可调用的函数"""
        self._func_registry[name] = func
        logger.info(f"注册任务函数: {name}")

    # ============ 任务提交 ============

    def submit(
        self,
        func_name: str,
        args: tuple = (),
        kwargs: dict = None,
        name: str = "",
        priority: TaskPriority = TaskPriority.NORMAL,
        max_retries: int = 3,
        timeout_sec: int = 300,
        tenant_id: str = "default",
    ) -> str:
        """提交任务到队列"""
        task = QueueTask(
            name=name or func_name,
            func_name=func_name,
            args=args,
            kwargs=kwargs or {},
            priority=priority,
            max_retries=max_retries,
            timeout_sec=timeout_sec,
            tenant_id=tenant_id,
        )
        self.backend.enqueue(self.queue_name, task)
        logger.info(f"任务已提交: {task.task_id} ({func_name}), 优先级={priority}")
        return task.task_id

    # ============ 任务查询 ============

    def get_task(self, task_id: str) -> Optional[QueueTask]:
        return self.backend.get_task(task_id)

    def get_result(self, task_id: str) -> Optional[dict]:
        return self.backend.get_result(task_id)

    def list_tasks(self) -> list:
        return self.backend.list_tasks(self.queue_name)

    def queue_size(self) -> int:
        return self.backend.queue_size(self.queue_name)

    # ============ Worker ============

    def start_workers(self, num_workers: int = 2):
        """启动 worker 线程"""
        self._running = True
        for i in range(num_workers):
            worker = threading.Thread(
                target=self._worker_loop,
                args=(i,),
                daemon=True,
                name=f"queue-worker-{i}",
            )
            worker.start()
            self._workers.append(worker)
        logger.info(f"启动 {num_workers} 个 worker")

    def stop_workers(self):
        """停止 worker"""
        self._running = False
        for w in self._workers:
            w.join(timeout=5)
        self._workers.clear()
        logger.info("所有 worker 已停止")

    def _worker_loop(self, worker_id: int):
        """worker 主循环"""
        logger.info(f"Worker-{worker_id} 启动")
        while self._running:
            try:
                task = self.backend.dequeue(self.queue_name, timeout=1.0)
                if task is None:
                    continue
                self._process_task(task, worker_id)
            except Exception as e:
                logger.error(f"Worker-{worker_id} 异常: {e}", exc_info=True)
        logger.info(f"Worker-{worker_id} 退出")

    def _process_task(self, task: QueueTask, worker_id: int):
        """处理单个任务"""
        logger.info(f"Worker-{worker_id} 处理任务: {task.task_id} ({task.func_name})")

        self.backend.update_task(
            task.task_id,
            state=QueueTaskState.PROCESSING,
            started_at=time.time(),
        )

        func = self._func_registry.get(task.func_name)
        if not func:
            self._fail_task(task, f"未注册的函数: {task.func_name}")
            return

        try:
            # 使用线程池实现超时
            result = self._execute_with_timeout(func, task)

            self.backend.update_task(
                task.task_id,
                state=QueueTaskState.SUCCESS,
                completed_at=time.time(),
            )
            self.backend.save_result(task.task_id, {
                "success": True,
                "result": result,
                "task_id": task.task_id,
            })
            duration = time.time() - (task.started_at or time.time())
            logger.info(f"任务完成: {task.task_id}, 耗时 {duration:.2f}s")

        except TimeoutError:
            self._handle_retry(task, f"任务超时 ({task.timeout_sec}s)", worker_id)
        except Exception as e:
            self._handle_retry(task, str(e), worker_id)

    def _execute_with_timeout(self, func: Callable, task: QueueTask):
        """带超时执行"""
        result_container = [None]
        exception_container = [None]

        def target():
            try:
                result_container[0] = func(*task.args, **task.kwargs)
            except Exception as e:
                exception_container[0] = e

        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        thread.join(timeout=task.timeout_sec)

        if thread.is_alive():
            raise TimeoutError(f"任务执行超时 ({task.timeout_sec}s)")
        if exception_container[0]:
            raise exception_container[0]
        return result_container[0]

    def _handle_retry(self, task: QueueTask, error: str, worker_id: int):
        """处理重试"""
        task.retries += 1
        if task.retries <= task.max_retries:
            logger.warning(
                f"任务重试 {task.retries}/{task.max_retries}: {task.task_id}, 错误: {error}"
            )
            self.backend.update_task(
                task.task_id,
                state=QueueTaskState.RETRYING,
                retries=task.retries,
                error=error,
            )
            # 重新入队（延迟）
            time.sleep(1 * task.retries)
            self.backend.enqueue(self.queue_name, task)
        else:
            self._fail_task(task, f"重试 {task.max_retries} 次后失败: {error}")

    def _fail_task(self, task: QueueTask, error: str):
        """标记任务失败"""
        self.backend.update_task(
            task.task_id,
            state=QueueTaskState.FAILED,
            error=error,
            completed_at=time.time(),
        )
        self.backend.save_result(task.task_id, {
            "success": False,
            "error": error,
            "task_id": task.task_id,
        })
        logger.error(f"任务失败: {task.task_id}, 错误: {error}")


# ============ 全局队列单例 ============

_global_queue: Optional[TaskQueue] = None


def get_task_queue(redis_url: str = None) -> TaskQueue:
    """获取全局任务队列"""
    global _global_queue
    if _global_queue is None:
        _global_queue = TaskQueue(
            backend="auto",
            redis_url=redis_url or os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
        )
    return _global_queue
