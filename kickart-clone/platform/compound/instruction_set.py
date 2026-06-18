"""
复利系统指令集 - 系统生成与复刻的指令引擎
基于"复利"理念：每次生成的系统/组件都可累积复用，形成资产复利
支持：指令定义、指令解析、指令执行、资产累积
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


# ============================================================================
# 指令模型
# ============================================================================

class InstructionType(str, Enum):
    """指令类型"""
    GENERATE = "generate"        # 生成新系统/组件
    CLONE = "clone"              # 复刻已有系统
    COMPOSE = "compose"          # 组合多个组件
    EXTEND = "extend"            # 扩展已有系统
    INTEGRATE = "integrate"      # 集成外部系统
    DEPLOY = "deploy"            # 部署
    ACCUMULATE = "accumulate"    # 累积资产


class InstructionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    DEGRADED = "degraded"


@dataclass
class Instruction:
    """复利指令"""
    instruction_id: str
    type: InstructionType
    target: str  # 目标系统/组件名
    params: dict = field(default_factory=dict)
    depends_on: list = field(default_factory=list)  # 依赖的指令 ID
    status: InstructionStatus = InstructionStatus.PENDING
    result: dict = field(default_factory=dict)
    created_at: Optional[float] = None
    completed_at: Optional[float] = None


@dataclass
class Asset:
    """复利资产"""
    asset_id: str
    name: str
    type: str  # system/component/template/config/dataset
    version: str
    path: str
    metadata: dict = field(default_factory=dict)
    created_at: Optional[float] = None
    reuse_count: int = 0


# ============================================================================
# 复利系统指令集定义
# ============================================================================

# 预定义指令模板 - 对应 Kickart Clone 的系统能力
INSTRUCTION_TEMPLATES = {
    # 生成类指令
    "generate.creative": {
        "type": InstructionType.GENERATE,
        "target": "creative_script",
        "description": "生成营销创意脚本",
        "params_schema": {
            "product_info": {"type": "dict", "required": True},
            "category": {"type": "string", "default": "auto"},
            "num_scenes": {"type": "int", "default": 6},
        },
        "produces": "creative_asset",
    },
    "generate.storyboard": {
        "type": InstructionType.GENERATE,
        "target": "storyboard",
        "description": "生成分镜列表",
        "params_schema": {
            "creative": {"type": "dict", "required": True},
            "aspect_ratio": {"type": "string", "default": "9:16"},
        },
        "produces": "storyboard_asset",
    },
    "generate.images": {
        "type": InstructionType.GENERATE,
        "target": "batch_images",
        "description": "批量生成图片",
        "params_schema": {
            "storyboard": {"type": "dict", "required": True},
            "num_variants": {"type": "int", "default": 1},
        },
        "produces": "images_asset",
    },
    "generate.video": {
        "type": InstructionType.GENERATE,
        "target": "marketing_video",
        "description": "合成营销视频",
        "params_schema": {
            "storyboard": {"type": "dict", "required": True},
            "images_dir": {"type": "string", "required": False},
            "audio_path": {"type": "string", "required": False},
        },
        "produces": "video_asset",
    },
    "generate.tts": {
        "type": InstructionType.GENERATE,
        "target": "narration_audio",
        "description": "生成 TTS 旁白",
        "params_schema": {
            "storyboard": {"type": "dict", "required": True},
            "voice": {"type": "string", "default": "xiaoxiao"},
        },
        "produces": "audio_asset",
    },

    # 复刻类指令
    "clone.kickart": {
        "type": InstructionType.CLONE,
        "target": "kickart_platform",
        "description": "复刻 Kickart 一站式营销创作平台",
        "params_schema": {
            "reference": {"type": "string", "default": "bytedance.kickart"},
            "modules": {"type": "list", "default": ["creative", "storyboard", "video", "tts"]},
        },
        "produces": "platform_asset",
    },

    # 组合类指令
    "compose.workflow": {
        "type": InstructionType.COMPOSE,
        "target": "end_to_end_workflow",
        "description": "组合端到端工作流",
        "params_schema": {
            "input_value": {"type": "string", "required": True},
            "workflow_type": {"type": "string", "default": "video"},
        },
        "produces": "workflow_asset",
        "chain": [
            "generate.creative",
            "generate.storyboard",
            "generate.images",
            "generate.tts",
            "generate.video",
        ],
    },

    # 集成类指令
    "integrate.jnpf": {
        "type": InstructionType.INTEGRATE,
        "target": "jnpf_platform",
        "description": "集成 JNPF6.2 低代码平台",
        "params_schema": {
            "forms": {"type": "bool", "default": True},
            "data_models": {"type": "bool", "default": True},
            "workflows": {"type": "bool", "default": True},
            "pages": {"type": "bool", "default": True},
        },
        "produces": "jnpf_config",
    },

    # 累积类指令
    "accumulate.asset": {
        "type": InstructionType.ACCUMULATE,
        "target": "asset_registry",
        "description": "累积资产到注册表",
        "params_schema": {
            "asset_name": {"type": "string", "required": True},
            "asset_type": {"type": "string", "required": True},
            "asset_path": {"type": "string", "required": True},
        },
        "produces": "registry_entry",
    },
}


# ============================================================================
# 复利系统指令引擎
# ============================================================================

class CompoundInstructionEngine:
    """
    复利系统指令引擎
    - 解析指令
    - 执行指令链
    - 累积资产
    - 支持复用
    """

    def __init__(self, registry_path: str = "/mnt/user-data/workspace/compound_registry"):
        self.registry_path = Path(registry_path)
        self.registry_path.mkdir(parents=True, exist_ok=True)
        self.assets: dict[str, Asset] = {}
        self.instructions: dict[str, Instruction] = {}
        self._load_registry()

    def _load_registry(self):
        """加载资产注册表"""
        registry_file = self.registry_path / "assets.json"
        if registry_file.exists():
            with open(registry_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                for asset_data in data.get("assets", []):
                    asset = Asset(**asset_data)
                    self.assets[asset.asset_id] = asset

    def _save_registry(self):
        """保存资产注册表"""
        registry_file = self.registry_path / "assets.json"
        with open(registry_file, "w", encoding="utf-8") as f:
            json.dump({
                "assets": [
                    {
                        "asset_id": a.asset_id,
                        "name": a.name,
                        "type": a.type,
                        "version": a.version,
                        "path": a.path,
                        "metadata": a.metadata,
                        "created_at": a.created_at,
                        "reuse_count": a.reuse_count,
                    }
                    for a in self.assets.values()
                ],
                "updated_at": datetime.now().isoformat(),
            }, f, ensure_ascii=False, indent=2)

    # ============ 指令解析 ============

    def parse_instruction(self, instruction_str: str, params: dict = None) -> Instruction:
        """解析指令字符串为 Instruction 对象"""
        template = INSTRUCTION_TEMPLATES.get(instruction_str)
        if not template:
            # 尝试模糊匹配
            matches = [k for k in INSTRUCTION_TEMPLATES if instruction_str in k]
            if matches:
                template = INSTRUCTION_TEMPLATES[matches[0]]
            else:
                raise ValueError(f"未知指令: {instruction_str}")

        instruction = Instruction(
            instruction_id=f"inst_{uuid.uuid4().hex[:8]}",
            type=template["type"],
            target=template["target"],
            params=params or {},
            created_at=time.time(),
        )
        self.instructions[instruction.instruction_id] = instruction
        return instruction

    # ============ 指令执行 ============

    def execute(self, instruction_str: str, params: dict = None) -> dict:
        """执行单条指令"""
        instruction = self.parse_instruction(instruction_str, params)
        instruction.status = InstructionStatus.RUNNING

        print(f"🔧 执行指令: {instruction_str}")
        print(f"   类型: {instruction.type.value}")
        print(f"   目标: {instruction.target}")

        try:
            result = self._dispatch(instruction)
            instruction.result = result
            instruction.status = InstructionStatus.SUCCESS if result.get("success") else InstructionStatus.FAILED
            instruction.completed_at = time.time()

            # 累积资产
            if result.get("success") and result.get("asset_path"):
                self._accumulate_asset(instruction, result)

            return result
        except Exception as e:
            instruction.status = InstructionStatus.FAILED
            instruction.result = {"success": False, "error": str(e)}
            instruction.completed_at = time.time()
            return instruction.result

    def execute_chain(self, instruction_str: str, params: dict = None) -> dict:
        """执行指令链（compose 类指令）"""
        template = INSTRUCTION_TEMPLATES.get(instruction_str, {})
        chain = template.get("chain", [])

        if not chain:
            return self.execute(instruction_str, params)

        print(f"🔗 执行指令链: {instruction_str}")
        print(f"   链: {' → '.join(chain)}")

        context = {"input": params or {}}
        results = []

        for step in chain:
            step_params = self._build_step_params(step, context)
            result = self.execute(step, step_params)
            results.append({"instruction": step, "result": result})

            if not result.get("success"):
                print(f"⚠️  链中断: {step} 失败")
                break

            # 将结果存入上下文
            context[step] = result

        return {
            "success": all(r["result"].get("success") for r in results),
            "chain": instruction_str,
            "steps": results,
            "final_output": results[-1]["result"] if results else None,
        }

    def _build_step_params(self, step: str, context: dict) -> dict:
        """根据上下文构建步骤参数"""
        template = INSTRUCTION_TEMPLATES.get(step, {})
        produces = template.get("produces")

        if step == "generate.creative":
            return {"product_info": context.get("input", {}).get("product_info", {
                "title": context.get("input", {}).get("input_value", "product"),
                "description": context.get("input", {}).get("input_value", ""),
            })}
        elif step == "generate.storyboard":
            creative = context.get("generate.creative", {}).get("creative")
            return {"creative": creative} if creative else {}
        elif step == "generate.images":
            storyboard = context.get("generate.storyboard", {}).get("storyboard")
            return {"storyboard": storyboard} if storyboard else {}
        elif step == "generate.tts":
            storyboard = context.get("generate.storyboard", {}).get("storyboard")
            return {"storyboard": storyboard} if storyboard else {}
        elif step == "generate.video":
            storyboard = context.get("generate.storyboard", {}).get("storyboard")
            images = context.get("generate.images", {})
            audio = context.get("generate.tts", {})
            return {
                "storyboard": storyboard,
                "images_dir": images.get("images_dir"),
                "audio_path": audio.get("output_path"),
            }
        return {}

    # ============ 指令分发 ============

    def _dispatch(self, instruction: Instruction) -> dict:
        """分发到具体执行器"""
        # 添加 Lead Agent 路径
        platform_dir = Path(__file__).parent.parent
        sys.path.insert(0, str(platform_dir / "agents" / "lead_agent" / "scripts"))
        sys.path.insert(0, str(platform_dir / "agents" / "creative" / "scripts"))
        sys.path.insert(0, str(platform_dir / "agents" / "storyboard" / "scripts"))
        sys.path.insert(0, str(platform_dir / "agents" / "video_gen" / "scripts"))
        sys.path.insert(0, str(platform_dir / "agents" / "tts" / "scripts"))

        target = instruction.target

        if target == "creative_script":
            return self._exec_creative(instruction)
        elif target == "storyboard":
            return self._exec_storyboard(instruction)
        elif target == "batch_images":
            return self._exec_images(instruction)
        elif target == "marketing_video":
            return self._exec_video(instruction)
        elif target == "narration_audio":
            return self._exec_tts(instruction)
        elif target == "jnpf_platform":
            return self._exec_jnpf(instruction)
        elif target == "asset_registry":
            return self._exec_accumulate(instruction)
        else:
            return {"success": False, "error": f"未知目标: {target}"}

    def _exec_creative(self, instruction: Instruction) -> dict:
        from creative_gen import generate_creative
        creative = generate_creative(
            product_info=instruction.params.get("product_info", {}),
            num_scenes=instruction.params.get("num_scenes", 6),
        )
        asset_path = str(self.registry_path / f"creative_{creative['creative_id']}.json")
        with open(asset_path, "w", encoding="utf-8") as f:
            json.dump(creative, f, ensure_ascii=False, indent=2)
        return {"success": True, "creative": creative, "asset_path": asset_path}

    def _exec_storyboard(self, instruction: Instruction) -> dict:
        from storyboard_gen import generate_storyboard
        storyboard = generate_storyboard(
            creative=instruction.params.get("creative", {}),
            aspect_ratio=instruction.params.get("aspect_ratio", "9:16"),
        )
        asset_path = str(self.registry_path / f"storyboard_{storyboard['storyboard_id']}.json")
        with open(asset_path, "w", encoding="utf-8") as f:
            json.dump(storyboard, f, ensure_ascii=False, indent=2)
        return {"success": True, "storyboard": storyboard, "asset_path": asset_path}

    def _exec_images(self, instruction: Instruction) -> dict:
        # 图片生成降级为占位图
        storyboard = instruction.params.get("storyboard", {})
        images_dir = str(self.registry_path / f"images_{uuid.uuid4().hex[:8]}")
        Path(images_dir).mkdir(parents=True, exist_ok=True)
        try:
            from PIL import Image, ImageDraw
            colors = [(255, 105, 180), (100, 149, 237), (144, 238, 144)]
            for shot in storyboard.get("shots", []):
                shot_id = shot.get("shot_id", 1)
                img = Image.new("RGB", (1080, 1920), colors[(shot_id - 1) % len(colors)])
                draw = ImageDraw.Draw(img)
                draw.text((540, 960), f"Shot {shot_id}", fill="white", anchor="mm")
                img.save(Path(images_dir) / f"shot_{shot_id}.png")
        except ImportError:
            pass
        return {"success": True, "images_dir": images_dir, "asset_path": images_dir, "degraded": True}

    def _exec_video(self, instruction: Instruction) -> dict:
        from video_compose import compose_video
        result = compose_video(
            storyboard=instruction.params.get("storyboard", {}),
            images_dir=instruction.params.get("images_dir", ""),
            output_dir=str(self.registry_path / "videos"),
            audio_path=instruction.params.get("audio_path"),
            burn_subs=True,
        )
        return result

    def _exec_tts(self, instruction: Instruction) -> dict:
        from tts_gen import generate_narration
        result = generate_narration(
            storyboard=instruction.params.get("storyboard", {}),
            output_dir=str(self.registry_path / "audio"),
            voice=instruction.params.get("voice", "xiaoxiao"),
        )
        return result

    def _exec_jnpf(self, instruction: Instruction) -> dict:
        sys.path.insert(0, str(Path(__file__).parent.parent / "platform" / "jnpf"))
        from adapter import JNPFAdapter
        adapter = JNPFAdapter(output_dir=str(self.registry_path / "jnpf"))
        config = adapter.export_full_config()
        return {"success": True, "config": config, "asset_path": str(self.registry_path / "jnpf" / "jnpf_config.json")}

    def _exec_accumulate(self, instruction: Instruction) -> dict:
        asset = Asset(
            asset_id=f"asset_{uuid.uuid4().hex[:8]}",
            name=instruction.params.get("asset_name", "unnamed"),
            type=instruction.params.get("asset_type", "unknown"),
            version="1.0.0",
            path=instruction.params.get("asset_path", ""),
            created_at=time.time(),
        )
        self.assets[asset.asset_id] = asset
        self._save_registry()
        return {"success": True, "asset_id": asset.asset_id, "asset_path": asset.path}

    # ============ 资产累积 ============

    def _accumulate_asset(self, instruction: Instruction, result: dict):
        """累积资产到注册表"""
        asset_path = result.get("asset_path")
        if not asset_path:
            return

        asset = Asset(
            asset_id=f"asset_{uuid.uuid4().hex[:8]}",
            name=instruction.target,
            type=instruction.type.value,
            version="1.0.0",
            path=asset_path,
            metadata={
                "instruction_id": instruction.instruction_id,
                "instruction_type": instruction.type.value,
            },
            created_at=time.time(),
        )
        self.assets[asset.asset_id] = asset
        self._save_registry()
        print(f"📦 资产累积: {asset.name} ({asset.asset_id})")

    # ============ 资产查询 ============

    def list_assets(self) -> list:
        """列出所有资产"""
        return [
            {
                "asset_id": a.asset_id,
                "name": a.name,
                "type": a.type,
                "version": a.version,
                "path": a.path,
                "reuse_count": a.reuse_count,
                "created_at": datetime.fromtimestamp(a.created_at).isoformat() if a.created_at else None,
            }
            for a in self.assets.values()
        ]

    def get_asset(self, asset_id: str) -> Optional[Asset]:
        """获取资产"""
        return self.assets.get(asset_id)

    def reuse_asset(self, asset_id: str) -> dict:
        """复用资产（增加复用计数）"""
        asset = self.assets.get(asset_id)
        if not asset:
            return {"success": False, "error": "资产不存在"}
        asset.reuse_count += 1
        self._save_registry()
        return {"success": True, "asset_id": asset_id, "reuse_count": asset.reuse_count}

    # ============ 指令清单 ============

    def list_instructions(self) -> list:
        """列出所有可用指令"""
        return [
            {
                "instruction": key,
                "type": tpl["type"].value,
                "target": tpl["target"],
                "description": tpl.get("description", ""),
                "produces": tpl.get("produces"),
                "chain": tpl.get("chain", []),
            }
            for key, tpl in INSTRUCTION_TEMPLATES.items()
        ]


# ============================================================================
# CLI 入口
# ============================================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(description="复利系统指令集")
    parser.add_argument(
        "--action",
        choices=["list", "assets", "execute", "chain"],
        default="list",
    )
    parser.add_argument("--instruction", help="指令名称")
    parser.add_argument("--params-json", help="参数 JSON 文件")
    parser.add_argument("--registry", default="/mnt/user-data/workspace/compound_registry")

    args = parser.parse_args()
    engine = CompoundInstructionEngine(registry_path=args.registry)

    if args.action == "list":
        print(json.dumps(engine.list_instructions(), ensure_ascii=False, indent=2))
    elif args.action == "assets":
        print(json.dumps(engine.list_assets(), ensure_ascii=False, indent=2))
    elif args.action == "execute":
        if not args.instruction:
            print("错误: 需要 --instruction")
            return 1
        params = {}
        if args.params_json:
            with open(args.params_json, "r", encoding="utf-8") as f:
                params = json.load(f)
        result = engine.execute(args.instruction, params)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0 if result.get("success") else 1
    elif args.action == "chain":
        if not args.instruction:
            print("错误: 需要 --instruction")
            return 1
        params = {}
        if args.params_json:
            with open(args.params_json, "r", encoding="utf-8") as f:
                params = json.load(f)
        result = engine.execute_chain(args.instruction, params)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0 if result.get("success") else 1

    return 0


if __name__ == "__main__":
    exit(main())
