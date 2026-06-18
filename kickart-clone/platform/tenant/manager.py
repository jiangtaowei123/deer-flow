"""
多租户支持 - 租户隔离与资源管理
支持：租户管理、配额控制、资源隔离、API 鉴权
"""
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional


# ============================================================================
# 租户模型
# ============================================================================

@dataclass
class Tenant:
    """租户"""
    tenant_id: str
    name: str
    plan: str = "free"  # free/pro/enterprise
    api_key: str = ""
    quota: dict = field(default_factory=dict)
    created_at: Optional[float] = None
    active: bool = True
    metadata: dict = field(default_factory=dict)


# 套餐配额定义
PLAN_QUOTAS = {
    "free": {
        "daily_videos": 3,
        "daily_images": 30,
        "concurrent_runs": 1,
        "storage_mb": 500,
        "agents": ["product_parser", "creative", "storyboard"],
    },
    "pro": {
        "daily_videos": 50,
        "daily_images": 500,
        "concurrent_runs": 5,
        "storage_mb": 5000,
        "agents": ["product_parser", "creative", "storyboard", "image_gen", "tts", "video_gen"],
    },
    "enterprise": {
        "daily_videos": 1000,
        "daily_images": 10000,
        "concurrent_runs": 20,
        "storage_mb": 100000,
        "agents": ["product_parser", "creative", "storyboard", "image_gen", "tts", "video_gen"],
    },
}


# ============================================================================
# 多租户管理器
# ============================================================================

