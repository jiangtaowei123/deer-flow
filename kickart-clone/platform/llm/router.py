"""
LLM 智能路由层
核心能力：
1. 按用途路由 - 根据业务场景选择对应 Key（JNPF团队/跨境电商/AIGC中台/图片生成）
2. 故障转移 - 主 Key 失败自动切换备用 Key
3. 多 Key 轮询 - 同用途多 Key 负载均衡
4. 健康检查 - 自动熔断不可用提供商
5. 用量统计 - 按 Key/用途/模型维度统计
6. 成本优化 - 优先 flash/lite 模型，按需升级 pro
基于用户提供的 7 个 API Key 清单设计路由策略
"""
import json
import os
import sys
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

# 添加路径
_PLATFORM_LLM_PATH = Path(__file__).parent
if str(_PLATFORM_LLM_PATH) not in sys.path:
    sys.path.insert(0, str(_PLATFORM_LLM_PATH))

from providers import (
    PROVIDER_REGISTRY, PURPOSE_PROVIDERS,
    TextProvider, ImageProvider,
    create_provider, list_providers,
)


# ============================================================================
# 路由策略
# ============================================================================

class RouteStrategy(str):
    """路由策略"""
    FAILOVER = "failover"       # 故障转移（主→备）
    ROUND_ROBIN = "round_robin"  # 轮询负载均衡
    LEAST_USED = "least_used"    # 最少使用
    RANDOM = "random"            # 随机


# ============================================================================
# 熔断器
# ============================================================================

class CircuitBreaker:
    """
    熔断器
    连续失败 N 次后熔断，冷却期后半开试探
    """

    def __init__(self, failure_threshold: int = 3, cooldown_sec: int = 60):
        self.failure_threshold = failure_threshold
        self.cooldown_sec = cooldown_sec
        self._failure_count: dict[str, int] = defaultdict(int)  # provider_id -> count
        self._open_until: dict[str, float] = {}  # provider_id -> timestamp

    def is_open(self, provider_id: str) -> bool:
        """是否熔断中"""
        until = self._open_until.get(provider_id, 0)
        if until > time.time():
            return True
        if until > 0 and until <= time.time():
            # 冷却期结束，半开（重置计数）
            self._failure_count[provider_id] = 0
            del self._open_until[provider_id]
        return False

    def record_failure(self, provider_id: str):
        """记录失败"""
        self._failure_count[provider_id] += 1
        if self._failure_count[provider_id] >= self.failure_threshold:
            self._open_until[provider_id] = time.time() + self.cooldown_sec

    def record_success(self, provider_id: str):
        """记录成功"""
        self._failure_count[provider_id] = 0
        self._open_until.pop(provider_id, None)

    def get_state(self, provider_id: str) -> dict:
        return {
            "provider_id": provider_id,
            "failure_count": self._failure_count[provider_id],
            "is_open": self.is_open(provider_id),
            "open_until": datetime.fromtimestamp(self._open_until[provider_id]).isoformat()
            if provider_id in self._open_until else None,
        }


# ============================================================================
# 用量统计
# ============================================================================

@dataclass
class UsageRecord:
    """用量记录"""
    timestamp: float
    provider_id: str
    purpose: str
    model: str
    tokens: int = 0
    success: bool = True
    latency_ms: int = 0
    error: str = ""


