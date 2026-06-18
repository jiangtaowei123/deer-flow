"""
JNPF6.2 适配层 - 低代码平台集成
将 Kickart Clone 能力封装为 JNPF6.2 兼容的低代码组件
支持：表单定义、流程编排、数据模型、API 注册、页面生成
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

# 添加 Lead Agent 路径
# __file__ = .../platform/jnpf/adapter.py
# PROJECT_ROOT = .../kickart-clone
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "agents" / "lead_agent" / "scripts"))

try:
    from orchestrator import LeadAgentOrchestrator, WorkflowType, TaskStatus
except ImportError:
    # 回退：定义最小占位（避免导入失败）
    LeadAgentOrchestrator = None
    WorkflowType = None
    TaskStatus = None


# ============================================================================
# JNPF6.2 数据模型
# ============================================================================

@dataclass
class JNPFFormField:
    """JNPF 表单字段"""
    field: str
    label: str
    type: str  # text/textarea/select/image/url/number/switch
    required: bool = False
    default: any = None
    options: list = field(default_factory=list)
    placeholder: str = ""
    description: str = ""


@dataclass
class JNPFDataModel:
    """JNPF 数据模型"""
    name: str
    table: str
    primary_key: str = "id"
    fields: list = field(default_factory=list)


@dataclass
class JNPFWorkflowNode:
    """JNPF 流程节点"""
    node_id: str
    node_type: str  # start/task/decision/end
    name: str
    agent: Optional[str] = None
    next_nodes: list = field(default_factory=list)
    config: dict = field(default_factory=dict)


@dataclass
class JNPFPage:
    """JNPF 页面定义"""
    page_id: str
    name: str
    type: str  # form/list/detail/dashboard
    title: str
    description: str = ""
    components: list = field(default_factory=list)
    api_bindings: dict = field(default_factory=dict)


# ============================================================================
# JNPF6.2 适配器
# ============================================================================

class JNPFAdapter:
    """
    JNPF6.2 低代码平台适配器
    将 Kickart Clone 能力映射为 JNPF6.2 组件
    """

    # 平台元信息
    PLATFORM_META = {
        "platform": "JNPF6.2",
        "version": "6.2.0",
        "spec": "low-code-platform",
        "compatibility": "jnpf6.2+",
    }

    def __init__(self, output_dir: str = "/mnt/user-data/workspace/jnpf"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        if LeadAgentOrchestrator is not None:
            self.lead_agent = LeadAgentOrchestrator(
                output_dir=str(self.output_dir / "runs")
            )
        else:
            self.lead_agent = None

    # ============ 表单定义 ============

    def get_creative_form(self) -> dict:
        """获取创意生成表单定义"""
        fields = [
            JNPFFormField(
                field="input_value",
                label="商品输入",
                type="textarea",
                required=True,
                placeholder="输入商品 URL/ID/描述",
                description="支持 Amazon URL、商品 ID 或文字描述",
            ),
            JNPFFormField(
                field="workflow",
                label="工作流类型",
                type="select",
                required=True,
                default="video",
                options=["video", "image", "storyboard"],
                description="video=完整视频，image=仅图片，storyboard=仅分镜",
            ),
            JNPFFormField(
                field="num_scenes",
                label="场景数量",
                type="number",
                default=6,
                description="3-10 个场景",
            ),
            JNPFFormField(
                field="aspect_ratio",
                label="宽高比",
                type="select",
                default="9:16",
                options=["9:16", "16:9", "1:1", "4:3", "3:4"],
            ),
            JNPFFormField(
                field="voice",
                label="TTS 音色",
                type="select",
                default="xiaoxiao",
                options=["xiaoxiao", "yunxi", "yunjian", "xiaoyi", "yunyang", "xiaohan"],
            ),
            JNPFFormField(
                field="enable_tts",
                label="启用旁白",
                type="switch",
                default=True,
            ),
            JNPFFormField(
                field="enable_subs",
                label="烧录字幕",
                type="switch",
                default=True,
            ),
        ]
        return self._build_form_schema("creative_form", "营销创作表单", fields)

    def get_product_form(self) -> dict:
        """获取商品解析表单"""
        fields = [
            JNPFFormField(
                field="product_url",
                label="商品 URL",
                type="url",
                placeholder="https://amazon.com/dp/B0XXX",
            ),
            JNPFFormField(
                field="product_image",
                label="商品图片",
                type="image",
            ),
            JNPFFormField(
                field="product_description",
                label="商品描述",
                type="textarea",
                placeholder="手动输入商品描述",
            ),
        ]
        return self._build_form_schema("product_form", "商品解析表单", fields)

    def _build_form_schema(self, form_id: str, name: str, fields: list) -> dict:
        """构建 JNPF 表单 schema"""
        return {
            "form_id": form_id,
            "name": name,
            "platform": self.PLATFORM_META,
            "fields": [
                {
                    "field": f.field,
                    "label": f.label,
                    "type": f.type,
                    "required": f.required,
                    "default": f.default,
                    "options": f.options if f.options else None,
                    "placeholder": f.placeholder,
                    "description": f.description,
                }
                for f in fields
            ],
            "generated_at": datetime.now().isoformat(),
        }

    # ============ 数据模型 ============

    def get_data_models(self) -> list:
        """获取 JNPF 数据模型定义"""
        models = [
            JNPFDataModel(
                name="商品信息",
                table="kickart_products",
                fields=[
                    {"field": "id", "type": "string", "primary": True},
                    {"field": "product_id", "type": "string", "label": "商品ID"},
                    {"field": "platform", "type": "string", "label": "平台"},
                    {"field": "title", "type": "string", "label": "标题"},
                    {"field": "category", "type": "string", "label": "类目"},
                    {"field": "description", "type": "text", "label": "描述"},
                    {"field": "main_image_url", "type": "string", "label": "主图URL"},
                    {"field": "created_at", "type": "datetime", "label": "创建时间"},
                ],
            ),
            JNPFDataModel(
                name="创意脚本",
                table="kickart_creatives",
                fields=[
                    {"field": "id", "type": "string", "primary": True},
                    {"field": "product_id", "type": "string", "label": "商品ID", "relation": "kickart_products.id"},
                    {"field": "theme", "type": "string", "label": "主题"},
                    {"field": "storyline", "type": "text", "label": "故事线"},
                    {"field": "target_audience", "type": "string", "label": "目标人群"},
                    {"field": "tone", "type": "string", "label": "调性"},
                    {"field": "total_duration", "type": "int", "label": "总时长(秒)"},
                    {"field": "scenes_json", "type": "text", "label": "场景JSON"},
                    {"field": "created_at", "type": "datetime", "label": "创建时间"},
                ],
            ),
            JNPFDataModel(
                name="分镜列表",
                table="kickart_storyboards",
                fields=[
                    {"field": "id", "type": "string", "primary": True},
                    {"field": "creative_id", "type": "string", "label": "创意ID", "relation": "kickart_creatives.id"},
                    {"field": "total_shots", "type": "int", "label": "分镜数"},
                    {"field": "aspect_ratio", "type": "string", "label": "宽高比"},
                    {"field": "shots_json", "type": "text", "label": "分镜JSON"},
                    {"field": "created_at", "type": "datetime", "label": "创建时间"},
                ],
            ),
            JNPFDataModel(
                name="视频产物",
                table="kickart_videos",
                fields=[
                    {"field": "id", "type": "string", "primary": True},
                    {"field": "storyboard_id", "type": "string", "label": "分镜ID", "relation": "kickart_storyboards.id"},
                    {"field": "output_path", "type": "string", "label": "视频路径"},
                    {"field": "duration_sec", "type": "int", "label": "时长(秒)"},
                    {"field": "resolution", "type": "string", "label": "分辨率"},
                    {"field": "file_size_mb", "type": "float", "label": "文件大小(MB)"},
                    {"field": "created_at", "type": "datetime", "label": "创建时间"},
                ],
            ),
        ]
        return [
            {
                "name": m.name,
                "table": m.table,
                "primary_key": m.primary_key,
                "fields": m.fields,
            }
            for m in models
        ]

    # ============ 流程编排 ============

    def get_workflow_definition(self) -> dict:
        """获取 JNPF 流程定义"""
        nodes = [
            JNPFWorkflowNode(
                node_id="start",
                node_type="start",
                name="开始",
                next_nodes=["parse_product"],
            ),
            JNPFWorkflowNode(
                node_id="parse_product",
                node_type="task",
                name="商品解析",
                agent="product_parser",
                next_nodes=["generate_creative"],
                config={"fallback": "manual_input"},
            ),
            JNPFWorkflowNode(
                node_id="generate_creative",
                node_type="task",
                name="创意生成",
                agent="creative",
                next_nodes=["generate_storyboard"],
                config={"fallback": "generic_template"},
            ),
            JNPFWorkflowNode(
                node_id="generate_storyboard",
                node_type="task",
                name="分镜设计",
                agent="storyboard",
                next_nodes=["decision_output"],
                config={"fallback": "simple_shots"},
            ),
            JNPFWorkflowNode(
                node_id="decision_output",
                node_type="decision",
                name="输出类型判断",
                next_nodes=["generate_images", "compose_video"],
                config={"condition": "workflow_type"},
            ),
            JNPFWorkflowNode(
                node_id="generate_images",
                node_type="task",
                name="图像生成",
                agent="image_gen",
                next_nodes=["end"],
                config={"fallback": "placeholder_images"},
            ),
            JNPFWorkflowNode(
                node_id="compose_video",
                node_type="task",
                name="视频合成",
                agent="video_gen",
                next_nodes=["end"],
                config={"fallback": None},
            ),
            JNPFWorkflowNode(
                node_id="end",
                node_type="end",
                name="结束",
                next_nodes=[],
            ),
        ]
        return {
            "workflow_id": "kickart_creative_workflow",
            "name": "Kickart 营销创作流程",
            "platform": self.PLATFORM_META,
            "nodes": [
                {
                    "node_id": n.node_id,
                    "node_type": n.node_type,
                    "name": n.name,
                    "agent": n.agent,
                    "next_nodes": n.next_nodes,
                    "config": n.config,
                }
                for n in nodes
            ],
        }

    # ============ 页面定义 ============

    def get_pages(self) -> list:
        """获取 JNPF 页面定义"""
        pages = [
            JNPFPage(
                page_id="dashboard",
                name="创作工作台",
                type="dashboard",
                title="Kickart 营销创作工作台",
                description="一站式营销素材/视频创作平台",
                components=[
                    {"type": "stat_card", "field": "daily_videos", "label": "日成片数"},
                    {"type": "stat_card", "field": "daily_assets", "label": "日素材数"},
                    {"type": "stat_card", "field": "agent_success_rate", "label": "Agent成功率"},
                    {"type": "stat_card", "field": "e2e_latency", "label": "端到端耗时"},
                    {"type": "recent_runs", "label": "最近运行"},
                ],
                api_bindings={"recent_runs": "GET /orchestrate"},
            ),
            JNPFPage(
                page_id="creative_form",
                name="创意生成",
                type="form",
                title="新建营销创作",
                description="输入商品信息，生成营销视频/图片",
                components=[
                    {"type": "form", "schema_ref": "creative_form"},
                    {"type": "submit_button", "label": "开始创作", "action": "POST /orchestrate"},
                ],
                api_bindings={"submit": "POST /orchestrate"},
            ),
            JNPFPage(
                page_id="run_detail",
                name="运行详情",
                type="detail",
                title="创作运行详情",
                description="查看单次创作运行的状态和产物",
                components=[
                    {"type": "task_timeline", "label": "任务时间线"},
                    {"type": "degradation_log", "label": "降级记录"},
                    {"type": "artifacts_preview", "label": "产物预览"},
                    {"type": "video_player", "field": "video_path", "label": "视频预览"},
                ],
                api_bindings={"detail": "GET /orchestrate/{run_id}"},
            ),
            JNPFPage(
                page_id="runs_list",
                name="运行列表",
                type="list",
                title="创作历史",
                description="所有创作运行记录",
                components=[
                    {"type": "table", "fields": ["run_id", "workflow_type", "status", "input", "created_at"]},
                    {"type": "filter", "fields": ["status", "workflow_type"]},
                    {"type": "action", "label": "查看详情", "page_ref": "run_detail"},
                ],
                api_bindings={"list": "GET /orchestrate"},
            ),
        ]
        return [
            {
                "page_id": p.page_id,
                "name": p.name,
                "type": p.type,
                "title": p.title,
                "description": p.description,
                "components": p.components,
                "api_bindings": p.api_bindings,
            }
            for p in pages
        ]

    # ============ API 注册 ============

    def get_api_registry(self) -> list:
        """获取 JNPF API 注册表"""
        return [
            {
                "path": "/orchestrate",
                "method": "POST",
                "name": "启动创作工作流",
                "description": "异步启动 Lead Agent 编排",
                "request_schema": "creative_form",
                "response_schema": "task_response",
                "async": True,
            },
            {
                "path": "/orchestrate/sync",
                "method": "POST",
                "name": "同步创作工作流",
                "description": "同步执行 Lead Agent 编排（阻塞）",
                "request_schema": "creative_form",
                "response_schema": "workflow_result",
                "async": False,
            },
            {
                "path": "/orchestrate/{run_id}",
                "method": "GET",
                "name": "查询运行状态",
                "description": "查询单次创作运行的状态和产物",
                "response_schema": "run_detail",
            },
            {
                "path": "/orchestrate",
                "method": "GET",
                "name": "列出所有运行",
                "description": "列出所有创作运行记录",
                "response_schema": "runs_list",
            },
            {
                "path": "/scenes",
                "method": "GET",
                "name": "场景模板列表",
                "description": "获取所有可用的场景模板",
                "response_schema": "scenes_list",
            },
            {
                "path": "/health",
                "method": "GET",
                "name": "健康检查",
                "description": "服务健康状态",
                "response_schema": "health_status",
            },
        ]

    # ============ 应用清单 ============

    def get_app_manifest(self) -> dict:
        """获取 JNPF 应用清单（用于一键部署）"""
        return {
            "app_id": "kickart-clone",
            "name": "Kickart 营销创作平台",
            "version": "1.0.0",
            "platform": self.PLATFORM_META,
            "description": "一站式营销创作平台 - 商品解析 + 创意生成 + 视频成片",
            "base": "DeerFlow + Stable Diffusion + JNPF6.2 + 复利系统指令集",
            "forms": ["creative_form", "product_form"],
            "data_models": ["kickart_products", "kickart_creatives", "kickart_storyboards", "kickart_videos"],
            "workflows": ["kickart_creative_workflow"],
            "pages": ["dashboard", "creative_form", "run_detail", "runs_list"],
            "apis": len(self.get_api_registry()),
            "agents": ["product_parser", "creative", "storyboard", "image_gen", "tts", "video_gen"],
            "generated_at": datetime.now().isoformat(),
        }

    # ============ 导出完整配置 ============

    def export_full_config(self) -> dict:
        """导出完整的 JNPF6.2 配置"""
        config = {
            "manifest": self.get_app_manifest(),
            "forms": {
                "creative_form": self.get_creative_form(),
                "product_form": self.get_product_form(),
            },
            "data_models": self.get_data_models(),
            "workflows": [self.get_workflow_definition()],
            "pages": self.get_pages(),
            "api_registry": self.get_api_registry(),
        }

        # 保存到文件
        config_path = self.output_dir / "jnpf_config.json"
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

        return config

    # ============ 执行入口（JNPF 调用） ============

    def execute_creative(self, form_data: dict) -> dict:
        """
        JNPF 表单提交入口
        接收表单数据，调用 Lead Agent 执行
        """
        if self.lead_agent is None or WorkflowType is None:
            return {"success": False, "error": "Lead Agent 不可用（orchestrator 未加载）"}

        input_value = form_data.get("input_value", "")
        workflow = form_data.get("workflow", "video")
        num_scenes = int(form_data.get("num_scenes", 6))
        aspect_ratio = form_data.get("aspect_ratio", "9:16")
        voice = form_data.get("voice", "xiaoxiao")

        if not input_value:
            return {"success": False, "error": "input_value 不能为空"}

        run = self.lead_agent.plan_workflow(
            input_value=input_value,
            workflow_type=WorkflowType(workflow),
            num_scenes=num_scenes,
            aspect_ratio=aspect_ratio,
            voice=voice,
        )
        result = self.lead_agent.execute_workflow(run.run_id)
        return result.final_outputs


# ============================================================================
# CLI 入口
# ============================================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(description="JNPF6.2 适配层")
    parser.add_argument(
        "--action",
        choices=["export", "manifest", "forms", "models", "workflow", "pages", "apis", "execute"],
        default="export",
        help="操作类型",
    )
    parser.add_argument("--output-dir", default="/mnt/user-data/workspace/jnpf")
    parser.add_argument("--input-value", help="商品输入（execute 时使用）")
    parser.add_argument("--workflow", default="video", choices=["video", "image", "storyboard"])

    args = parser.parse_args()
    adapter = JNPFAdapter(output_dir=args.output_dir)

    if args.action == "export":
        config = adapter.export_full_config()
        print(f"✅ JNPF6.2 配置已导出")
        print(f"   应用: {config['manifest']['name']} v{config['manifest']['version']}")
        print(f"   表单: {len(config['forms'])} 个")
        print(f"   数据模型: {len(config['data_models'])} 个")
        print(f"   流程: {len(config['workflows'])} 个")
        print(f"   页面: {len(config['pages'])} 个")
        print(f"   API: {config['manifest']['apis']} 个")
        print(f"   输出: {adapter.output_dir}/jnpf_config.json")
    elif args.action == "manifest":
        print(json.dumps(adapter.get_app_manifest(), ensure_ascii=False, indent=2))
    elif args.action == "forms":
        print(json.dumps({
            "creative_form": adapter.get_creative_form(),
            "product_form": adapter.get_product_form(),
        }, ensure_ascii=False, indent=2))
    elif args.action == "models":
        print(json.dumps(adapter.get_data_models(), ensure_ascii=False, indent=2))
    elif args.action == "workflow":
        print(json.dumps(adapter.get_workflow_definition(), ensure_ascii=False, indent=2))
    elif args.action == "pages":
        print(json.dumps(adapter.get_pages(), ensure_ascii=False, indent=2))
    elif args.action == "apis":
        print(json.dumps(adapter.get_api_registry(), ensure_ascii=False, indent=2))
    elif args.action == "execute":
        if not args.input_value:
            print("错误: execute 需要 --input-value")
            return 1
        result = adapter.execute_creative({
            "input_value": args.input_value,
            "workflow": args.workflow,
        })
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0 if result.get("success") else 1

    return 0


if __name__ == "__main__":
    exit(main())
