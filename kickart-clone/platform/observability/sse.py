"""
SSE 实时进度推送 - Server-Sent Events
支持工作流执行进度的实时推送
"""
import asyncio
import json
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from logger import get_logger

logger = get_logger(__name__)


@dataclass
class ProgressEvent:
    """进度事件"""
    event_type: str  # started/progress/task_completed/completed/failed
    run_id: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    data: dict = field(default_factory=dict)

    def to_sse(self) -> str:
        """转换为 SSE 格式"""
        return (
            f"event: {self.event_type}\n"
            f"data: {json.dumps({'run_id': self.run_id, 'timestamp': self.timestamp, **self.data}, ensure_ascii=False)}\n\n"
        )


class ProgressBroadcaster:
    """
    进度广播器
    - 每个工作流 run 有独立的订阅队列
    - 支持多订阅者
    - 自动清理已完成 run 的队列
    """

    def __init__(self, max_queue_size: int = 100):
        self.max_queue_size = max_queue_size
        # run_id -> list[Queue]
        self._subscribers: dict[str, list[queue.Queue]] = {}
        # run_id -> 最后事件（用于新订阅者立即获取最新状态）
        self._last_events: dict[str, ProgressEvent] = {}
        self._lock = threading.Lock()

    def subscribe(self, run_id: str) -> queue.Queue:
        """订阅某个 run 的进度"""
        q = queue.Queue(maxsize=self.max_queue_size)
        with self._lock:
            if run_id not in self._subscribers:
                self._subscribers[run_id] = []
            self._subscribers[run_id].append(q)

            # 发送最后状态
            if run_id in self._last_events:
                try:
                    q.put_nowait(self._last_events[run_id])
                except queue.Full:
                    pass

        logger.info(f"SSE 订阅: run_id={run_id}, 订阅者数={len(self._subscribers[run_id])}")
        return q

    def unsubscribe(self, run_id: str, q: queue.Queue):
        """取消订阅"""
        with self._lock:
            if run_id in self._subscribers:
                try:
                    self._subscribers[run_id].remove(q)
                except ValueError:
                    pass
                if not self._subscribers[run_id]:
                    del self._subscribers[run_id]

    def broadcast(self, event: ProgressEvent):
        """广播事件到所有订阅者"""
        with self._lock:
            self._last_events[event.run_id] = event
            subscribers = self._subscribers.get(event.run_id, []).copy()

        for q in subscribers:
            try:
                q.put_nowait(event)
            except queue.Full:
                # 队列满，丢弃旧事件
                try:
                    q.get_nowait()
                    q.put_nowait(event)
                except queue.Empty:
                    pass

        logger.debug(f"SSE 广播: run_id={event.run_id}, type={event.event_type}, 订阅者={len(subscribers)}")

    def emit_started(self, run_id: str, workflow_type: str, task_count: int):
        """发送开始事件"""
        self.broadcast(ProgressEvent(
            event_type="started",
            run_id=run_id,
            data={
                "workflow_type": workflow_type,
                "task_count": task_count,
                "message": f"工作流启动: {workflow_type}, {task_count} 个任务",
            },
        ))

    def emit_progress(self, run_id: str, progress: float, current_task: str = "", task_index: int = 0, task_total: int = 0):
        """发送进度事件"""
        self.broadcast(ProgressEvent(
            event_type="progress",
            run_id=run_id,
            data={
                "progress": round(progress * 100, 1),
                "current_task": current_task,
                "task_index": task_index,
                "task_total": task_total,
                "message": f"进度: {progress*100:.1f}% - {current_task}",
            },
        ))

    def emit_task_completed(self, run_id: str, task_name: str, task_index: int, task_total: int, success: bool = True):
        """发送任务完成事件"""
        self.broadcast(ProgressEvent(
            event_type="task_completed",
            run_id=run_id,
            data={
                "task_name": task_name,
                "task_index": task_index,
                "task_total": task_total,
                "success": success,
                "message": f"任务完成: {task_name} ({task_index}/{task_total})",
            },
        ))

    def emit_completed(self, run_id: str, success: bool, artifacts: dict = None, duration: float = 0):
        """发送完成事件"""
        self.broadcast(ProgressEvent(
            event_type="completed" if success else "failed",
            run_id=run_id,
            data={
                "success": success,
                "duration_sec": round(duration, 2),
                "artifacts": artifacts or {},
                "message": "工作流完成" if success else "工作流失败",
            },
        ))

    def cleanup(self, run_id: str):
        """清理 run 的所有订阅"""
        with self._lock:
            self._subscribers.pop(run_id, None)
            self._last_events.pop(run_id, None)


# 全局广播器单例
_broadcaster: Optional[ProgressBroadcaster] = None


def get_broadcaster() -> ProgressBroadcaster:
    """获取全局广播器"""
    global _broadcaster
    if _broadcaster is None:
        _broadcaster = ProgressBroadcaster()
    return _broadcaster


def sse_event_generator(run_id: str):
    """
    SSE 事件生成器（用于 FastAPI StreamingResponse）

    Yields:
        SSE 格式字符串
    """
    broadcaster = get_broadcaster()
    q = broadcaster.subscribe(run_id)

    # 发送连接建立事件
    yield f"event: connected\ndata: {json.dumps({'run_id': run_id, 'message': 'SSE 连接已建立'})}\n\n"

    try:
        while True:
            try:
                # 非阻塞获取，超时后发送心跳
                event = q.get(timeout=15)
                yield event.to_sse()

                # 如果是完成/失败事件，结束生成器
                if event.event_type in ("completed", "failed"):
                    break
            except queue.Empty:
                # 发送心跳保持连接
                yield f"event: heartbeat\ndata: {json.dumps({'timestamp': datetime.now().isoformat()})}\n\n"
    finally:
        broadcaster.unsubscribe(run_id, q)
        logger.info(f"SSE 连接关闭: run_id={run_id}")
