"""
结构化日志系统 - 生产级可观测性
基于标准库 logging + JSON 格式化，支持结构化字段、请求追踪、性能指标
"""
import json
import logging
import logging.handlers
import os
import sys
import time
import uuid
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path


# 请求上下文（用于追踪）
request_id_var: ContextVar[str] = ContextVar("request_id", default="")
tenant_id_var: ContextVar[str] = ContextVar("tenant_id", default="")


class StructuredFormatter(logging.Formatter):
    """JSON 结构化日志格式化器"""

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # 请求上下文
        req_id = request_id_var.get()
        if req_id:
            log_data["request_id"] = req_id
        tenant_id = tenant_id_var.get()
        if tenant_id:
            log_data["tenant_id"] = tenant_id

        # 异常信息
        if record.exc_info:
            log_data["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
                "traceback": self.formatException(record.exc_info),
            }

        # 额外字段
        for key, value in record.__dict__.items():
            if key not in {
                "name", "msg", "args", "levelname", "levelno", "pathname",
                "filename", "module", "exc_info", "exc_text", "stack_info",
                "lineno", "funcName", "created", "msecs", "relativeCreated",
                "thread", "threadName", "processName", "process", "getMessage",
                "message",
            }:
                try:
                    json.dumps(value)
                    log_data[key] = value
                except (TypeError, ValueError):
                    log_data[key] = str(value)

        return json.dumps(log_data, ensure_ascii=False)


class ConsoleFormatter(logging.Formatter):
    """控制台彩色格式化器（开发环境）"""

    COLORS = {
        "DEBUG": "\033[36m",    # cyan
        "INFO": "\033[32m",     # green
        "WARNING": "\033[33m",  # yellow
        "ERROR": "\033[31m",    # red
        "CRITICAL": "\033[35m", # magenta
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, "")
        req_id = request_id_var.get()
        req_str = f" [{req_id[:8]}]" if req_id else ""
        msg = record.getMessage()
        return (
            f"{color}{datetime.now().strftime('%H:%M:%S')}{self.RESET} "
            f"{color}{record.levelname:<8}{self.RESET} "
            f"{record.name:<20} "
            f"{req_str} {msg}"
        )


def setup_logging(
    level: str = "INFO",
    json_output: bool = False,
    log_file: str = None,
    max_file_size: int = 50 * 1024 * 1024,  # 50MB
    backup_count: int = 5,
):
    """
    初始化日志系统

    Args:
        level: 日志级别
        json_output: 是否输出 JSON 格式（生产环境）
        log_file: 日志文件路径（None 则不写文件）
        max_file_size: 单文件最大大小
        backup_count: 保留备份数
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # 清除已有 handlers
    root_logger.handlers.clear()

    # 控制台 handler
    console_handler = logging.StreamHandler(sys.stdout)
    if json_output:
        console_handler.setFormatter(StructuredFormatter())
    else:
        console_handler.setFormatter(ConsoleFormatter())
    root_logger.addHandler(console_handler)

    # 文件 handler
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=max_file_size,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(StructuredFormatter())
        root_logger.addHandler(file_handler)

    # 降低第三方库日志级别
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """获取命名 logger"""
    return logging.getLogger(name)


def set_request_context(request_id: str = None, tenant_id: str = None):
    """设置请求上下文（用于日志追踪）"""
    if request_id is not None:
        request_id_var.set(request_id)
    if tenant_id is not None:
        tenant_id_var.set(tenant_id)


def new_request_id() -> str:
    """生成新的请求 ID"""
    req_id = f"req_{uuid.uuid4().hex[:12]}"
    request_id_var.set(req_id)
    return req_id


class LoggerMixin:
    """为类添加 logger 的 Mixin"""

    @property
    def logger(self) -> logging.Logger:
        if not hasattr(self, "_logger"):
            self._logger = get_logger(self.__class__.__name__)
        return self._logger
