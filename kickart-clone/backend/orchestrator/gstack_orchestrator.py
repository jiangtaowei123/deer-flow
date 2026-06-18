"""
Kickart Clone - gstack Orchestrator
借鉴 gstack autoplan 方法论，自动规划与推进项目迭代
"""
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class Task:
    """gstack 任务"""
    id: str
    title: str
    status: str = "pending"  # pending | in_progress | completed | blocked
    assigned_agent: Optional[str] = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    artifacts: list = field(default_factory=list)


@dataclass
class Iteration:
    """gstack 迭代"""
    id: str
    name: str
    duration: str
    status: str = "planned"
    deliverables: list = field(default_factory=list)
    success_criteria: list = field(default_factory=list)
    tasks: list = field(default_factory=list)


@dataclass
class Metric:
    """gstack 度量"""
    name: str
    description: str
    target: float
    unit: str
    current: float = 0.0


class GstackOrchestrator:
    """gstack 编排器 - 自动规划与推进"""

    def __init__(self, config_path: str = "autoplan.yaml"):
        self.config_path = Path(config_path)
        self.config = self._load_config()
        self.iterations = self._parse_iterations()
        self.metrics = self._parse_metrics()
        self.state_file = Path(".gstack-state.json")
        self.state = self._load_state()

    def _load_config(self) -> dict:
        with open(self.config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _parse_iterations(self) -> list[Iteration]:
        iterations = []
        for it_data in self.config.get("iterations", []):
            tasks = [Task(**t) for t in it_data.get("tasks", [])]
            it = Iteration(
                id=it_data["id"],
                name=it_data["name"],
                duration=it_data.get("duration", ""),
                status=it_data.get("status", "planned"),
                deliverables=it_data.get("deliverables", []),
                success_criteria=it_data.get("success_criteria", []),
                tasks=tasks,
            )
            iterations.append(it)
        return iterations

    def _parse_metrics(self) -> list[Metric]:
        metrics = []
        for m in self.config.get("metrics", []):
            metrics.append(Metric(
                name=m["name"],
                description=m["description"],
                target=m["target"],
                unit=m["unit"],
            ))
        return metrics

    def _load_state(self) -> dict:
        if self.state_file.exists():
            with open(self.state_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"current_iteration": None, "completed_tasks": [], "metrics_history": []}

    def _save_state(self):
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=2, ensure_ascii=False)

    def get_current_iteration(self) -> Optional[Iteration]:
        """获取当前迭代"""
        for it in self.iterations:
            if it.status == "in_progress":
                return it
        # 自动启动下一个迭代
        for it in self.iterations:
            if it.status == "planned":
                it.status = "in_progress"
                self.state["current_iteration"] = it.id
                self._save_state()
                return it
        return None

    def get_next_task(self) -> Optional[Task]:
        """获取下一个待执行任务"""
        current = self.get_current_iteration()
        if not current:
            return None
        for task in current.tasks:
            if task.status == "pending":
                task.status = "in_progress"
                task.started_at = time.time()
                self._save_state()
                return task
        return None

    def complete_task(self, task_id: str, artifacts: list = None):
        """完成任务"""
        for it in self.iterations:
            for task in it.tasks:
                if task.id == task_id:
                    task.status = "completed"
                    task.completed_at = time.time()
                    task.artifacts = artifacts or []
                    self.state["completed_tasks"].append(task_id)
                    self._save_state()
                    self._check_iteration_completion(it)
                    return True
        return False

    def _check_iteration_completion(self, iteration: Iteration):
        """检查迭代是否完成"""
        if all(t.status == "completed" for t in iteration.tasks):
            iteration.status = "completed"
            self.state["current_iteration"] = None
            self._save_state()

    def record_metric(self, name: str, value: float):
        """记录度量值"""
        for m in self.metrics:
            if m.name == name:
                m.current = value
                self.state["metrics_history"].append({
                    "name": name,
                    "value": value,
                    "timestamp": time.time(),
                })
                self._save_state()
                return True
        return False

    def get_progress_report(self) -> dict:
        """生成进度报告"""
        current = self.get_current_iteration()
        total_tasks = sum(len(it.tasks) for it in self.iterations)
        completed_tasks = sum(
            1 for it in self.iterations for t in it.tasks if t.status == "completed"
        )

        return {
            "project": self.config["project"]["name"],
            "goal": self.config["project"]["goal"],
            "current_iteration": current.name if current else None,
            "current_iteration_status": current.status if current else None,
            "overall_progress": f"{completed_tasks}/{total_tasks}",
            "progress_percentage": round(completed_tasks / total_tasks * 100, 1) if total_tasks else 0,
            "iterations": [
                {
                    "id": it.id,
                    "name": it.name,
                    "status": it.status,
                    "tasks_total": len(it.tasks),
                    "tasks_completed": sum(1 for t in it.tasks if t.status == "completed"),
                }
                for it in self.iterations
            ],
            "metrics": [
                {
                    "name": m.name,
                    "description": m.description,
                    "current": m.current,
                    "target": m.target,
                    "unit": m.unit,
                    "achieved": m.current >= m.target if m.current > 0 else False,
                }
                for m in self.metrics
            ],
        }

    def print_progress(self):
        """打印进度报告"""
        report = self.get_progress_report()
        print("=" * 60)
        print(f"🚀 {report['project']} - gstack Progress Report")
        print(f"🎯 Goal: {report['goal']}")
        print(f"📊 Overall: {report['overall_progress']} ({report['progress_percentage']}%)")
        print("=" * 60)

        if report["current_iteration"]:
            print(f"\n📍 Current Iteration: {report['current_iteration']}")
            print(f"   Status: {report['current_iteration_status']}")

        print("\n📋 Iterations:")
        for it in report["iterations"]:
            status_icon = {"completed": "✅", "in_progress": "🔄", "planned": "⏳"}.get(it["status"], "❓")
            print(f"  {status_icon} {it['name']}: {it['tasks_completed']}/{it['tasks_total']} tasks")

        print("\n📈 Metrics:")
        for m in report["metrics"]:
            achieved_icon = "✅" if m["achieved"] else "⏳"
            print(f"  {achieved_icon} {m['description']}: {m['current']}/{m['target']} {m['unit']}")


if __name__ == "__main__":
    orchestrator = GstackOrchestrator("/workspace/kickart-clone/autoplan.yaml")
    orchestrator.print_progress()

    print("\n" + "=" * 60)
    print("📝 Next Task:")
    next_task = orchestrator.get_next_task()
    if next_task:
        print(f"  ID: {next_task.id}")
        print(f"  Title: {next_task.title}")
        print(f"  Status: {next_task.status}")
    else:
        print("  No pending tasks")