class UsageTracker:
    """用量统计器"""

    def __init__(self, max_records: int = 10000):
        self.max_records = max_records
        self._records: deque = deque(maxlen=max_records)
        self._lock = threading.Lock()

    def record(self, record: UsageRecord):
        with self._lock:
            self._records.append(record)

    def get_stats(self, group_by: str = "provider") -> dict:
        """获取统计（按 provider/purpose/model 分组）"""
        with self._lock:
            records = list(self._records)

        stats: dict[str, dict] = defaultdict(lambda: {
            "total_calls": 0, "success_calls": 0, "failed_calls": 0,
            "total_tokens": 0, "total_latency_ms": 0,
        })

        for r in records:
            key = getattr(r, group_by, "unknown")
            s = stats[key]
            s["total_calls"] += 1
            if r.success:
                s["success_calls"] += 1
            else:
                s["failed_calls"] += 1
            s["total_tokens"] += r.tokens
            s["total_latency_ms"] += r.latency_ms

        # 计算平均值
        result = {}
        for key, s in stats.items():
            result[key] = {
                **s,
                "success_rate": round(s["success_calls"] / s["total_calls"], 3) if s["total_calls"] > 0 else 0,
                "avg_latency_ms": round(s["total_latency_ms"] / s["total_calls"]) if s["total_calls"] > 0 else 0,
                "avg_tokens": round(s["total_tokens"] / s["total_calls"]) if s["total_calls"] > 0 else 0,
            }
        return result

    def get_recent(self, limit: int = 50) -> list:
        with self._lock:
            recent = list(self._records)[-limit:]
        return [
            {
                "timestamp": datetime.fromtimestamp(r.timestamp).isoformat(),
                "provider_id": r.provider_id,
                "purpose": r.purpose,
                "model": r.model,
                "tokens": r.tokens,
                "success": r.success,
                "latency_ms": r.latency_ms,
                "error": r.error,
            }
            for r in reversed(recent)
        ]


# ============================================================================
# 智能路由器
# ============================================================================

