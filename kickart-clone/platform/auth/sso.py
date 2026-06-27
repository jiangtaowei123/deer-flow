"""
SSO 单点登录与权限矩阵 - 企业级身份认证
支持：JWT 令牌、OAuth2/OIDC 集成、RBAC 权限矩阵、会话管理
基于 JNPF6.2 低代码平台的权限模型扩展
"""
import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Optional
import base64
import secrets


# ============================================================================
# 权限模型
# ============================================================================

class Permission(str, Enum):
    """权限枚举"""
    # 创作权限
    CREATE_VIDEO = "create:video"
    CREATE_IMAGE = "create:image"
    CREATE_STORYBOARD = "create:storyboard"
    # 查看权限
    VIEW_RUNS = "view:runs"
    VIEW_TENANT = "view:tenant"
    # 管理权限
    MANAGE_TENANT = "manage:tenant"
    MANAGE_AGENTS = "manage:agents"
    MANAGE_WEBHOOKS = "manage:webhooks"
    MANAGE_SSO = "manage:sso"
    # 系统权限
    SYSTEM_ADMIN = "system:admin"
    VIEW_METRICS = "view:metrics"


# 角色定义（RBAC）
ROLE_PERMISSIONS = {
    "viewer": [
        Permission.VIEW_RUNS,
        Permission.VIEW_TENANT,
    ],
    "creator": [
        Permission.CREATE_VIDEO,
        Permission.CREATE_IMAGE,
        Permission.CREATE_STORYBOARD,
        Permission.VIEW_RUNS,
        Permission.VIEW_TENANT,
    ],
    "manager": [
        Permission.CREATE_VIDEO,
        Permission.CREATE_IMAGE,
        Permission.CREATE_STORYBOARD,
        Permission.VIEW_RUNS,
        Permission.VIEW_TENANT,
        Permission.MANAGE_TENANT,
        Permission.MANAGE_AGENTS,
        Permission.MANAGE_WEBHOOKS,
        Permission.VIEW_METRICS,
    ],
    "admin": [p for p in Permission],  # 全部权限
}


@dataclass
class User:
    """用户"""
    user_id: str
    username: str
    email: str
    tenant_id: str
    role: str = "viewer"  # viewer/creator/manager/admin
    active: bool = True
    created_at: Optional[float] = None
    last_login: Optional[float] = None
    metadata: dict = field(default_factory=dict)
    # SSO 相关
    sso_provider: Optional[str] = None  # oauth2/oidc/saml/ldap
    sso_subject: Optional[str] = None  # SSO 提供商返回的唯一标识


@dataclass
class Session:
    """会话"""
    session_id: str
    user_id: str
    tenant_id: str
    token: str
    refresh_token: str
    expires_at: float
    refresh_expires_at: float
    created_at: float
    ip_address: str = ""
    user_agent: str = ""


@dataclass
class SSOTenantConfig:
    """租户 SSO 配置"""
    tenant_id: str
    provider: str  # oauth2/oidc/saml
    client_id: str
    client_secret: str
    authorize_url: str
    token_url: str
    userinfo_url: str
    redirect_uri: str
    scopes: list = field(default_factory=lambda: ["openid", "profile", "email"])
    auto_create_user: bool = True
    default_role: str = "creator"


# ============================================================================
# JWT 工具（无外部依赖，使用 HMAC-SHA256）
# ============================================================================

