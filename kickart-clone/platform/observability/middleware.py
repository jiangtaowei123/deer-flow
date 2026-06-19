"""
API 安全中间件 - 鉴权与速率限制
- API Key 鉴权（基于多租户）
- 令牌桶速率限制
- 请求追踪（request_id）
"""
import time
from collections import defaultdict, deque
from typing import Optional

from fastapi import HTTPException, Request, Response
from fastapi.security import APIKeyHeader
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from logger import get_logger, new_request_id, set_request_context
from config import get_settings

logger = get_logger(__name__)


# ============ API Key 鉴权 ============

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


class AuthMiddleware(BaseHTTPMiddleware):
    """API Key 鉴权中间件"""

    # 不需要鉴权的路径
    PUBLIC_PATHS = {"/health", "/metrics", "/docs", "/redoc", "/openapi.json"}

    def __init__(self, app, tenant_manager=None):
        super().__init__(app)
        self.tenant_manager = tenant_manager

    async def dispatch(self, request: Request, call_next):
        settings = get_settings()

        # 公开路径跳过
        if request.url.path in self.PUBLIC_PATHS:
            return await call_next(request)

        # 未启用鉴权
        if not settings.api_key_enabled:
            return await call_next(request)

        # 获取 API Key
        api_key = request.headers.get("X-API-Key")
        if not api_key:
            return JSONResponse(
                status_code=401,
                content={"detail": "缺少 API Key，请在 X-API-Key 头中提供"},
            )

        # 验证 API Key
        tenant = None
        if self.tenant_manager:
            tenant = self.tenant_manager.authenticate(api_key)

        if not tenant:
            return JSONResponse(
                status_code=403,
                content={"detail": "无效的 API Key 或租户已禁用"},
            )

        # 设置租户上下文
        set_request_context(tenant_id=tenant.tenant_id)
        request.state.tenant = tenant

        # 检查 Agent 访问权限（针对编排端点）
        if "/orchestrate" in request.url.path:
            # 所有租户都可以访问编排，但 Agent 内部会检查
            pass

        response = await call_next(request)
        response.headers["X-Tenant-Id"] = tenant.tenant_id
        return response


# ============ 速率限制（令牌桶） ============

class TokenBucket:
    """令牌桶速率限制器"""

    def __init__(self, rate: float, burst: int):
        """
        Args:
            rate: 每秒令牌生成速率
            burst: 桶容量（突发上限）
        """
        self.rate = rate
        self.burst = burst
        self.tokens = burst
        self.last_update = time.time()
        self._lock = None

    def consume(self, tokens: int = 1) -> bool:
        """消费令牌"""
        now = time.time()
        # 补充令牌
        elapsed = now - self.last_update
        self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
        self.last_update = now

        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False

    def get_status(self) -> dict:
        """获取状态"""
        return {
            "rate": self.rate,
            "burst": self.burst,
            "tokens_remaining": round(self.tokens, 2),
        }


class RateLimitMiddleware(BaseHTTPMiddleware):
    """速率限制中间件（基于客户端 IP）"""

    # 不需要限流的路径
    EXEMPT_PATHS = {"/health", "/metrics"}

    def __init__(self, app, requests_per_minute: int = 60, burst: int = 10):
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self.burst = burst
        self.buckets: dict[str, TokenBucket] = {}
        self._cleanup_counter = 0

    async def dispatch(self, request: Request, call_next):
        settings = get_settings()

        # 未启用或豁免路径
        if not settings.rate_limit_enabled or request.url.path in self.EXEMPT_PATHS:
            return await call_next(request)

        # 获取客户端标识（API Key 优先，否则用 IP）
        client_id = request.headers.get("X-API-Key") or request.client.host

        # 获取或创建令牌桶
        if client_id not in self.buckets:
            self.buckets[client_id] = TokenBucket(
                rate=settings.rate_limit_requests / 60.0,  # 转换为每秒
                burst=settings.rate_limit_burst,
            )

        bucket = self.buckets[client_id]

        # 消费令牌
        if not bucket.consume():
            retry_after = int(60 / settings.rate_limit_requests)
            logger.warning(f"速率限制触发: client={client_id}")
            return JSONResponse(
                status_code=429,
                content={
                    "detail": f"请求过于频繁，请 {retry_after} 秒后重试",
                    "retry_after": retry_after,
                },
                headers={"Retry-After": str(retry_after)},
            )

        # 定期清理过期桶
        self._cleanup_counter += 1
        if self._cleanup_counter > 1000:
            self._cleanup_buckets()
            self._cleanup_counter = 0

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(settings.rate_limit_requests)
        response.headers["X-RateLimit-Remaining"] = str(int(bucket.tokens))
        return response

    def _cleanup_buckets(self):
        """清理长时间未使用的桶"""
        now = time.time()
        expired = [
            cid for cid, bucket in self.buckets.items()
            if now - bucket.last_update > 3600  # 1 小时未使用
        ]
        for cid in expired:
            del self.buckets[cid]
        if expired:
            logger.info(f"清理 {len(expired)} 个过期速率限制桶")


# ============ 请求追踪中间件 ============

class RequestTracingMiddleware(BaseHTTPMiddleware):
    """请求追踪中间件（添加 request_id）"""

    async def dispatch(self, request: Request, call_next):
        # 生成或复用 request_id
        request_id = request.headers.get("X-Request-ID") or new_request_id()
        set_request_context(request_id=request_id)

        start_time = time.time()
        logger.info(f"请求开始: {request.method} {request.url.path}")

        response = await call_next(request)

        duration = time.time() - start_time
        logger.info(
            f"请求完成: {request.method} {request.url.path} "
            f"status={response.status_code} duration={duration:.3f}s"
        )

        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time"] = f"{duration:.3f}s"
        return response


# ============ CORS 中间件 ============

class CORSMiddleware(BaseHTTPMiddleware):
    """简化的 CORS 中间件"""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-API-Key, X-Request-ID"
        response.headers["Access-Control-Expose-Headers"] = "X-Request-ID, X-Response-Time, X-RateLimit-Remaining"
        return response