class LLMRouter:
    """
    LLM 智能路由器
    - 按用途路由到对应提供商
    - 故障转移 + 负载均衡
    - 熔断保护
    - 用量统计
    """

    def __init__(
        self,
        strategy: str = RouteStrategy.FAILOVER,
        keys: dict = None,
        enable_breaker: bool = True,
    ):
        """
        Args:
            strategy: 路由策略
            keys: 显式传入的 Key 字典 {provider_id: api_key}，不传则从环境变量读
            enable_breaker: 是否启用熔断器
        """
        self.strategy = strategy
        self.keys = keys or {}
        self.enable_breaker = enable_breaker
        self.breaker = CircuitBreaker() if enable_breaker else None
        self.usage = UsageTracker()

        # 提供商实例缓存
        self._providers: dict[str, TextProvider] = {}
        self._image_providers: dict[str, ImageProvider] = {}

        # 轮询指针
        self._rr_index: dict[str, int] = defaultdict(int)
        self._lock = threading.Lock()

        # 初始化所有提供商
        self._init_providers()

    def _init_providers(self):
        """初始化所有提供商实例"""
        for pid, meta in PROVIDER_REGISTRY.items():
            key = self.keys.get(pid) or os.environ.get(meta.key_env, "")
            if meta.provider_type == "text":
                self._providers[pid] = TextProvider(meta, api_key=key)
            elif meta.provider_type == "image":
                self._image_providers[pid] = ImageProvider(meta, api_key=key)

    # ============ 文本生成路由 ============

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        purpose: str = "default",
        temperature: float = 0.8,
        max_tokens: int = 2000,
        model: str = None,
        preferred_provider: str = None,
    ) -> dict:
        """
        智能路由文本生成
        Args:
            purpose: 业务用途（jnpf_team/cross_border_ecommerce/aigc_marketing/default）
            model: 指定模型（不传则用提供商默认）
            preferred_provider: 指定提供商 ID（优先使用）
        Returns:
            {"text": str, "provider_id": str, "model": str, "latency_ms": int, "tokens": int}
        """
        # 获取该用途的可用提供商列表
        candidate_ids = self._get_candidates(purpose, preferred_provider)

        if not candidate_ids:
            return {
                "text": "",
                "provider_id": None,
                "model": None,
                "error": f"用途 '{purpose}' 无可用提供商（未配置 Key）",
                "latency_ms": 0,
                "tokens": 0,
            }

        # 按策略排序候选
        ordered = self._order_candidates(candidate_ids, purpose)

        last_error = ""
        for pid in ordered:
            provider = self._providers.get(pid)
            if not provider or not provider.is_available():
                continue

            # 熔断检查
            if self.breaker and self.breaker.is_open(pid):
                continue

            start = time.time()
            try:
                text = provider.generate(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    model=model,
                )
                latency_ms = int((time.time() - start) * 1000)

                # 记录成功
                if self.breaker:
                    self.breaker.record_success(pid)

                # 估算 tokens（如果提供商没返回）
                tokens = provider._total_tokens  # 累计值，这里取增量需改进
                # 简单估算：字符数/4
                est_tokens = len(text) // 4

                self.usage.record(UsageRecord(
                    timestamp=time.time(),
                    provider_id=pid,
                    purpose=purpose,
                    model=model or provider.model,
                    tokens=est_tokens,
                    success=True,
                    latency_ms=latency_ms,
                ))

                return {
                    "text": text,
                    "provider_id": pid,
                    "provider_name": provider.meta.name,
                    "model": model or provider.model,
                    "latency_ms": latency_ms,
                    "tokens": est_tokens,
                }

            except Exception as e:
                latency_ms = int((time.time() - start) * 1000)
                last_error = str(e)
                provider.record_error(last_error)

                if self.breaker:
                    self.breaker.record_failure(pid)

                self.usage.record(UsageRecord(
                    timestamp=time.time(),
                    provider_id=pid,
                    purpose=purpose,
                    model=model or provider.model,
                    success=False,
                    latency_ms=latency_ms,
                    error=last_error,
                ))
                continue

        return {
            "text": "",
            "provider_id": None,
            "model": None,
            "error": f"所有提供商均失败，最后错误: {last_error}",
            "latency_ms": 0,
            "tokens": 0,
        }

    # ============ 图片生成路由 ============

    def generate_image(
        self,
        prompt: str,
        purpose: str = "image_generation",
        width: int = 1024,
        height: int = 1024,
        seed: int = 0,
        model: str = None,
    ) -> dict:
        """
        智能路由图片生成
        Returns:
            {"image_base64": str, "provider_id": str, "model": str, ...}
        """
        candidate_ids = PURPOSE_PROVIDERS.get(purpose, PURPOSE_PROVIDERS["image_generation"])

        last_error = ""
        for pid in candidate_ids:
            provider = self._image_providers.get(pid)
            if not provider or not provider.is_available():
                continue
            if self.breaker and self.breaker.is_open(pid):
                continue

            try:
                result = provider.generate_image(
                    prompt=prompt,
                    width=width,
                    height=height,
                    seed=seed,
                    model=model,
                )
                result["provider_id"] = pid
                result["provider_name"] = provider.meta.name
                result["model"] = model or provider.model

                if self.breaker:
                    self.breaker.record_success(pid)

                self.usage.record(UsageRecord(
                    timestamp=time.time(),
                    provider_id=pid,
                    purpose=purpose,
                    model=result["model"],
                    success=True,
                ))
                return result

            except Exception as e:
                last_error = str(e)
                provider.record_error(last_error)
                if self.breaker:
                    self.breaker.record_failure(pid)
                continue

        return {"image_base64": "", "error": f"图片生成失败: {last_error}"}

    # ============ 候选选择 ============

    def _get_candidates(self, purpose: str, preferred: str = None) -> list:
        """获取候选提供商列表"""
        if preferred and preferred in self._providers:
            # 指定提供商优先
            candidates = PURPOSE_PROVIDERS.get(purpose, PURPOSE_PROVIDERS["default"]).copy()
            if preferred in candidates:
                candidates.remove(preferred)
            return [preferred] + candidates

        return PURPOSE_PROVIDERS.get(purpose, PURPOSE_PROVIDERS["default"]).copy()

    def _order_candidates(self, candidate_ids: list, purpose: str) -> list:
        """按策略排序候选"""
        # 过滤掉熔断中的
        available = [
            pid for pid in candidate_ids
            if not (self.breaker and self.breaker.is_open(pid))
        ]
        if not available:
            return candidate_ids  # 全熔断时返回原列表（最后挣扎）

        if self.strategy == RouteStrategy.ROUND_ROBIN:
            with self._lock:
                idx = self._rr_index[purpose] % len(available)
                self._rr_index[purpose] += 1
                first = available[idx]
                return [first] + [p for p in available if p != first]

        elif self.strategy == RouteStrategy.LEAST_USED:
            stats = self.usage.get_stats("provider_id")
            return sorted(available, key=lambda p: stats.get(p, {}).get("total_calls", 0))

        elif self.strategy == RouteStrategy.RANDOM:
            import random
            shuffled = available.copy()
            random.shuffle(shuffled)
            return shuffled

        else:  # FAILOVER（默认顺序）
            return available

    # ============ 查询接口 ============

    def get_available_providers(self, purpose: str = None) -> list:
        """获取可用提供商"""
        result = []
        for pid, provider in {**self._providers, **self._image_providers}.items():
            if purpose and provider.meta.purpose != purpose:
                continue
            stats = provider.get_stats()
            stats["breaker"] = self.breaker.get_state(pid) if self.breaker else None
            result.append(stats)
        return result

    def get_usage_stats(self, group_by: str = "provider_id") -> dict:
        """获取用量统计"""
        return self.usage.get_stats(group_by)

    def get_recent_calls(self, limit: int = 50) -> list:
        """获取最近调用记录"""
        return self.usage.get_recent(limit)

    def get_router_status(self) -> dict:
        """获取路由器整体状态"""
        all_providers = list(PROVIDER_REGISTRY.keys())
        available = [
            pid for pid in all_providers
            if (pid in self._providers and self._providers[pid].is_available())
            or (pid in self._image_providers and self._image_providers[pid].is_available())
        ]
        broken = [
            pid for pid in all_providers
            if self.breaker and self.breaker.is_open(pid)
        ]
        return {
            "strategy": self.strategy,
            "total_providers": len(all_providers),
            "available_providers": len(available),
            "broken_providers": len(broken),
            "available_list": available,
            "broken_list": broken,
            "purposes": list(PURPOSE_PROVIDERS.keys()),
            "breaker_enabled": self.enable_breaker,
        }


