"""
Prometheus 指标采集 - 生产级监控指标
基于 prometheus_client，暴露 /metrics 端点
"""
import time
from functools import wraps
from typing import Callable

try:
    from prometheus_client import (
        Counter, Histogram, Gauge, Summary,
        CollectorRegistry, generate_latest, CONTENT_TYPE_LATEST,
        start_http_server,
    )
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False


# 自定义注册表（避免与全局注册表冲突）
REGISTRY = CollectorRegistry() if PROMETHEUS_AVAILABLE else None


if PROMETHEUS_AVAILABLE:
    # ============ 业务指标 ============

    # 视频生成总数
    videos_total = Counter(
        "kickart_videos_total",
        "Total videos generated",
        ["workflow_type", "status", "tenant_id"],
        registry=REGISTRY,
    )

    # 图片生成总数
    images_total = Counter(
        "kickart_images_total",
        "Total images generated",
        ["scene", "status", "tenant_id"],
        registry=REGISTRY,
    )

    # 工作流执行耗时
    workflow_duration = Histogram(
        "kickart_workflow_duration_seconds",
        "Workflow execution duration in seconds",
        ["workflow_type", "status"],
        buckets=[1, 5, 10, 30, 60, 120, 300, 600, 1200],
        registry=REGISTRY,
    )

    # Agent 执行耗时
    agent_duration = Histogram(
        "kickart_agent_duration_seconds",
        "Agent execution duration in seconds",
        ["agent_name", "status"],
        buckets=[0.1, 0.5, 1, 5, 10, 30, 60, 120],
        registry=REGISTRY,
    )

    # Agent 成功率
    agent_success_total = Counter(
        "kickart_agent_success_total",
        "Total successful agent executions",
        ["agent_name"],
        registry=REGISTRY,
    )
    agent_failure_total = Counter(
        "kickart_agent_failure_total",
        "Total failed agent executions",
        ["agent_name"],
        registry=REGISTRY,
    )
    agent_degraded_total = Counter(
        "kickart_agent_degraded_total",
        "Total degraded agent executions",
        ["agent_name"],
        registry=REGISTRY,
    )

    # 活跃工作流数
    active_workflows = Gauge(
        "kickart_active_workflows",
        "Number of active workflows",
        registry=REGISTRY,
    )

    # 队列大小
    queue_size = Gauge(
        "kickart_queue_size",
        "Task queue size",
        registry=REGISTRY,
    )

    # API 请求指标
    api_requests_total = Counter(
        "kickart_api_requests_total",
        "Total API requests",
        ["method", "endpoint", "status"],
        registry=REGISTRY,
    )
    api_request_duration = Histogram(
        "kickart_api_request_duration_seconds",
        "API request duration in seconds",
        ["method", "endpoint"],
        buckets=[0.01, 0.05, 0.1, 0.5, 1, 5, 10, 30],
        registry=REGISTRY,
    )

    # 资源使用
    storage_usage = Gauge(
        "kickart_storage_usage_bytes",
        "Storage usage in bytes",
        ["type"],
        registry=REGISTRY,
    )

else:
    # 回退：无操作占位
    class _NoopMetric:
        def labels(self, *args, **kwargs): return self
        def inc(self, *args, **kwargs): pass
        def observe(self, *args, **kwargs): pass
        def set(self, *args, **kwargs): pass
        def time(self): return self
        def __enter__(self): return self
        def __exit__(self, *args): pass

    videos_total = images_total = workflow_duration = agent_duration = _NoopMetric()
    agent_success_total = agent_failure_total = agent_degraded_total = _NoopMetric()
    active_workflows = queue_size = _NoopMetric()
    api_requests_total = api_request_duration = storage_usage = _NoopMetric()


# ============ 便捷装饰器 ============

def track_agent_execution(agent_name: str):
    """装饰器：追踪 Agent 执行"""
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start = time.time()
            try:
                result = func(*args, **kwargs)
                duration = time.time() - start
                agent_duration.labels(agent_name=agent_name, status="success").observe(duration)
                agent_success_total.labels(agent_name=agent_name).inc()
                return result
            except Exception as e:
                duration = time.time() - start
                agent_duration.labels(agent_name=agent_name, status="failure").observe(duration)
                agent_failure_total.labels(agent_name=agent_name).inc()
                raise
        return wrapper
    return decorator


def track_workflow(workflow_type: str):
    """装饰器：追踪工作流执行"""
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start = time.time()
            active_workflows.inc()
            try:
                result = func(*args, **kwargs)
                duration = time.time() - start
                status = "success" if result.get("success", True) else "failed"
                workflow_duration.labels(workflow_type=workflow_type, status=status).observe(duration)
                videos_total.labels(workflow_type=workflow_type, status=status, tenant_id="default").inc()
                return result
            except Exception as e:
                duration = time.time() - start
                workflow_duration.labels(workflow_type=workflow_type, status="error").observe(duration)
                videos_total.labels(workflow_type=workflow_type, status="error", tenant_id="default").inc()
                raise
            finally:
                active_workflows.dec()
        return wrapper
    return decorator


def track_api_request(method: str, endpoint: str):
    """装饰器：追踪 API 请求"""
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start = time.time()
            try:
                result = func(*args, **kwargs)
                duration = time.time() - start
                status = str(getattr(result, "status_code", 200))
                api_requests_total.labels(method=method, endpoint=endpoint, status=status).inc()
                api_request_duration.labels(method=method, endpoint=endpoint).observe(duration)
                return result
            except Exception as e:
                duration = time.time() - start
                api_requests_total.labels(method=method, endpoint=endpoint, status="500").inc()
                api_request_duration.labels(method=method, endpoint=endpoint).observe(duration)
                raise
        return wrapper
    return decorator


def get_metrics():
    """获取 Prometheus 格式指标数据"""
    if PROMETHEUS_AVAILABLE:
        return generate_latest(REGISTRY)
    return b""


def get_metrics_content_type():
    """获取指标 Content-Type"""
    if PROMETHEUS_AVAILABLE:
        return CONTENT_TYPE_LATEST
    return "text/plain"
