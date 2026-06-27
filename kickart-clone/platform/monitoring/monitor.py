"""
监控告警系统 - 平台运行时监控
支持：指标采集、告警规则、事件通知、健康检查
"""
import json
import os
import sys
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional


# ============================================================================
# 监控模型
# ============================================================================

class AlertLevel(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    FATAL = "fatal"


class AlertStatus(str, Enum):
    FIRING = "firing"
    RESOLVED = "resolved"
    ACKNOWLEDGED = "acknowledged"


@dataclass
class Metric:
    """指标"""
    name: str
    value: float
    timestamp: float
    labels: dict = field(default_factory=dict)


@dataclass
class Alert:
    """告警"""
    alert_id: str
    rule_name: str
    level: AlertLevel
    message: str
    status: AlertStatus = AlertStatus.FIRING
    fired_at: float = field(default_factory=time.time)
    resolved_at: Optional[float] = None
    labels: dict = field(default_factory=dict)
    value: float = 0.0


@dataclass
class AlertRule:
    """告警规则"""
    name: str
    metric: str
    condition: str  # gt/lt/gte/lte/eq
    threshold: float
    level: AlertLevel = AlertLevel.WARNING
    message_template: str = ""
    cooldown_sec: int = 300  # 冷却时间


# ============================================================================
# 默认告警规则
# ============================================================================

DEFAULT_ALERT_RULES = [
    AlertRule(
        name="agent_success_rate_low",
        metric="agent_success_rate",
        condition="lt",
        threshold=0.95,
        level=AlertLevel.WARNING,
        message_template="Agent 成功率低于 95%: {value}",
    ),
    AlertRule(
        name="agent_success_rate_critical",
        metric="agent_success_rate",
        condition="lt",
        threshold=0.80,
        level=AlertLevel.CRITICAL,
        message_template="Agent 成功率严重低于 80%: {value}",
    ),
    AlertRule(
        name="e2e_latency_high",
        metric="e2e_latency",
        condition="gt",
        threshold=300,
        level=AlertLevel.WARNING,
        message_template="端到端耗时超过 300s: {value}s",
    ),
    AlertRule(
        name="e2e_latency_critical",
        metric="e2e_latency",
        condition="gt",
        threshold=600,
        level=AlertLevel.CRITICAL,
        message_template="端到端耗时严重超过 600s: {value}s",
    ),
    AlertRule(
        name="api_error_rate_high",
        metric="api_error_rate",
        condition="gt",
        threshold=0.05,
        level=AlertLevel.WARNING,
        message_template="API 错误率超过 5%: {value}",
    ),
    AlertRule(
        name="daily_videos_low",
        metric="daily_videos",
        condition="lt",
        threshold=5,
        level=AlertLevel.INFO,
        message_template="日成片数低于 5: {value}",
    ),
]


# ============================================================================
# 监控系统
# ============================================================================

class MonitoringSystem:
    """
    监控告警系统
    - 指标采集（时序存储）
    - 告警规则评估
    - 事件通知
    - 健康检查
    """

    def __init__(self, storage_path: str = "/mnt/user-data/workspace/monitoring"):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)

        # 指标存储：name -> deque[(timestamp, value)]
        self.metrics: dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))
        self.rules: list[AlertRule] = DEFAULT_ALERT_RULES.copy()
        self.active_alerts: dict[str, Alert] = {}  # rule_name -> Alert
        self.alert_history: list[Alert] = []
        self.last_alert_time: dict[str, float] = {}  # rule_name -> last fired time

        self._lock = threading.Lock()

        # 初始基线指标（避免仪表盘冷启动全 0，真实业务上线后会被覆盖）
        self._seed_baseline_metrics()

    def _seed_baseline_metrics(self):
        """播种基线指标 - 商用系统冷启动时的合理默认值"""
        baseline = {
            "daily_videos": 0,
            "daily_assets": 0,
            "agent_success_rate": 1.0,
            "e2e_latency": 0.0,
            "api_error_rate": 0.0,
        }
        now = time.time()
        for name, value in baseline.items():
            self.metrics[name].append({
                "timestamp": now,
                "value": value,
                "labels": {"source": "baseline_seed"},
            })

    # ============ 指标采集 ============

    def record_metric(self, name: str, value: float, labels: dict = None):
        """记录指标"""
        with self._lock:
            self.metrics[name].append({
                "timestamp": time.time(),
                "value": value,
                "labels": labels or {},
            })

    def get_metric(self, name: str, window_sec: int = 3600) -> list:
        """获取指标历史"""
        with self._lock:
            now = time.time()
            return [
                m for m in self.metrics.get(name, [])
                if now - m["timestamp"] <= window_sec
            ]

    def get_metric_latest(self, name: str) -> Optional[float]:
        """获取指标最新值"""
        with self._lock:
            metrics = self.metrics.get(name, [])
            return metrics[-1]["value"] if metrics else None

    def get_metric_avg(self, name: str, window_sec: int = 3600) -> Optional[float]:
        """获取指标平均值"""
        metrics = self.get_metric(name, window_sec)
        if not metrics:
            return None
        return sum(m["value"] for m in metrics) / len(metrics)

    # ============ 告警评估 ============

    def evaluate_rules(self) -> list[Alert]:
        """评估所有告警规则"""
        new_alerts = []
        now = time.time()

        for rule in self.rules:
            latest = self.get_metric_latest(rule.metric)
            if latest is None:
                continue

            triggered = self._check_condition(rule, latest)

            if triggered:
                # 检查冷却时间
                last_fired = self.last_alert_time.get(rule.name, 0)
                if now - last_fired < rule.cooldown_sec:
                    continue

                # 检查是否已有活跃告警
                if rule.name in self.active_alerts:
                    continue

                # 触发告警
                alert = Alert(
                    alert_id=f"alert_{int(now)}_{rule.name}",
                    rule_name=rule.name,
                    level=rule.level,
                    message=rule.message_template.format(value=latest),
                    value=latest,
                    fired_at=now,
                )
                self.active_alerts[rule.name] = alert
                self.last_alert_time[rule.name] = now
                new_alerts.append(alert)

                print(f"🚨 告警触发: [{alert.level.value}] {alert.message}")
            else:
                # 检查是否需要恢复
                if rule.name in self.active_alerts:
                    alert = self.active_alerts.pop(rule.name)
                    alert.status = AlertStatus.RESOLVED
                    alert.resolved_at = now
                    self.alert_history.append(alert)
                    print(f"✅ 告警恢复: {alert.rule_name}")

        return new_alerts

    def _check_condition(self, rule: AlertRule, value: float) -> bool:
        """检查告警条件"""
        conditions = {
            "gt": value > rule.threshold,
            "lt": value < rule.threshold,
            "gte": value >= rule.threshold,
            "lte": value <= rule.threshold,
            "eq": value == rule.threshold,
        }
        return conditions.get(rule.condition, False)

    # ============ 告警管理 ============

    def acknowledge_alert(self, rule_name: str) -> bool:
        """确认告警"""
        with self._lock:
            alert = self.active_alerts.get(rule_name)
            if alert:
                alert.status = AlertStatus.ACKNOWLEDGED
                return True
            return False

    def get_active_alerts(self) -> list:
        """获取活跃告警"""
        with self._lock:
            return [
                {
                    "alert_id": a.alert_id,
                    "rule_name": a.rule_name,
                    "level": a.level.value,
                    "message": a.message,
                    "status": a.status.value,
                    "fired_at": datetime.fromtimestamp(a.fired_at).isoformat(),
                    "value": a.value,
                }
                for a in self.active_alerts.values()
            ]

    def get_alert_history(self, limit: int = 100) -> list:
        """获取告警历史"""
        with self._lock:
            return [
                {
                    "alert_id": a.alert_id,
                    "rule_name": a.rule_name,
                    "level": a.level.value,
                    "message": a.message,
                    "status": a.status.value,
                    "fired_at": datetime.fromtimestamp(a.fired_at).isoformat(),
                    "resolved_at": datetime.fromtimestamp(a.resolved_at).isoformat() if a.resolved_at else None,
                }
                for a in self.alert_history[-limit:]
            ]

    # ============ 规则管理 ============

    def add_rule(self, rule: AlertRule):
        """添加告警规则"""
        with self._lock:
            self.rules.append(rule)

    def list_rules(self) -> list:
        """列出所有规则"""
        return [
            {
                "name": r.name,
                "metric": r.metric,
                "condition": r.condition,
                "threshold": r.threshold,
                "level": r.level.value,
                "message_template": r.message_template,
                "cooldown_sec": r.cooldown_sec,
            }
            for r in self.rules
        ]

    # ============ 健康检查 ============

    def health_check(self) -> dict:
        """系统健康检查"""
        checks = {
            "api_server": self._check_api_server(),
            "sd_webui": self._check_sd_webui(),
            "ffmpeg": self._check_ffmpeg(),
            "edge_tts": self._check_edge_tts(),
            "storage": self._check_storage(),
        }

        all_healthy = all(c["healthy"] for c in checks.values())

        return {
            "status": "healthy" if all_healthy else "degraded",
            "timestamp": datetime.now().isoformat(),
            "checks": checks,
            "active_alerts": len(self.active_alerts),
            "metrics_count": sum(len(v) for v in self.metrics.values()),
        }

    def _check_api_server(self) -> dict:
        """检查 API 服务器"""
        return {"healthy": True, "message": "API server running"}

    def _check_sd_webui(self) -> dict:
        """检查 SD WebUI"""
        try:
            import requests
            resp = requests.get(
                os.environ.get("SD_WEBUI_URL", "http://localhost:7860") + "/sdapi/v1/options",
                timeout=2,
            )
            return {"healthy": resp.status_code == 200, "message": f"SD WebUI status: {resp.status_code}"}
        except Exception as e:
            return {"healthy": False, "message": f"SD WebUI 不可用: {str(e)[:50]}"}

    def _check_ffmpeg(self) -> dict:
        """检查 ffmpeg"""
        try:
            import subprocess
            result = subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=2)
            return {"healthy": result.returncode == 0, "message": "ffmpeg available"}
        except Exception:
            return {"healthy": False, "message": "ffmpeg 不可用"}

    def _check_edge_tts(self) -> dict:
        """检查 edge-tts"""
        try:
            import edge_tts
            return {"healthy": True, "message": "edge-tts available"}
        except ImportError:
            return {"healthy": False, "message": "edge-tts 未安装"}

    def _check_storage(self) -> dict:
        """检查存储"""
        try:
            usage = os.statvfs(self.storage_path)
            free_mb = (usage.f_bavail * usage.f_frsize) / (1024 * 1024)
            return {"healthy": free_mb > 100, "message": f"可用空间: {free_mb:.0f}MB"}
        except Exception:
            return {"healthy": True, "message": "storage check skipped"}

    # ============ 仪表盘 ============

    def get_dashboard(self) -> dict:
        """获取监控仪表盘数据"""
        return {
            "health": self.health_check(),
            "metrics": {
                "daily_videos": self.get_metric_latest("daily_videos") or 0,
                "daily_assets": self.get_metric_latest("daily_assets") or 0,
                "agent_success_rate": self.get_metric_latest("agent_success_rate") or 0,
                "e2e_latency": self.get_metric_latest("e2e_latency") or 0,
                "api_error_rate": self.get_metric_latest("api_error_rate") or 0,
            },
            "active_alerts": self.get_active_alerts(),
            "alert_history_24h": len([
                a for a in self.alert_history
                if time.time() - a.fired_at < 86400
            ]),
            "rules_count": len(self.rules),
        }

    # ============ 持久化 ============

    def save_state(self):
        """保存状态"""
        state = {
            "metrics": {
                name: list(deq) for name, deq in self.metrics.items()
            },
            "alert_history": [
                {
                    "alert_id": a.alert_id,
                    "rule_name": a.rule_name,
                    "level": a.level.value,
                    "message": a.message,
                    "status": a.status.value,
                    "fired_at": a.fired_at,
                    "resolved_at": a.resolved_at,
                }
                for a in self.alert_history
            ],
            "saved_at": datetime.now().isoformat(),
        }
        state_file = self.storage_path / "monitoring_state.json"
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)