# ============================================================================
# 全局单例
# ============================================================================

_router: Optional[LLMRouter] = None


def get_router() -> LLMRouter:
    """获取全局路由器单例"""
    global _router
    if _router is None:
        _router = LLMRouter()
    return _router


def reset_router():
    """重置路由器（用于测试）"""
    global _router
    _router = None


# ============================================================================
# CLI 入口
# ============================================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(description="LLM 智能路由层")
    parser.add_argument("--action", required=True,
                        choices=["status", "providers", "usage", "recent", "generate", "breakers"])
    parser.add_argument("--purpose", default="default")
    parser.add_argument("--prompt")
    parser.add_argument("--system-prompt", default="你是营销创意助手")
    parser.add_argument("--model")
    parser.add_argument("--preferred")
    parser.add_argument("--strategy", default="failover",
                        choices=["failover", "round_robin", "least_used", "random"])
    parser.add_argument("--group-by", default="provider_id",
                        choices=["provider_id", "purpose", "model"])

    args = parser.parse_args()
    router = LLMRouter(strategy=args.strategy)

    if args.action == "status":
        print(json.dumps(router.get_router_status(), ensure_ascii=False, indent=2))

    elif args.action == "providers":
        print(json.dumps(router.get_available_providers(args.purpose), ensure_ascii=False, indent=2))

    elif args.action == "usage":
        print(json.dumps(router.get_usage_stats(args.group_by), ensure_ascii=False, indent=2))

    elif args.action == "recent":
        print(json.dumps(router.get_recent_calls(), ensure_ascii=False, indent=2))

    elif args.action == "generate":
        if not args.prompt:
            print("错误: 需要 --prompt")
            return 1
        result = router.generate(
            system_prompt=args.system_prompt,
            user_prompt=args.prompt,
            purpose=args.purpose,
            model=args.model,
            preferred_provider=args.preferred,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result.get("error"):
            return 1

    elif args.action == "breakers":
        states = []
        for pid in PROVIDER_REGISTRY:
            if router.breaker:
                states.append(router.breaker.get_state(pid))
        print(json.dumps(states, ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    exit(main())
