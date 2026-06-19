"""
Webhook 事件订阅系统 - 事件驱动的外部集成
支持：事件订阅、Webhook 投递、签名验证、重试机制、死信队列
基于 JNPF6.2 流程引擎事件扩展
"""
import hashlib
import hmac
import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError


# ============================================================================
# 事件模型
# ============================================================================

class EventType(str, Enum):
    """事件类型"""
    # 工作流事件
    WORKFLOW_STARTED = "workflow.started"
    WORKFLOW_COMPLETED = "workflow.completed"
    WORKFLOW_FAILED = "workflow.failed"
    WORKFLOW_DEGRADED = "workflow.degraded"
    # Agent 事件
    AGENT_TASK_COMPLETED = "agent.task_completed"
    AGENT_TASK_FAILED = "agent.task_failed"
    # 资产事件
    ASSET_CREATED = "asset.created"
    ASSET_REUSED = "asset.reused"
    # 租户事件
    TENANT_CREATED = "tenant.created"
    TENANT_QUOTA_EXCEEDED = "tenant.quota_exceeded"
    # 系统事件
    SYSTEM_HEALTH = "system.health"
    SYSTEM_ALERT = "system.alert"


@dataclass
class WebhookSubscription:
    """Webhook 订阅"""
    subscription_id: str
    tenant_id: str
    url: str
    events: list  # 订阅的事件类型列表，["*"] 表示全部
    secret: str  # 用于签名验证
    active: bool = True
    created_at: Optional[float] = None
    # 投递配置
    max_retries: int = 3
    timeout_sec: int = 10
    metadata: dict = field(default_factory=dict)


@dataclass
class WebhookDelivery:
    """Webhook 投递记录"""
    delivery_id: str
    subscription_id: str
    event_type: str
    payload: dict
    url: str
    status: str = "pending"  # pending/success/failed/dead
    attempt: int = 0
    response_code: Optional[int] = None
    response_body: str = ""
    error: str = ""
    created_at: Optional[float] = None
    completed_at: Optional[float] = None
    next_retry_at: Optional[float] = None


# ============================================================================
# Webhook 管理器
# ============================================================================

