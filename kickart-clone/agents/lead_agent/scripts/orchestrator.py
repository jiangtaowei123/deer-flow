"""
Lead Agent 编排器 - 自主调度全流程
整合 Product Parser / Creative / Storyboard / Image Gen / TTS / Video Gen
支持任务规划、Agent 调度、失败降级、状态跟踪
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

# 添加各 Agent 脚本路径
# __file__ = .../agents/lead_agent/scripts/orchestrator.py
# AGENTS_DIR = .../agents
AGENTS_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(AGENTS_DIR / "creative" / "scripts"))
sys.path.insert(0, str(AGENTS_DIR / "storyboard" / "scripts"))
sys.path.insert(0, str(AGENTS_DIR / "video_gen" / "scripts"))
sys.path.insert(0, str(AGENTS_DIR / "tts" / "scripts"))
sys.path.insert(0, str(AGENTS_DIR.parent / "skills" / "product-parse" / "scripts"))

from creative_gen import generate_creative, detect_category
from storyboard_gen import generate_storyboard
from video_compose import compose_video
from tts_gen import generate_narration


# ============ 状态机定义 ============

class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    DEGRADED = "degraded"  # 降级成功


class WorkflowType(str, Enum):
    IMAGE = "image"          # 仅生成图片
    VIDEO = "video"          # 完整视频流程
    STORYBOARD = "storyboard"  # 仅生成分镜（不生成图片/视频）


@dataclass
class AgentTask:
    """单个 Agent 任务"""
    task_id: str
    agent_name: str
    action: str
    inputs: dict
    outputs: dict = field(default_factory=dict)
    status: TaskStatus = TaskStatus.PENDING
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    error: Optional[str] = None
    retries: int = 0
    degraded: bool = False


@dataclass
class WorkflowRun:
    """一次完整的工作流执行"""
    run_id: str
    workflow_type: WorkflowType
    input_value: str  # 商品 URL/ID/描述
    tasks: list = field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    final_outputs: dict = field(default_factory=dict)
    degradation_log: list = field(default_factory=list)


# ============ Lead Agent 编排器 ============

class LeadAgentOrchestrator:
    """
    Lead Agent - 自主调度全流程

    工作流：
    1. 解析用户输入（URL/ID/描述）
    2. 规划任务链
    3. 依次调度 Agent
    4. 失败降级
    5. 汇总交付
    """

    # Agent 注册表
    AGENT_REGISTRY = {
        "product_parser": {
            "description": "商品信息解析",
            "required": True,
            "fallback": "manual_input",
        },
        "creative": {
            "description": "创意脚本生成",
            "required": True,
            "fallback": "generic_template",
        },
        "storyboard": {
            "description": "分镜设计",
            "required": True,
            "fallback": "simple_shots",
        },
        "image_gen": {
            "description": "图像生成",
            "required": False,  # 视频流程可选（可用占位图）
            "fallback": "placeholder_images",
        },
        "tts": {
            "description": "TTS 旁白",
            "required": False,
            "fallback": "silence_audio",
        },
        "video_gen": {
            "description": "视频合成",
            "required": True,
            "fallback": None,  # 无降级
        },
    }

    # 最大重试次数
    MAX_RETRIES = 3

    # 单任务超时（秒）
    TASK_TIMEOUT = 120

    def __init__(self, output_dir: str = "/mnt/user-data/workspace/lead_agent_runs"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.runs: dict[str, WorkflowRun] = {}

    # ============ 任务规划 ============

    def plan_workflow(
        self,
        input_value: str,
        workflow_type: WorkflowType = WorkflowType.VIDEO,
        num_scenes: int = 6,
        aspect_ratio: str = "9:16",
        voice: str = "xiaoxiao",
    ) -> WorkflowRun:
        """规划工作流任务链"""
        run_id = f"run_{uuid.uuid4().hex[:8]}"
        run = WorkflowRun(
            run_id=run_id,
            workflow_type=workflow_type,
            input_value=input_value,
            started_at=time.time(),
        )

        # 通用：商品解析
        run.tasks.append(AgentTask(
            task_id=f"{run_id}_t1_parse",
            agent_name="product_parser",
            action="parse",
            inputs={"input_value": input_value},
        ))

        # 通用：创意脚本
        run.tasks.append(AgentTask(
            task_id=f"{run_id}_t2_creative",
            agent_name="creative",
            action="generate",
            inputs={"num_scenes": num_scenes},
        ))

        # 通用：分镜
        run.tasks.append(AgentTask(
            task_id=f"{run_id}_t3_storyboard",
            agent_name="storyboard",
            action="generate",
            inputs={"aspect_ratio": aspect_ratio},
        ))

        if workflow_type == WorkflowType.VIDEO:
            # 图片生成（可选）
            run.tasks.append(AgentTask(
                task_id=f"{run_id}_t4_image_gen",
                agent_name="image_gen",
                action="batch_generate",
                inputs={"num_variants": 1},
            ))
            # TTS
            run.tasks.append(AgentTask(
                task_id=f"{run_id}_t5_tts",
                agent_name="tts",
                action="generate",
                inputs={"voice": voice},
            ))
            # 视频合成
            run.tasks.append(AgentTask(
                task_id=f"{run_id}_t6_video",
                agent_name="video_gen",
                action="compose",
                inputs={"aspect_ratio": aspect_ratio},
            ))
        elif workflow_type == WorkflowType.IMAGE:
            run.tasks.append(AgentTask(
                task_id=f"{run_id}_t4_image_gen",
                agent_name="image_gen",
                action="batch_generate",
                inputs={"num_variants": 10},
            ))

        self.runs[run_id] = run
        return run

    # ============ Agent 调度 ============

    def execute_workflow(self, run_id: str) -> WorkflowRun:
        """执行完整工作流"""
        run = self.runs[run_id]
        run.status = TaskStatus.RUNNING

        print(f"\n🚀 Lead Agent 启动工作流: {run_id}")
        print(f"   类型: {run.workflow_type.value}")
        print(f"   输入: {run.input_value[:80]}")
        print(f"   任务数: {len(run.tasks)}")
        print("=" * 60)

        # 上下文：传递给后续任务
        context = {"input_value": run.input_value}

        for idx, task in enumerate(run.tasks, 1):
            print(f"\n📍 [{idx}/{len(run.tasks)}] {task.agent_name} - {task.action}")
            task.status = TaskStatus.RUNNING
            task.started_at = time.time()

            success = self._execute_task(task, context, run)

            if success:
                task.status = TaskStatus.SUCCESS
                task.completed_at = time.time()
                duration = task.completed_at - task.started_at
                print(f"   ✅ 成功 ({duration:.1f}s)")
            else:
                # 尝试降级
                degraded = self._try_degrade(task, context, run)
                if degraded:
                    task.status = TaskStatus.DEGRADED
                    task.degraded = True
                    task.completed_at = time.time()
                    print(f"   ⚠️  降级成功")
                else:
                    task.status = TaskStatus.FAILED
                    task.completed_at = time.time()
                    print(f"   ❌ 失败: {task.error}")

                    # 必需任务失败则终止
                    agent_cfg = self.AGENT_REGISTRY.get(task.agent_name, {})
                    if agent_cfg.get("required", False):
                        print(f"\n⛔ 必需任务失败，终止工作流")
                        run.status = TaskStatus.FAILED
                        run.completed_at = time.time()
                        run.final_outputs = {
                            "success": False,
                            "error": f"Required agent '{task.agent_name}' failed: {task.error}",
                            "completed_tasks": [t.task_id for t in run.tasks if t.status in (TaskStatus.SUCCESS, TaskStatus.DEGRADED)],
                        }
                        self._save_run(run)
                        return run

        # 全部完成
        run.status = TaskStatus.SUCCESS
        run.completed_at = time.time()
        run.final_outputs = self._build_final_outputs(run, context)

        total_duration = run.completed_at - run.started_at
        print(f"\n{'=' * 60}")
        print(f"🎉 工作流完成！")
        print(f"   总耗时: {total_duration:.1f}s")
        print(f"   成功: {sum(1 for t in run.tasks if t.status == TaskStatus.SUCCESS)}")
        print(f"   降级: {sum(1 for t in run.tasks if t.status == TaskStatus.DEGRADED)}")
        print(f"   失败: {sum(1 for t in run.tasks if t.status == TaskStatus.FAILED)}")
        if run.degradation_log:
            print(f"   降级记录: {len(run.degradation_log)} 条")

        self._save_run(run)
        return run

    def _execute_task(self, task: AgentTask, context: dict, run: WorkflowRun) -> bool:
        """执行单个 Agent 任务（带重试）"""
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                task.retries = attempt - 1
                result = self._dispatch_agent(task, context)
                if result.get("success", False):
                    task.outputs = result
                    # 将输出合并到上下文
                    context[task.agent_name] = result
                    return True
                else:
                    task.error = result.get("error", "未知错误")
                    if attempt < self.MAX_RETRIES:
                        print(f"   🔄 重试 {attempt}/{self.MAX_RETRIES}: {task.error}")
                        time.sleep(1 * attempt)
            except Exception as e:
                task.error = f"{type(e).__name__}: {str(e)}"
                if attempt < self.MAX_RETRIES:
                    print(f"   🔄 重试 {attempt}/{self.MAX_RETRIES}: {task.error}")
                    time.sleep(1 * attempt)

        return False

    def _dispatch_agent(self, task: AgentTask, context: dict) -> dict:
        """分发到具体 Agent"""
        agent = task.agent_name

        if agent == "product_parser":
            return self._run_product_parser(task, context)
        elif agent == "creative":
            return self._run_creative(task, context)
        elif agent == "storyboard":
            return self._run_storyboard(task, context)
        elif agent == "image_gen":
            return self._run_image_gen(task, context)
        elif agent == "tts":
            return self._run_tts(task, context)
        elif agent == "video_gen":
            return self._run_video_gen(task, context)
        else:
            return {"success": False, "error": f"未知 Agent: {agent}"}

    # ============ 各 Agent 执行器 ============

    def _run_product_parser(self, task: AgentTask, context: dict) -> dict:
        """商品解析"""
        try:
            from parse import ProductParser
            parser = ProductParser()
            product_info = parser.parse(task.inputs["input_value"])

            if "error" in product_info:
                return {"success": False, "error": product_info["error"]}

            return {"success": True, "product_info": product_info}
        except ImportError:
            # 降级：使用输入作为商品描述
            return {
                "success": True,
                "product_info": {
                    "product_id": "manual",
                    "title": task.inputs["input_value"][:100],
                    "description": task.inputs["input_value"],
                    "category": "generic",
                },
                "degraded": True,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _run_creative(self, task: AgentTask, context: dict) -> dict:
        """创意脚本生成"""
        product_info = context.get("product_parser", {}).get("product_info", {})
        if not product_info:
            return {"success": False, "error": "缺少商品信息"}

        try:
            creative = generate_creative(
                product_info=product_info,
                num_scenes=task.inputs.get("num_scenes", 6),
            )
            return {"success": True, "creative": creative}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _run_storyboard(self, task: AgentTask, context: dict) -> dict:
        """分镜生成"""
        creative = context.get("creative", {}).get("creative")
        if not creative:
            return {"success": False, "error": "缺少创意脚本"}

        try:
            storyboard = generate_storyboard(
                creative=creative,
                aspect_ratio=task.inputs.get("aspect_ratio", "9:16"),
            )
            return {"success": True, "storyboard": storyboard}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _run_image_gen(self, task: AgentTask, context: dict) -> dict:
        """图像生成 - 调用 SD WebUI"""
        storyboard = context.get("storyboard", {}).get("storyboard")
        if not storyboard:
            return {"success": False, "error": "缺少分镜"}

        try:
            # 尝试调用 SD WebUI
            sys.path.insert(0, "/workspace/skills/public/amazon-product-image/scripts")
            from generate import StableDiffusionBatchGenerator

            product_info = context.get("product_parser", {}).get("product_info", {})
            generator = StableDiffusionBatchGenerator(
                sd_url=os.environ.get("SD_WEBUI_URL", "http://localhost:7860"),
                output_dir=str(self.output_dir / "images"),
            )

            shots = storyboard.get("shots", [])
            prompts = [s.get("positive_prompt", "") for s in shots]
            negatives = [s.get("negative_prompt", "") for s in shots]

            result = generator.batch_generate(
                product_description=product_info.get("title", "product"),
                scenes=[],  # 直接使用 prompts
                product_id=product_info.get("product_id", "unknown"),
                num_variants=task.inputs.get("num_variants", 1),
                custom_prompts=prompts,
                custom_negatives=negatives,
            )

            if result.get("success"):
                return {"success": True, "images": result.get("images", []), "images_dir": result.get("output_dir")}
            return {"success": False, "error": result.get("error", "SD 生成失败")}
        except Exception as e:
            return {"success": False, "error": f"image_gen 异常: {str(e)}"}

    def _run_tts(self, task: AgentTask, context: dict) -> dict:
        """TTS 旁白生成"""
        storyboard = context.get("storyboard", {}).get("storyboard")
        if not storyboard:
            return {"success": False, "error": "缺少分镜"}

        try:
            result = generate_narration(
                storyboard=storyboard,
                output_dir=str(self.output_dir / "audio"),
                voice=task.inputs.get("voice", "xiaoxiao"),
            )
            return result
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _run_video_gen(self, task: AgentTask, context: dict) -> dict:
        """视频合成"""
        storyboard = context.get("storyboard", {}).get("storyboard")
        if not storyboard:
            return {"success": False, "error": "缺少分镜"}

        # 图片目录：优先用 SD 生成的，否则用占位图
        images_dir = context.get("image_gen", {}).get("images_dir")
        if not images_dir:
            images_dir = str(self.output_dir / "placeholder_images")
            self._ensure_placeholder_images(storyboard, images_dir)

        # 音频路径
        audio_path = context.get("tts", {}).get("output_path")

        try:
            result = compose_video(
                storyboard=storyboard,
                images_dir=images_dir,
                output_dir=str(self.output_dir / "videos"),
                audio_path=audio_path,
                burn_subs=True,
                aspect_ratio=task.inputs.get("aspect_ratio", "9:16"),
            )
            return result
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ============ 失败降级 ============

    def _try_degrade(self, task: AgentTask, context: dict, run: WorkflowRun) -> bool:
        """尝试降级方案"""
        agent_cfg = self.AGENT_REGISTRY.get(task.agent_name, {})
        fallback = agent_cfg.get("fallback")

        if not fallback:
            return False

        degradation_entry = {
            "task_id": task.task_id,
            "agent": task.agent_name,
            "original_error": task.error,
            "fallback": fallback,
            "timestamp": datetime.now().isoformat(),
        }

        try:
            if fallback == "manual_input":
                # 商品解析降级：使用原始输入作为商品信息
                context[task.agent_name] = {
                    "success": True,
                    "product_info": {
                        "product_id": "manual",
                        "title": task.inputs["input_value"][:100],
                        "description": task.inputs["input_value"],
                        "category": "generic",
                    },
                    "degraded": True,
                }
                task.outputs = context[task.agent_name]
                degradation_entry["result"] = "使用原始输入作为商品信息"
                run.degradation_log.append(degradation_entry)
                return True

            elif fallback == "generic_template":
                # 创意降级：使用通用模板
                product_info = context.get("product_parser", {}).get("product_info", {})
                creative = generate_creative(
                    product_info=product_info,
                    category="generic",
                    num_scenes=task.inputs.get("num_scenes", 6),
                )
                context[task.agent_name] = {"success": True, "creative": creative, "degraded": True}
                task.outputs = context[task.agent_name]
                degradation_entry["result"] = "使用通用创意模板"
                run.degradation_log.append(degradation_entry)
                return True

            elif fallback == "simple_shots":
                # 分镜降级：简单分镜
                creative = context.get("creative", {}).get("creative", {})
                storyboard = generate_storyboard(creative=creative)
                context[task.agent_name] = {"success": True, "storyboard": storyboard, "degraded": True}
                task.outputs = context[task.agent_name]
                degradation_entry["result"] = "使用简单分镜"
                run.degradation_log.append(degradation_entry)
                return True

            elif fallback == "placeholder_images":
                # 图片降级：占位图
                storyboard = context.get("storyboard", {}).get("storyboard", {})
                images_dir = str(self.output_dir / "placeholder_images")
                self._ensure_placeholder_images(storyboard, images_dir)
                context[task.agent_name] = {
                    "success": True,
                    "images_dir": images_dir,
                    "degraded": True,
                }
                task.outputs = context[task.agent_name]
                degradation_entry["result"] = "使用占位图"
                run.degradation_log.append(degradation_entry)
                return True

            elif fallback == "silence_audio":
                # TTS 降级：静音音频
                storyboard = context.get("storyboard", {}).get("storyboard", {})
                audio_dir = self.output_dir / "audio"
                audio_dir.mkdir(parents=True, exist_ok=True)
                # 生成静音音频
                import subprocess
                total_duration = sum(s.get("duration_sec", 5) for s in storyboard.get("shots", []))
                audio_path = str(audio_dir / f"silence_{uuid.uuid4().hex[:8]}.aac")
                cmd = [
                    "ffmpeg", "-y",
                    "-f", "lavfi",
                    "-i", f"anullsrc=channel_layout=stereo:sample_rate=44100",
                    "-t", str(total_duration),
                    "-c:a", "aac",
                    audio_path,
                ]
                subprocess.run(cmd, capture_output=True, timeout=30)
                context[task.agent_name] = {
                    "success": True,
                    "output_path": audio_path,
                    "degraded": True,
                }
                task.outputs = context[task.agent_name]
                degradation_entry["result"] = "使用静音音频"
                run.degradation_log.append(degradation_entry)
                return True

        except Exception as e:
            degradation_entry["result"] = f"降级失败: {str(e)}"
            run.degradation_log.append(degradation_entry)
            return False

        return False

    def _ensure_placeholder_images(self, storyboard: dict, images_dir: str):
        """确保占位图存在"""
        Path(images_dir).mkdir(parents=True, exist_ok=True)
        try:
            from PIL import Image, ImageDraw
            colors = [(255, 105, 180), (100, 149, 237), (144, 238, 144),
                      (255, 165, 0), (186, 85, 211), (255, 215, 0)]
            for shot in storyboard.get("shots", []):
                shot_id = shot.get("shot_id", 1)
                img_path = Path(images_dir) / f"shot_{shot_id}.png"
                if not img_path.exists():
                    color = colors[(shot_id - 1) % len(colors)]
                    img = Image.new("RGB", (1080, 1920), color)
                    draw = ImageDraw.Draw(img)
                    draw.text((540, 960), f"Shot {shot_id}", fill="white", anchor="mm")
                    img.save(img_path)
        except ImportError:
            pass

    # ============ 结果汇总 ============

    def _build_final_outputs(self, run: WorkflowRun, context: dict) -> dict:
        """构建最终交付物"""
        outputs = {
            "success": True,
            "run_id": run.run_id,
            "workflow_type": run.workflow_type.value,
            "started_at": datetime.fromtimestamp(run.started_at).isoformat() if run.started_at else None,
            "completed_at": datetime.fromtimestamp(run.completed_at).isoformat() if run.completed_at else None,
            "total_duration_sec": round(run.completed_at - run.started_at, 2) if run.completed_at and run.started_at else None,
            "tasks_summary": [
                {
                    "task_id": t.task_id,
                    "agent": t.agent_name,
                    "action": t.action,
                    "status": t.status.value,
                    "degraded": t.degraded,
                    "retries": t.retries,
                    "duration_sec": round(t.completed_at - t.started_at, 2) if t.completed_at and t.started_at else None,
                }
                for t in run.tasks
            ],
            "degradation_log": run.degradation_log,
            "artifacts": {},
        }

        # 收集产物
        if "product_parser" in context:
            outputs["artifacts"]["product_info"] = context["product_parser"].get("product_info")
        if "creative" in context:
            outputs["artifacts"]["creative"] = context["creative"].get("creative")
        if "storyboard" in context:
            outputs["artifacts"]["storyboard"] = context["storyboard"].get("storyboard")
        if "image_gen" in context:
            outputs["artifacts"]["images_dir"] = context["image_gen"].get("images_dir")
        if "tts" in context:
            outputs["artifacts"]["audio_path"] = context["tts"].get("output_path")
        if "video_gen" in context:
            outputs["artifacts"]["video"] = context["video_gen"]

        return outputs

    def _save_run(self, run: WorkflowRun):
        """保存运行记录"""
        run_file = self.output_dir / f"{run.run_id}.json"
        with open(run_file, "w", encoding="utf-8") as f:
            json.dump(run.final_outputs, f, ensure_ascii=False, indent=2, default=str)

    # ============ 查询接口 ============

    def get_run(self, run_id: str) -> Optional[WorkflowRun]:
        return self.runs.get(run_id)

    def list_runs(self) -> list:
        return list(self.runs.values())


# ============ CLI 入口 ============

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Lead Agent 编排器")
    parser.add_argument(
        "--input",
        required=True,
        help="商品 URL/ID/描述",
    )
    parser.add_argument(
        "--workflow",
        default="video",
        choices=["image", "video", "storyboard"],
        help="工作流类型",
    )
    parser.add_argument("--num-scenes", type=int, default=6)
    parser.add_argument("--aspect-ratio", default="9:16")
    parser.add_argument("--voice", default="xiaoxiao")
    parser.add_argument(
        "--output-dir",
        default="/mnt/user-data/workspace/lead_agent_runs",
    )

    args = parser.parse_args()

    orchestrator = LeadAgentOrchestrator(output_dir=args.output_dir)
    run = orchestrator.plan_workflow(
        input_value=args.input,
        workflow_type=WorkflowType(args.workflow),
        num_scenes=args.num_scenes,
        aspect_ratio=args.aspect_ratio,
        voice=args.voice,
    )
    result = orchestrator.execute_workflow(run.run_id)

    print(f"\n{'=' * 60}")
    print(f"📦 最终交付:")
    print(json.dumps(result.final_outputs.get("artifacts", {}).get("video", {}), ensure_ascii=False, indent=2))

    return 0 if result.final_outputs.get("success") else 1


if __name__ == "__main__":
    exit(main())