class TenantManager:
    """
    多租户管理器
    - 租户 CRUD
    - API Key 鉴权
    - 配额控制
    - 资源隔离
    """

    def __init__(self, storage_path: str = "/mnt/user-data/workspace/tenants"):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.tenants: dict[str, Tenant] = {}
        self.usage: dict[str, dict] = {}  # tenant_id -> daily usage
        self._load_tenants()

    def _load_tenants(self):
        """加载租户数据"""
        tenants_file = self.storage_path / "tenants.json"
        if tenants_file.exists():
            with open(tenants_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                for t_data in data.get("tenants", []):
                    tenant = Tenant(**t_data)
                    self.tenants[tenant.tenant_id] = tenant

    def _save_tenants(self):
        """保存租户数据"""
        tenants_file = self.storage_path / "tenants.json"
        with open(tenants_file, "w", encoding="utf-8") as f:
            json.dump({
                "tenants": [
                    {
                        "tenant_id": t.tenant_id,
                        "name": t.name,
                        "plan": t.plan,
                        "api_key": t.api_key,
                        "quota": t.quota,
                        "created_at": t.created_at,
                        "active": t.active,
                        "metadata": t.metadata,
                    }
                    for t in self.tenants.values()
                ],
                "updated_at": datetime.now().isoformat(),
            }, f, ensure_ascii=False, indent=2)

    # ============ 租户 CRUD ============

    def create_tenant(self, name: str, plan: str = "free") -> Tenant:
        """创建租户"""
        tenant_id = f"tenant_{uuid.uuid4().hex[:8]}"
        api_key = f"kk_{uuid.uuid4().hex}"
        quota = PLAN_QUOTAS.get(plan, PLAN_QUOTAS["free"]).copy()

        tenant = Tenant(
            tenant_id=tenant_id,
            name=name,
            plan=plan,
            api_key=api_key,
            quota=quota,
            created_at=time.time(),
        )
        self.tenants[tenant_id] = tenant
        self.usage[tenant_id] = self._init_usage()
        self._save_tenants()
        return tenant

    def get_tenant(self, tenant_id: str) -> Optional[Tenant]:
        """获取租户"""
        return self.tenants.get(tenant_id)

    def get_tenant_by_api_key(self, api_key: str) -> Optional[Tenant]:
        """通过 API Key 获取租户"""
        for tenant in self.tenants.values():
            if tenant.api_key == api_key and tenant.active:
                return tenant
        return None

    def list_tenants(self) -> list:
        """列出所有租户"""
        return [
            {
                "tenant_id": t.tenant_id,
                "name": t.name,
                "plan": t.plan,
                "active": t.active,
                "created_at": datetime.fromtimestamp(t.created_at).isoformat() if t.created_at else None,
                "usage": self.usage.get(t.tenant_id, {}),
            }
            for t in self.tenants.values()
        ]

    def update_tenant(self, tenant_id: str, **kwargs) -> Optional[Tenant]:
        """更新租户"""
        tenant = self.tenants.get(tenant_id)
        if not tenant:
            return None

        if "plan" in kwargs:
            tenant.plan = kwargs["plan"]
            tenant.quota = PLAN_QUOTAS.get(tenant.plan, PLAN_QUOTAS["free"]).copy()
        if "name" in kwargs:
            tenant.name = kwargs["name"]
        if "active" in kwargs:
            tenant.active = kwargs["active"]

        self._save_tenants()
        return tenant

    def delete_tenant(self, tenant_id: str) -> bool:
        """删除租户"""
        if tenant_id in self.tenants:
            del self.tenants[tenant_id]
            self.usage.pop(tenant_id, None)
            self._save_tenants()
            return True
        return False

    # ============ 配额控制 ============

    def _init_usage(self) -> dict:
        """初始化当日用量"""
        today = datetime.now().strftime("%Y-%m-%d")
        return {
            "date": today,
            "videos": 0,
            "images": 0,
            "runs": 0,
            "storage_mb": 0.0,
        }

    def _check_daily_reset(self, tenant_id: str):
        """检查是否需要重置日用量"""
        today = datetime.now().strftime("%Y-%m-%d")
        usage = self.usage.get(tenant_id, self._init_usage())
        if usage.get("date") != today:
            self.usage[tenant_id] = self._init_usage()

    def check_quota(self, tenant_id: str, resource: str) -> dict:
        """检查配额"""
        tenant = self.tenants.get(tenant_id)
        if not tenant:
            return {"allowed": False, "error": "租户不存在"}

        self._check_daily_reset(tenant_id)
        usage = self.usage.get(tenant_id, self._init_usage())

        quota_map = {
            "video": ("daily_videos", "videos"),
            "image": ("daily_images", "images"),
            "run": ("concurrent_runs", "runs"),
        }

        if resource not in quota_map:
            return {"allowed": True}

        quota_key, usage_key = quota_map[resource]
        limit = tenant.quota.get(quota_key, 0)
        current = usage.get(usage_key, 0)

        return {
            "allowed": current < limit,
            "limit": limit,
            "current": current,
            "remaining": max(0, limit - current),
        }

    def record_usage(self, tenant_id: str, resource: str, count: int = 1):
        """记录用量"""
        self._check_daily_reset(tenant_id)
        usage = self.usage.setdefault(tenant_id, self._init_usage())

        usage_map = {
            "video": "videos",
            "image": "images",
            "run": "runs",
        }
        if resource in usage_map:
            usage[usage_map[resource]] = usage.get(usage_map[resource], 0) + count

    # ============ 资源隔离 ============

    def get_tenant_workspace(self, tenant_id: str) -> str:
        """获取租户专属工作空间"""
        workspace = self.storage_path / tenant_id / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        return str(workspace)

    def get_tenant_output_dir(self, tenant_id: str) -> str:
        """获取租户专属输出目录"""
        output_dir = self.storage_path / tenant_id / "outputs"
        output_dir.mkdir(parents=True, exist_ok=True)
        return str(output_dir)

    def check_agent_access(self, tenant_id: str, agent_name: str) -> bool:
        """检查租户是否有权访问某个 Agent"""
        tenant = self.tenants.get(tenant_id)
        if not tenant:
            return False
        allowed_agents = tenant.quota.get("agents", [])
        return agent_name in allowed_agents

    # ============ 鉴权 ============

    def authenticate(self, api_key: str) -> Optional[Tenant]:
        """API Key 鉴权"""
        tenant = self.get_tenant_by_api_key(api_key)
        if not tenant:
            return None
        if not tenant.active:
            return None
        return tenant


# ============================================================================
# CLI 入口
# ============================================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(description="多租户管理")
    parser.add_argument(
        "--action",
        choices=["create", "list", "get", "update", "delete", "quota", "auth"],
        required=True,
    )
    parser.add_argument("--name", help="租户名称")
    parser.add_argument("--plan", default="free", choices=["free", "pro", "enterprise"])
    parser.add_argument("--tenant-id")
    parser.add_argument("--api-key")
    parser.add_argument("--resource", choices=["video", "image", "run"])
    parser.add_argument("--storage", default="/mnt/user-data/workspace/tenants")

    args = parser.parse_args()
    manager = TenantManager(storage_path=args.storage)

    if args.action == "create":
        if not args.name:
            print("错误: 需要 --name")
            return 1
        tenant = manager.create_tenant(args.name, args.plan)
        print(f"✅ 租户创建成功")
        print(f"   ID: {tenant.tenant_id}")
        print(f"   名称: {tenant.name}")
        print(f"   套餐: {tenant.plan}")
        print(f"   API Key: {tenant.api_key}")
    elif args.action == "list":
        print(json.dumps(manager.list_tenants(), ensure_ascii=False, indent=2))
    elif args.action == "get":
        if not args.tenant_id:
            print("错误: 需要 --tenant-id")
            return 1
        tenant = manager.get_tenant(args.tenant_id)
        if tenant:
            print(json.dumps({
                "tenant_id": tenant.tenant_id,
                "name": tenant.name,
                "plan": tenant.plan,
                "api_key": tenant.api_key,
                "quota": tenant.quota,
                "active": tenant.active,
            }, ensure_ascii=False, indent=2))
        else:
            print("租户不存在")
            return 1
    elif args.action == "quota":
        if not args.tenant_id or not args.resource:
            print("错误: 需要 --tenant-id 和 --resource")
            return 1
        result = manager.check_quota(args.tenant_id, args.resource)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.action == "auth":
        if not args.api_key:
            print("错误: 需要 --api-key")
            return 1
        tenant = manager.authenticate(args.api_key)
        if tenant:
            print(f"✅ 鉴权成功: {tenant.name} ({tenant.plan})")
        else:
            print("❌ 鉴权失败")
            return 1

    return 0


if __name__ == "__main__":
    exit(main())
