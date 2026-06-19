"""
配置管理 - 基于 pydantic-settings 的类型安全配置
支持环境变量、.env 文件、默认值
"""
import os
from pathlib import Path
from typing import Optional

try:
    from pydantic_settings import BaseSettings
    from pydantic import Field
except ImportError:
    # 回退：使用 dataclass 模拟
    from dataclasses import dataclass as _dataclass

    class BaseSettings:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    def Field(default=None, **kwargs):
        return default


class Settings(BaseSettings):
    """应用全局配置"""

    # ============ 应用配置 ============
    app_name: str = Field(default="kickart-clone", description="应用名称")
    app_version: str = Field(default="1.0.0", description="应用版本")
    debug: bool = Field(default=False, description="调试模式")
    environment: str = Field(default="development", description="运行环境")

    # ============ API 服务配置 ============
    api_host: str = Field(default="0.0.0.0", description="API 监听地址")
    api_port: int = Field(default=8765, description="API 监听端口")
    api_workers: int = Field(default=4, description="API 工作进程数")
    api_timeout: int = Field(default=300, description="API 请求超时（秒）")

    # ============ 日志配置 ============
    log_level: str = Field(default="INFO", description="日志级别")
    log_format: str = Field(default="console", description="日志格式：console/json")
    log_file: Optional[str] = Field(default=None, description="日志文件路径")

    # ============ Stable Diffusion 配置 ============
    sd_webui_url: str = Field(default="http://localhost:7860", description="SD WebUI 地址")
    sd_timeout: int = Field(default=120, description="SD 请求超时（秒）")
    sd_max_concurrent: int = Field(default=2, description="SD 最大并发数")

    # ============ Lead Agent 配置 ============
    lead_agent_output_dir: str = Field(
        default="/mnt/user-data/workspace/lead_agent_runs",
        description="Lead Agent 输出目录",
    )
    lead_agent_max_retries: int = Field(default=3, description="最大重试次数")
    lead_agent_task_timeout: int = Field(default=120, description="单任务超时（秒）")

    # ============ 视频合成配置 ============
    video_output_dir: str = Field(
        default="/mnt/user-data/workspace/videos",
        description="视频输出目录",
    )
    video_default_fps: int = Field(default=25, description="默认帧率")
    video_default_resolution: str = Field(default="1080x1920", description="默认分辨率")
    video_default_bitrate: str = Field(default="2M", description="默认码率")

    # ============ TTS 配置 ============
    tts_output_dir: str = Field(
        default="/mnt/user-data/workspace/audio",
        description="TTS 输出目录",
    )
    tts_default_voice: str = Field(default="xiaoxiao", description="默认音色")
    tts_default_rate: str = Field(default="+0%", description="默认语速")

    # ============ 平台配置 ============
    jnpf_output_dir: str = Field(
        default="/mnt/user-data/workspace/jnpf",
        description="JNPF 配置输出目录",
    )
    compound_registry_dir: str = Field(
        default="/mnt/user-data/workspace/compound_registry",
        description="复利资产注册表目录",
    )
    tenant_storage_dir: str = Field(
        default="/mnt/user-data/workspace/tenants",
        description="租户数据目录",
    )
    monitoring_storage_dir: str = Field(
        default="/mnt/user-data/workspace/monitoring",
        description="监控数据目录",
    )

    # ============ 安全配置 ============
    api_key_enabled: bool = Field(default=False, description="是否启用 API Key 鉴权")
    rate_limit_enabled: bool = Field(default=True, description="是否启用速率限制")
    rate_limit_requests: int = Field(default=60, description="每分钟请求限制")
    rate_limit_burst: int = Field(default=10, description="突发请求限制")

    # ============ 性能配置 ============
    max_concurrent_workflows: int = Field(default=5, description="最大并发工作流")
    task_queue_size: int = Field(default=100, description="任务队列大小")
    enable_sse: bool = Field(default=True, description="是否启用 SSE 进度推送")

    # ============ 监控配置 ============
    metrics_enabled: bool = Field(default=True, description="是否启用 Prometheus 指标")
    metrics_path: str = Field(default="/metrics", description="指标暴露路径")

    # ============ LLM 多提供商配置 ============
    llm_strategy: str = Field(default="failover", description="路由策略：failover/round_robin/least_used/random")
    llm_default_purpose: str = Field(default="aigc_marketing", description="默认用途")
    llm_breaker_enabled: bool = Field(default=True, description="是否启用熔断器")
    llm_breaker_threshold: int = Field(default=3, description="熔断阈值（连续失败次数）")
    llm_breaker_cooldown: int = Field(default=60, description="熔断冷却时间（秒）")
    llm_default_temperature: float = Field(default=0.8, description="默认温度")
    llm_default_max_tokens: int = Field(default=2000, description="默认最大 tokens")

    class Config:
        env_prefix = "KICKART_"  # 环境变量前缀
        env_file = ".env"
        case_sensitive = False


# 全局配置单例
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """获取全局配置单例"""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reload_settings():
    """重新加载配置（用于测试）"""
    global _settings
    _settings = Settings()
    return _settings


# 便捷访问
def is_production() -> bool:
    return get_settings().environment == "production"


def is_debug() -> bool:
    return get_settings().debug