class WebhookManager:
    """
    Webhook 事件订阅管理器
    - 订阅 CRUD
    - 事件发布
    - 异步投递（带重试）
    - 签名验证
    - 死信队列
    """

    def __init__(self, storage_path: str = "/mnt/user-data/workspace/webhooks"):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.subscriptions: dict[str, WebhookSubscription] = {}
        self.deliveries: dict[str, WebhookDelivery] = {}
        self.dead_letters: dict[str, WebhookDelivery] = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self):
        """加载订阅"""
        sub_file = self.storage_path / "subscriptions.json"
        if sub_file.exists():
            with open(sub_file, "r", encoding="utf-8") as f:
                for s_data in json.load(f).get("subscriptions", []):
                    sub = WebhookSubscription(**s_data)
                    self.subscriptions[sub.subscription_id] = sub

    def _save_subscriptions(self):
        """保存订阅"""
        with open(self.storage_path / "subscriptions.json", "w", encoding="utf-8") as f:
            json.dump({
                "subscriptions": [
                    {
                        "subscription_id": s.subscription_id,
                        "tenant_id": s.tenant_id,
                        "url": s.url,
                        "events": s.events,
                        "secret": s.secret,
                        "active": s.active,
                        "created_at": s.created_at,
                        "max_retries": s.max_retries,
                        "timeout_sec": s.timeout_sec,
                        "metadata": s.metadata,
                    }
                    for s in self.subscriptions.values()
                ],
                "updated_at": datetime.now().isoformat(),
            }, f, ensure_ascii=False, indent=2)

    # ============ 订阅管理 ============

    def subscribe(
        self,
        tenant_id: str,
        url: str,
        events: list,
        max_retries: int = 3,
        timeout_sec: int = 10,
    ) -> WebhookSubscription:
        """创建订阅"""
        # 验证事件类型
        valid_events = set()
        for e in events:
            if e == "*":
                valid_events.add("*")
            else:
                try:
                    EventType(e)
                    valid_events.add(e)
                except ValueError:
                    pass
        if not valid_events:
            raise ValueError("无有效事件类型")

        sub = WebhookSubscription(
            subscription_id=f"sub_{uuid.uuid4().hex[:12]}",
            tenant_id=tenant_id,
            url=url,
            events=list(valid_events),
            secret=uuid.uuid4().hex,
            created_at=time.time(),
            max_retries=max_retries,
            timeout_sec=timeout_sec,
        )
        with self._lock:
            self.subscriptions[sub.subscription_id] = sub
            self._save_subscriptions()
        return sub

    def unsubscribe(self, subscription_id: str) -> bool:
        """取消订阅"""
        with self._lock:
            if subscription_id in self.subscriptions:
                del self.subscriptions[subscription_id]
                self._save_subscriptions()
                return True
            return False

    def list_subscriptions(self, tenant_id: Optional[str] = None) -> list:
        subs = self.subscriptions.values()
        if tenant_id:
            subs = [s for s in subs if s.tenant_id == tenant_id]
        return [
            {
                "subscription_id": s.subscription_id,
                "tenant_id": s.tenant_id,
                "url": s.url,
                "events": s.events,
                "active": s.active,
                "created_at": datetime.fromtimestamp(s.created_at).isoformat() if s.created_at else None,
            }
            for s in subs
        ]

    def deactivate(self, subscription_id: str) -> bool:
        """停用订阅"""
        with self._lock:
            sub = self.subscriptions.get(subscription_id)
            if sub:
                sub.active = False
                self._save_subscriptions()
                return True
            return False

    # ============ 事件发布与投递 ============

    def publish(self, event_type: str, payload: dict, tenant_id: Optional[str] = None) -> list:
        """
        发布事件
        返回投递记录 ID 列表
        """
        try:
            event = EventType(event_type)
        except ValueError:
            raise ValueError(f"未知事件类型: {event_type}")

        # 查找匹配的订阅
        matched_subs = []
        with self._lock:
            for sub in self.subscriptions.values():
                if not sub.active:
                    continue
                if tenant_id and sub.tenant_id != tenant_id:
                    continue
                if "*" in sub.events or event.value in sub.events:
                    matched_subs.append(sub)

        # 创建投递记录
        delivery_ids = []
        for sub in matched_subs:
            delivery = WebhookDelivery(
                delivery_id=f"dlv_{uuid.uuid4().hex[:12]}",
                subscription_id=sub.subscription_id,
                event_type=event.value,
                payload={
                    "event": event.value,
                    "timestamp": datetime.now().isoformat(),
                    "tenant_id": sub.tenant_id,
                    "data": payload,
                },
                url=sub.url,
                created_at=time.time(),
            )
            with self._lock:
                self.deliveries[delivery.delivery_id] = delivery
            delivery_ids.append(delivery.delivery_id)
            # 同步投递（生产环境应改为异步队列）
            self._deliver(delivery, sub)

        return delivery_ids

    def _deliver(self, delivery: WebhookDelivery, sub: WebhookSubscription):
        """执行投递（带重试）"""
        delivery.status = "pending"
        payload_bytes = json.dumps(delivery.payload).encode("utf-8")

        # 计算签名（HMAC-SHA256）
        signature = hmac.new(
            sub.secret.encode("utf-8"),
            payload_bytes,
            hashlib.sha256,
        ).hexdigest()

        headers = {
            "Content-Type": "application/json",
            "X-Kickart-Event": delivery.event_type,
            "X-Kickart-Signature": f"sha256={signature}",
            "X-Kickart-Delivery": delivery.delivery_id,
        }

        for attempt in range(1, sub.max_retries + 1):
            delivery.attempt = attempt
            try:
                req = Request(
                    delivery.url,
                    data=payload_bytes,
                    headers=headers,
                    method="POST",
                )
                with urlopen(req, timeout=sub.timeout_sec) as resp:
                    delivery.response_code = resp.getcode()
                    delivery.response_body = resp.read(4096).decode("utf-8", errors="replace")
                    if 200 <= delivery.response_code < 300:
                        delivery.status = "success"
                        delivery.completed_at = time.time()
                        return
                    else:
                        delivery.error = f"HTTP {delivery.response_code}"
            except (URLError, HTTPError, TimeoutError, OSError) as e:
                delivery.error = f"{type(e).__name__}: {e}"
            except Exception as e:
                delivery.error = f"{type(e).__name__}: {e}"

            # 等待重试（指数退避）
            if attempt < sub.max_retries:
                wait = min(2 ** attempt, 30)
                delivery.next_retry_at = time.time() + wait
                time.sleep(wait)

        # 所有重试失败 → 死信
        delivery.status = "dead"
        delivery.completed_at = time.time()
        with self._lock:
            self.dead_letters[delivery.delivery_id] = delivery

    # ============ 投递记录查询 ============

    def get_delivery(self, delivery_id: str) -> Optional[dict]:
        """获取投递记录"""
        delivery = self.deliveries.get(delivery_id) or self.dead_letters.get(delivery_id)
        if not delivery:
            return None
        return {
            "delivery_id": delivery.delivery_id,
            "subscription_id": delivery.subscription_id,
            "event_type": delivery.event_type,
            "url": delivery.url,
            "status": delivery.status,
            "attempt": delivery.attempt,
            "response_code": delivery.response_code,
            "error": delivery.error,
            "created_at": datetime.fromtimestamp(delivery.created_at).isoformat() if delivery.created_at else None,
            "completed_at": datetime.fromtimestamp(delivery.completed_at).isoformat() if delivery.completed_at else None,
        }

    def list_deliveries(
        self,
        subscription_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> list:
        """列出投递记录"""
        deliveries = list(self.deliveries.values()) + list(self.dead_letters.values())
        if subscription_id:
            deliveries = [d for d in deliveries if d.subscription_id == subscription_id]
        if status:
            deliveries = [d for d in deliveries if d.status == status]
        deliveries.sort(key=lambda d: d.created_at or 0, reverse=True)
        return [
            {
                "delivery_id": d.delivery_id,
                "event_type": d.event_type,
                "status": d.status,
                "attempt": d.attempt,
                "url": d.url,
                "created_at": datetime.fromtimestamp(d.created_at).isoformat() if d.created_at else None,
            }
            for d in deliveries[:limit]
        ]

    def list_dead_letters(self, limit: int = 50) -> list:
        """列出死信"""
        dead = list(self.dead_letters.values())
        dead.sort(key=lambda d: d.created_at or 0, reverse=True)
        return [
            {
                "delivery_id": d.delivery_id,
                "event_type": d.event_type,
                "url": d.url,
                "attempt": d.attempt,
                "error": d.error,
                "created_at": datetime.fromtimestamp(d.created_at).isoformat() if d.created_at else None,
            }
            for d in dead[:limit]
        ]

    def replay_delivery(self, delivery_id: str) -> bool:
        """重放死信"""
        delivery = self.dead_letters.get(delivery_id)
        if not delivery:
            return False
        sub = self.subscriptions.get(delivery.subscription_id)
        if not sub or not sub.active:
            return False
        # 从死信移除，重新投递
        with self._lock:
            del self.dead_letters[delivery_id]
        delivery.status = "pending"
        delivery.attempt = 0
        delivery.error = ""
        self._deliver(delivery, sub)
        return True

    # ============ 签名验证（供接收方使用） ============

    @staticmethod
    def verify_signature(
        payload_bytes: bytes,
        signature_header: str,
        secret: str,
    ) -> bool:
        """
        验证 Webhook 签名
        signature_header 格式: sha256=<hex>
        """
        if not signature_header.startswith("sha256="):
            return False
        expected = hmac.new(
            secret.encode("utf-8"),
            payload_bytes,
            hashlib.sha256,
        ).hexdigest()
        actual = signature_header[7:]
        return hmac.compare_digest(expected, actual)


# ============================================================================
# 全局单例
# ============================================================================

_webhook_manager: Optional[WebhookManager] = None


def get_webhook_manager() -> WebhookManager:
    global _webhook_manager
    if _webhook_manager is None:
        _webhook_manager = WebhookManager()
    return _webhook_manager


# ============================================================================
# CLI 入口
# ============================================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Webhook 事件订阅系统")
    parser.add_argument("--action", required=True,
                        choices=["subscribe", "unsubscribe", "list", "publish", "deliveries", "dead-letters", "replay"])
    parser.add_argument("--tenant-id")
    parser.add_argument("--url")
    parser.add_argument("--events", help="逗号分隔的事件列表")
    parser.add_argument("--event")
    parser.add_argument("--payload-json", help="payload JSON 文件")
    parser.add_argument("--subscription-id")
    parser.add_argument("--delivery-id")
    parser.add_argument("--storage", default="/mnt/user-data/workspace/webhooks")

    args = parser.parse_args()
    mgr = WebhookManager(storage_path=args.storage)

    if args.action == "subscribe":
        if not all([args.tenant_id, args.url, args.events]):
            print("错误: 需要 --tenant-id --url --events")
            return 1
        events = [e.strip() for e in args.events.split(",")]
        sub = mgr.subscribe(args.tenant_id, args.url, events)
        print(f"✅ 订阅创建: {sub.subscription_id}")
        print(f"   Secret: {sub.secret}")
    elif args.action == "unsubscribe":
        if not args.subscription_id:
            print("错误: 需要 --subscription-id")
            return 1
        if mgr.unsubscribe(args.subscription_id):
            print("✅ 已取消订阅")
        else:
            print("❌ 订阅不存在")
            return 1
    elif args.action == "list":
        print(json.dumps(mgr.list_subscriptions(args.tenant_id), ensure_ascii=False, indent=2))
    elif args.action == "publish":
        if not args.event:
            print("错误: 需要 --event")
            return 1
        payload = {}
        if args.payload_json:
            with open(args.payload_json, "r", encoding="utf-8") as f:
                payload = json.load(f)
        delivery_ids = mgr.publish(args.event, payload, args.tenant_id)
        print(f"✅ 事件已发布，投递 {len(delivery_ids)} 个订阅")
        for did in delivery_ids:
            d = mgr.get_delivery(did)
            print(f"   {did}: {d['status'] if d else 'unknown'}")
    elif args.action == "deliveries":
        print(json.dumps(mgr.list_deliveries(args.subscription_id), ensure_ascii=False, indent=2))
    elif args.action == "dead-letters":
        print(json.dumps(mgr.list_dead_letters(), ensure_ascii=False, indent=2))
    elif args.action == "replay":
        if not args.delivery_id:
            print("错误: 需要 --delivery-id")
            return 1
        if mgr.replay_delivery(args.delivery_id):
            print("✅ 已重放")
        else:
            print("❌ 重放失败")
            return 1

    return 0


if __name__ == "__main__":
    exit(main())
