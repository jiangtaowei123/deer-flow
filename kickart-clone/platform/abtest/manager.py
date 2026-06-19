"""
A/B 测试框架 - 营销效果对比与优化
支持：多变体生成、指标采集、统计显著性检验、自动选优
"""
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

# 添加路径
_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "platform" / "observability"))
sys.path.insert(0, str(_PROJECT_ROOT / "agents" / "creative" / "scripts"))

from logger import get_logger

logger = get_logger(__name__)


class ExperimentStatus(str, Enum):
    DRAFT = "draft"
    RUNNING = "running"
    COMPLETED = "completed"
    STOPPED = "stopped"


class VariantStatus(str, Enum):
    PENDING = "pending"
    GENERATED = "generated"
    PUBLISHED = "published"
    EVALUATED = "evaluated"


@dataclass
class Variant:
    """实验变体"""
    variant_id: str
    name: str
    config: dict  # 生成配置（style/voice/aspect_ratio 等）
    artifacts: dict = field(default_factory=dict)  # 生成的产物
    metrics: dict = field(default_factory=dict)  # 效果指标
    status: VariantStatus = VariantStatus.PENDING
    weight: float = 1.0  # 流量权重


@dataclass
class Experiment:
    """A/B 测试实验"""
    experiment_id: str
    name: str
    product_input: str
    variants: list[Variant] = field(default_factory=list)
    status: ExperimentStatus = ExperimentStatus.DRAFT
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    winner_id: Optional[str] = None
    config: dict = field(default_factory=dict)


# ============ A/B 测试管理器 ============