class JWTCodec:
    """简易 JWT 编解码（HS256）"""

    def __init__(self, secret: str):
        self.secret = secret.encode("utf-8")

    def encode(self, payload: dict, expires_in: int = 3600) -> str:
        header = {"alg": "HS256", "typ": "JWT"}
        now = time.time()
        payload = {**payload, "iat": int(now), "exp": int(now + expires_in), "jti": uuid.uuid4().hex}
        header_b64 = self._b64(json.dumps(header, separators=(",", ":")).encode())
        payload_b64 = self._b64(json.dumps(payload, separators=(",", ":")).encode())
        signing_input = f"{header_b64}.{payload_b64}".encode()
        signature = hmac.new(self.secret, signing_input, hashlib.sha256).digest()
        sig_b64 = self._b64(signature)
        return f"{header_b64}.{payload_b64}.{sig_b64}"

    def decode(self, token: str) -> Optional[dict]:
        try:
            parts = token.split(".")
            if len(parts) != 3:
                return None
            header_b64, payload_b64, sig_b64 = parts
            signing_input = f"{header_b64}.{payload_b64}".encode()
            expected_sig = hmac.new(self.secret, signing_input, hashlib.sha256).digest()
            actual_sig = self._unb64(sig_b64)
            if not hmac.compare_digest(expected_sig, actual_sig):
                return None
            payload = json.loads(self._unb64(payload_b64))
            if payload.get("exp", 0) < time.time():
                return None
            return payload
        except Exception:
            return None

    @staticmethod
    def _b64(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    @staticmethod
    def _unb64(data: str) -> bytes:
        padding = 4 - len(data) % 4
        if padding != 4:
            data += "=" * padding
        return base64.urlsafe_b64decode(data)


# ============================================================================
# SSO 管理器
# ============================================================================

class SSOManager:
    """
    SSO 单点登录管理器
    - 用户管理
    - 会话管理（JWT）
    - RBAC 权限矩阵
    - OAuth2/OIDC 集成
    """

    def __init__(
        self,
        storage_path: str = "/mnt/user-data/workspace/sso",
        jwt_secret: Optional[str] = None,
        token_expires_in: int = 3600,
        refresh_expires_in: int = 86400 * 7,
    ):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.jwt = JWTCodec(jwt_secret or secrets.token_hex(32))
        self.token_expires_in = token_expires_in
        self.refresh_expires_in = refresh_expires_in
        self.users: dict[str, User] = {}
        self.sessions: dict[str, Session] = {}
        self.sso_configs: dict[str, SSOTenantConfig] = {}
        self._load()

    def _load(self):
        """加载数据"""
        users_file = self.storage_path / "users.json"
        if users_file.exists():
            with open(users_file, "r", encoding="utf-8") as f:
                for u_data in json.load(f).get("users", []):
                    user = User(**u_data)
                    self.users[user.user_id] = user
        # 始终保证有一个默认 admin 用户（不破坏已有数据）
        # 检查 admin 用户名是否已存在，缺失则补种
        has_admin = any(u.username == "admin" for u in self.users.values())
        if not has_admin:
            self._seed_default_admin()

    def _save_users(self):
        """保存用户"""
        with open(self.storage_path / "users.json", "w", encoding="utf-8") as f:
            json.dump({
                "users": [
                    {
                        "user_id": u.user_id,
                        "username": u.username,
                        "email": u.email,
                        "tenant_id": u.tenant_id,
                        "role": u.role,
                        "active": u.active,
                        "created_at": u.created_at,
                        "last_login": u.last_login,
                        "metadata": u.metadata,
                        "sso_provider": u.sso_provider,
                        "sso_subject": u.sso_subject,
                    }
                    for u in self.users.values()
                ],
                "updated_at": datetime.now().isoformat(),
            }, f, ensure_ascii=False, indent=2)

    def _seed_default_admin(self):
        """种子默认 admin 用户（首次启动时创建，便于登录测试）"""
        admin = User(
            user_id="user_admin_default",
            username="admin",
            email="admin@kickart.local",
            tenant_id="default",
            role="admin",
            created_at=time.time(),
        )
        self.users[admin.user_id] = admin
        # 也补一个默认 tenant（避免后续查询出错）
        try:
            self._save_users()
        except Exception:
            pass

    # ============ 用户管理 ============

    def create_user(
        self,
        username: str,
        email: str,
        tenant_id: str,
        role: str = "viewer",
        sso_provider: Optional[str] = None,
        sso_subject: Optional[str] = None,
    ) -> User:
        """创建用户"""
        if role not in ROLE_PERMISSIONS:
            raise ValueError(f"未知角色: {role}")
        user = User(
            user_id=f"user_{uuid.uuid4().hex[:12]}",
            username=username,
            email=email,
            tenant_id=tenant_id,
            role=role,
            created_at=time.time(),
            sso_provider=sso_provider,
            sso_subject=sso_subject,
        )
        self.users[user.user_id] = user
        self._save_users()
        return user

    def get_user(self, user_id: str) -> Optional[User]:
        return self.users.get(user_id)

    def find_user_by_sso(self, provider: str, subject: str) -> Optional[User]:
        """通过 SSO 标识查找用户"""
        for user in self.users.values():
            if user.sso_provider == provider and user.sso_subject == subject:
                return user
        return None

    def find_user_by_email(self, email: str) -> Optional[User]:
        for user in self.users.values():
            if user.email == email:
                return user
        return None

    def list_users(self, tenant_id: Optional[str] = None) -> list:
        users = self.users.values()
        if tenant_id:
            users = [u for u in users if u.tenant_id == tenant_id]
        return [
            {
                "user_id": u.user_id,
                "username": u.username,
                "email": u.email,
                "tenant_id": u.tenant_id,
                "role": u.role,
                "active": u.active,
                "sso_provider": u.sso_provider,
                "last_login": datetime.fromtimestamp(u.last_login).isoformat() if u.last_login else None,
            }
            for u in users
        ]

    def update_user_role(self, user_id: str, role: str) -> Optional[User]:
        if role not in ROLE_PERMISSIONS:
            raise ValueError(f"未知角色: {role}")
        user = self.users.get(user_id)
        if not user:
            return None
        user.role = role
        self._save_users()
        return user

    # ============ 会话与令牌 ============

    def create_session(
        self,
        user: User,
        ip_address: str = "",
        user_agent: str = "",
    ) -> Session:
        """创建会话（签发 JWT）"""
        now = time.time()
        payload = {
            "sub": user.user_id,
            "tenant": user.tenant_id,
            "role": user.role,
            "username": user.username,
            "type": "access",
        }
        token = self.jwt.encode(payload, self.token_expires_in)
        refresh_payload = {**payload, "type": "refresh"}
        refresh_token = self.jwt.encode(refresh_payload, self.refresh_expires_in)

        session = Session(
            session_id=f"sess_{uuid.uuid4().hex[:12]}",
            user_id=user.user_id,
            tenant_id=user.tenant_id,
            token=token,
            refresh_token=refresh_token,
            expires_at=now + self.token_expires_in,
            refresh_expires_at=now + self.refresh_expires_in,
            created_at=now,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        self.sessions[session.session_id] = session
        user.last_login = now
        self._save_users()
        return session

    def verify_token(self, token: str) -> Optional[dict]:
        """验证 JWT 令牌"""
        payload = self.jwt.decode(token)
        if not payload or payload.get("type") != "access":
            return None
        user = self.users.get(payload.get("sub"))
        if not user or not user.active:
            return None
        return payload

    def refresh_token(self, refresh_token: str) -> Optional[Session]:
        """刷新令牌"""
        payload = self.jwt.decode(refresh_token)
        if not payload or payload.get("type") != "refresh":
            return None
        user = self.users.get(payload.get("sub"))
        if not user or not user.active:
            return None
        return self.create_session(user)

    def revoke_session(self, session_id: str) -> bool:
        """撤销会话"""
        if session_id in self.sessions:
            del self.sessions[session_id]
            return True
        return False

    def revoke_all_sessions(self, user_id: str) -> int:
        """撤销用户所有会话"""
        to_remove = [sid for sid, s in self.sessions.items() if s.user_id == user_id]
        for sid in to_remove:
            del self.sessions[sid]
        return len(to_remove)

    # ============ 权限矩阵 ============

    def check_permission(self, user: User, permission: Permission) -> bool:
        """检查用户权限"""
        permissions = ROLE_PERMISSIONS.get(user.role, [])
        return permission in permissions

    def check_permission_by_token(self, token: str, permission: Permission) -> bool:
        """通过令牌检查权限"""
        payload = self.verify_token(token)
        if not payload:
            return False
        user = self.users.get(payload.get("sub"))
        if not user:
            return False
        return self.check_permission(user, permission)

    def get_user_permissions(self, user: User) -> list:
        """获取用户权限列表"""
        return [p.value for p in ROLE_PERMISSIONS.get(user.role, [])]

    # ============ SSO 配置 ============

    def set_sso_config(self, config: SSOTenantConfig):
        """设置租户 SSO 配置"""
        self.sso_configs[config.tenant_id] = config
        config_file = self.storage_path / f"sso_{config.tenant_id}.json"
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump({
                "tenant_id": config.tenant_id,
                "provider": config.provider,
                "client_id": config.client_id,
                "client_secret": config.client_secret,
                "authorize_url": config.authorize_url,
                "token_url": config.token_url,
                "userinfo_url": config.userinfo_url,
                "redirect_uri": config.redirect_uri,
                "scopes": config.scopes,
                "auto_create_user": config.auto_create_user,
                "default_role": config.default_role,
            }, f, ensure_ascii=False, indent=2)

    def get_sso_config(self, tenant_id: str) -> Optional[SSOTenantConfig]:
        return self.sso_configs.get(tenant_id)

    def build_authorize_url(self, tenant_id: str, state: str) -> Optional[str]:
        """构建 SSO 授权 URL"""
        config = self.sso_configs.get(tenant_id)
        if not config:
            return None
        from urllib.parse import urlencode
        params = urlencode({
            "client_id": config.client_id,
            "redirect_uri": config.redirect_uri,
            "response_type": "code",
            "scope": " ".join(config.scopes),
            "state": state,
        })
        return f"{config.authorize_url}?{params}"

    def handle_sso_callback(
        self,
        tenant_id: str,
        code: str,
        userinfo: dict,
        ip_address: str = "",
    ) -> Optional[Session]:
        """
        处理 SSO 回调
        userinfo 应包含：sub, email, name（或 username）
        """
        config = self.sso_configs.get(tenant_id)
        if not config:
            return None

        provider = config.provider
        subject = userinfo.get("sub", "")
        email = userinfo.get("email", "")
        name = userinfo.get("name") or userinfo.get("username") or email

        # 查找已有用户
        user = self.find_user_by_sso(provider, subject)
        if not user and email:
            user = self.find_user_by_email(email)
            if user:
                user.sso_provider = provider
                user.sso_subject = subject

        # 自动创建用户
        if not user and config.auto_create_user:
            user = self.create_user(
                username=name,
                email=email,
                tenant_id=tenant_id,
                role=config.default_role,
                sso_provider=provider,
                sso_subject=subject,
            )

        if not user or not user.active:
            return None

        return self.create_session(user, ip_address=ip_address)


# ============================================================================
# 全局单例
# ============================================================================

_sso_manager: Optional[SSOManager] = None


def get_sso_manager() -> SSOManager:
    global _sso_manager
    if _sso_manager is None:
        _sso_manager = SSOManager()
    return _sso_manager


# ============================================================================
# CLI 入口
# ============================================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(description="SSO 单点登录与权限矩阵")
    parser.add_argument("--action", required=True,
                        choices=["create-user", "list-users", "create-session", "verify", "permission", "sso-config"])
    parser.add_argument("--username")
    parser.add_argument("--email")
    parser.add_argument("--tenant-id")
    parser.add_argument("--role", default="viewer", choices=list(ROLE_PERMISSIONS.keys()))
    parser.add_argument("--token")
    parser.add_argument("--permission")
    parser.add_argument("--storage", default="/mnt/user-data/workspace/sso")

    args = parser.parse_args()
    mgr = SSOManager(storage_path=args.storage)

    if args.action == "create-user":
        if not all([args.username, args.email, args.tenant_id]):
            print("错误: 需要 --username --email --tenant-id")
            return 1
        user = mgr.create_user(args.username, args.email, args.tenant_id, args.role)
        print(f"✅ 用户创建: {user.user_id} ({user.role})")
    elif args.action == "list-users":
        print(json.dumps(mgr.list_users(args.tenant_id), ensure_ascii=False, indent=2))
    elif args.action == "create-session":
        if not args.username:
            print("错误: 需要 --username")
            return 1
        user = next((u for u in mgr.users.values() if u.username == args.username), None)
        if not user:
            print("用户不存在")
            return 1
        session = mgr.create_session(user)
        print(json.dumps({
            "session_id": session.session_id,
            "token": session.token,
            "refresh_token": session.refresh_token,
            "expires_at": datetime.fromtimestamp(session.expires_at).isoformat(),
        }, ensure_ascii=False, indent=2))
    elif args.action == "verify":
        if not args.token:
            print("错误: 需要 --token")
            return 1
        payload = mgr.verify_token(args.token)
        if payload:
            print(f"✅ 令牌有效: {payload.get('username')} ({payload.get('role')})")
        else:
            print("❌ 令牌无效或已过期")
            return 1
    elif args.action == "permission":
        if not args.token or not args.permission:
            print("错误: 需要 --token --permission")
            return 1
        try:
            perm = Permission(args.permission)
        except ValueError:
            print(f"未知权限: {args.permission}")
            return 1
        allowed = mgr.check_permission_by_token(args.token, perm)
        print(f"{'✅ 允许' if allowed else '❌ 拒绝'}: {args.permission}")
        return 0 if allowed else 1
    elif args.action == "sso-config":
        if not args.tenant_id:
            print("错误: 需要 --tenant-id")
            return 1
        config = mgr.get_sso_config(args.tenant_id)
        if config:
            print(json.dumps({
                "tenant_id": config.tenant_id,
                "provider": config.provider,
                "authorize_url": config.authorize_url,
            }, ensure_ascii=False, indent=2))
        else:
            print("未配置 SSO")
            return 1

    return 0


if __name__ == "__main__":
    exit(main())