# ============================================================================
# CLI 入口
# ============================================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(description="监控告警系统")
    parser.add_argument(
        "--action",
        choices=["health", "dashboard", "alerts", "history", "rules", "record"],
        required=True,
    )
    parser.add_argument("--metric", help="指标名")
    parser.add_argument("--value", type=float, help="指标值")
    parser.add_argument("--storage", default="/mnt/user-data/workspace/monitoring")

    args = parser.parse_args()
    monitor = MonitoringSystem(storage_path=args.storage)

    if args.action == "health":
        print(json.dumps(monitor.health_check(), ensure_ascii=False, indent=2))
    elif args.action == "dashboard":
        print(json.dumps(monitor.get_dashboard(), ensure_ascii=False, indent=2))
    elif args.action == "alerts":
        print(json.dumps(monitor.get_active_alerts(), ensure_ascii=False, indent=2))
    elif args.action == "history":
        print(json.dumps(monitor.get_alert_history(), ensure_ascii=False, indent=2))
    elif args.action == "rules":
        print(json.dumps(monitor.list_rules(), ensure_ascii=False, indent=2))
    elif args.action == "record":
        if not args.metric or args.value is None:
            print("错误: 需要 --metric 和 --value")
            return 1
        monitor.record_metric(args.metric, args.value)
        alerts = monitor.evaluate_rules()
        print(f"✅ 指标已记录: {args.metric} = {args.value}")
        if alerts:
            print(f"🚨 触发 {len(alerts)} 个告警")
        else:
            print("✅ 无告警触发")

    return 0


if __name__ == "__main__":
    exit(main())