class ABTestManager:
    """
    A/B 测试管理器
    - 创建多变体实验
    - 生成各变体产物
    - 采集效果指标
    - 统计显著性检验
    - 自动选优
    """

    def __init__(self, storage_dir: str = "/mnt/user-data/workspace/ab_tests"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.experiments: dict[str, Experiment] = {}
        self._load_experiments()

    def _load_experiments(self):
        """加载已有实验"""
        for f in self.storage_dir.glob("exp_*.json"):
            try:
                with open(f, "r", encoding="utf-8") as fp:
                    data = json.load(fp)
                    exp = Experiment(
                        experiment_id=data["experiment_id"],
                        name=data["name"],
                        product_input=data["product_input"],
                        status=ExperimentStatus(data.get("status", "draft")),
                        created_at=data.get("created_at", time.time()),
                        started_at=data.get("started_at"),
                        completed_at=data.get("completed_at"),
                        winner_id=data.get("winner_id"),
                        config=data.get("config", {}),
                        variants=[
                            Variant(
                                variant_id=v["variant_id"],
                                name=v["name"],
                                config=v["config"],
                                artifacts=v.get("artifacts", {}),
                                metrics=v.get("metrics", {}),
                                status=VariantStatus(v.get("status", "pending")),
                                weight=v.get("weight", 1.0),
                            )
                            for v in data.get("variants", [])
                        ],
                    )
                    self.experiments[exp.experiment_id] = exp
            except Exception as e:
                logger.warning(f"加载实验失败 {f}: {e}")

    def _save_experiment(self, exp: Experiment):
        """保存实验"""
        data = {
            "experiment_id": exp.experiment_id,
            "name": exp.name,
            "product_input": exp.product_input,
            "status": exp.status.value,
            "created_at": exp.created_at,
            "started_at": exp.started_at,
            "completed_at": exp.completed_at,
            "winner_id": exp.winner_id,
            "config": exp.config,
            "variants": [
                {
                    "variant_id": v.variant_id,
                    "name": v.name,
                    "config": v.config,
                    "artifacts": v.artifacts,
                    "metrics": v.metrics,
                    "status": v.status.value,
                    "weight": v.weight,
                }
                for v in exp.variants
            ],
        }
        f = self.storage_dir / f"{exp.experiment_id}.json"
        with open(f, "w", encoding="utf-8") as fp:
            json.dump(data, fp, ensure_ascii=False, indent=2, default=str)

    # ============ 实验管理 ============

    def create_experiment(
        self,
        name: str,
        product_input: str,
        variants_config: list[dict],
        **kwargs,
    ) -> Experiment:
        """
        创建 A/B 测试实验

        Args:
            name: 实验名称
            product_input: 商品输入
            variants_config: 变体配置列表 [{"name": "A", "config": {"style": "viral"}}]

        Returns:
            实验对象
        """
        exp_id = f"exp_{uuid.uuid4().hex[:8]}"
        variants = [
            Variant(
                variant_id=f"{exp_id}_v{chr(65 + i)}",  # exp_xxx_vA, vB, vC
                name=vc.get("name", f"变体{chr(65 + i)}"),
                config=vc.get("config", {}),
                weight=vc.get("weight", 1.0),
            )
            for i, vc in enumerate(variants_config)
        ]

        exp = Experiment(
            experiment_id=exp_id,
            name=name,
            product_input=product_input,
            variants=variants,
            config=kwargs,
        )
        self.experiments[exp_id] = exp
        self._save_experiment(exp)
        logger.info(f"实验创建: {exp_id} ({name}), {len(variants)} 个变体")
        return exp

    def run_experiment(self, experiment_id: str) -> Experiment:
        """
        运行实验：为每个变体生成产物

        Args:
            experiment_id: 实验 ID

        Returns:
            更新后的实验
        """
        exp = self.experiments.get(experiment_id)
        if not exp:
            raise ValueError(f"实验不存在: {experiment_id}")

        exp.status = ExperimentStatus.RUNNING
        exp.started_at = time.time()
        logger.info(f"实验启动: {experiment_id}")

        # 为每个变体生成产物
        for variant in exp.variants:
            try:
                artifacts = self._generate_variant(exp, variant)
                variant.artifacts = artifacts
                variant.status = VariantStatus.GENERATED
                logger.info(f"变体 {variant.variant_id} 生成完成")
            except Exception as e:
                logger.error(f"变体 {variant.variant_id} 生成失败: {e}")
                variant.status = VariantStatus.PENDING
                variant.artifacts = {"error": str(e)}

        self._save_experiment(exp)
        return exp

    def _generate_variant(self, exp: Experiment, variant: Variant) -> dict:
        """为变体生成产物"""
        from llm_creative import IntelligentCreativeGenerator

        # 商品信息
        product_info = {
            "title": exp.product_input[:100],
            "description": exp.product_input,
            "category": "generic",
        }

        # 使用变体配置生成创意
        generator = IntelligentCreativeGenerator.auto_select()
        style = variant.config.get("style", "viral")
        creative = generator.generate(
            product_info=product_info,
            num_scenes=variant.config.get("num_scenes", 6),
            style=style,
            temperature=variant.config.get("temperature", 0.8),
        )

        return {
            "creative": creative,
            "style": style,
            "voice": variant.config.get("voice", "xiaoxiao"),
            "aspect_ratio": variant.config.get("aspect_ratio", "9:16"),
        }

    # ============ 指标采集 ============

    def record_metrics(
        self,
        experiment_id: str,
        variant_id: str,
        metrics: dict,
    ):
        """
        记录变体效果指标

        Args:
            experiment_id: 实验 ID
            variant_id: 变体 ID
            metrics: 指标 {"views": 1000, "likes": 50, "shares": 10, "conversions": 5}
        """
        exp = self.experiments.get(experiment_id)
        if not exp:
            raise ValueError(f"实验不存在: {experiment_id}")

        variant = next((v for v in exp.variants if v.variant_id == variant_id), None)
        if not variant:
            raise ValueError(f"变体不存在: {variant_id}")

        # 合并指标
        for k, v in metrics.items():
            if k in variant.metrics:
                variant.metrics[k] += v
            else:
                variant.metrics[k] = v

        variant.status = VariantStatus.EVALUATED
        self._save_experiment(exp)
        logger.info(f"指标记录: {variant_id} = {metrics}")

    # ============ 统计分析 ============

    def analyze(self, experiment_id: str) -> dict:
        """
        分析实验结果

        Returns:
            分析报告
        """
        exp = self.experiments.get(experiment_id)
        if not exp:
            raise ValueError(f"实验不存在: {experiment_id}")

        # 计算各变体的核心指标
        variant_reports = []
        for v in exp.variants:
            metrics = v.metrics
            views = metrics.get("views", 0)
            likes = metrics.get("likes", 0)
            shares = metrics.get("shares", 0)
            conversions = metrics.get("conversions", 0)
            watch_time = metrics.get("avg_watch_time", 0)

            ctr = (likes + shares) / views if views > 0 else 0
            cvr = conversions / views if views > 0 else 0
            engagement = (likes + shares * 2 + conversions * 5) / views if views > 0 else 0

            variant_reports.append({
                "variant_id": v.variant_id,
                "name": v.name,
                "config": v.config,
                "metrics": metrics,
                "derived": {
                    "ctr": round(ctr, 4),
                    "cvr": round(cvr, 4),
                    "engagement_score": round(engagement, 4),
                    "avg_watch_time": watch_time,
                },
                "status": v.status.value,
            })

        # 排序（按 engagement_score 降序）
        variant_reports.sort(key=lambda x: x["derived"]["engagement_score"], reverse=True)

        # 选出胜者
        winner = variant_reports[0] if variant_reports else None

        # 统计显著性检验（简化版：基于 engagement 差异）
        significance = self._compute_significance(variant_reports)

        report = {
            "experiment_id": exp.experiment_id,
            "name": exp.name,
            "status": exp.status.value,
            "variant_count": len(exp.variants),
            "variants": variant_reports,
            "winner": winner,
            "significance": significance,
            "recommendation": self._build_recommendation(winner, significance),
            "analyzed_at": datetime.now().isoformat(),
        }

        # 更新实验
        if winner:
            exp.winner_id = winner["variant_id"]
        exp.status = ExperimentStatus.COMPLETED
        exp.completed_at = time.time()
        self._save_experiment(exp)

        return report

    def _compute_significance(self, reports: list) -> dict:
        """计算统计显著性（简化版）"""
        if len(reports) < 2:
            return {"significant": False, "reason": "变体数不足"}

        best = reports[0]["derived"]["engagement_score"]
        second = reports[1]["derived"]["engagement_score"] if len(reports) > 1 else 0

        if best == 0:
            return {"significant": False, "reason": "无数据"}

        improvement = (best - second) / best if best > 0 else 0
        # 简化判断：提升 > 10% 视为显著
        significant = improvement > 0.1

        return {
            "significant": significant,
            "improvement": round(improvement, 4),
            "best_score": best,
            "second_score": second,
            "method": "engagement_score_comparison",
        }

    def _build_recommendation(self, winner: dict, significance: dict) -> str:
        """构建推荐建议"""
        if not winner:
            return "无足够数据给出建议"
        if not significance.get("significant"):
            return f"变体 {winner['name']} 略优，但差异不显著，建议继续测试"
        return f"推荐采用变体 {winner['name']}（engagement={winner['derived']['engagement_score']}，提升 {significance.get('improvement', 0)*100:.1f}%）"

    # ============ 查询 ============

    def get_experiment(self, experiment_id: str) -> Optional[Experiment]:
        return self.experiments.get(experiment_id)

    def list_experiments(self) -> list:
        return [
            {
                "experiment_id": e.experiment_id,
                "name": e.name,
                "status": e.status.value,
                "variant_count": len(e.variants),
                "winner": e.winner_id,
                "created_at": datetime.fromtimestamp(e.created_at).isoformat(),
            }
            for e in self.experiments.values()
        ]


# ============ 预设实验模板 ============

PRESET_EXPERIMENTS = {
    "style_comparison": {
        "name": "风格对比测试",
        "description": "对比不同创意风格的效果",
        "variants": [
            {"name": "爆款病毒式", "config": {"style": "viral"}},
            {"name": "优雅品质", "config": {"style": "elegant"}},
            {"name": "专业测评", "config": {"style": "professional"}},
        ],
    },
    "voice_comparison": {
        "name": "音色对比测试",
        "description": "对比不同 TTS 音色的效果",
        "variants": [
            {"name": "晓晓", "config": {"voice": "xiaoxiao", "style": "viral"}},
            {"name": "云希", "config": {"voice": "yunxi", "style": "viral"}},
            {"name": "云健", "config": {"voice": "yunjian", "style": "viral"}},
        ],
    },
    "aspect_ratio_comparison": {
        "name": "宽高比对比测试",
        "description": "对比不同宽高比的效果",
        "variants": [
            {"name": "竖屏 9:16", "config": {"aspect_ratio": "9:16"}},
            {"name": "横屏 16:9", "config": {"aspect_ratio": "16:9"}},
            {"name": "方形 1:1", "config": {"aspect_ratio": "1:1"}},
        ],
    },
}
