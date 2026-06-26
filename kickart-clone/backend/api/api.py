"""
Kickart Clone - 批量生成 API
整合 Product Parser + Image Generator，提供端到端 HTTP API
"""
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

# 添加项目路径
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "skills" / "product-parse" / "scripts"))
sys.path.insert(0, str("/workspace/skills/public/amazon-product-image/scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "backend" / "api"))

from parse import ProductParser
from generate import StableDiffusionBatchGenerator
from platform_routes import router as platform_router

app = FastAPI(
    title="Kickart Clone API",
    description="一站式营销创作平台 - 商品解析 + 批量图像生成 + 多 Agent 编排 + 平台能力",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载平台路由（V3-V7 所有模块）
app.include_router(platform_router)

# 静态文件服务（前端）
FRONTEND_DIR = PROJECT_ROOT / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

# 任务存储（生产环境应使用数据库）
TASKS_DB = {}


# ============================================================================
# 数据模型
# ============================================================================

class GenerateRequest(BaseModel):
    """批量生成请求"""
    product_url: Optional[str] = Field(None, description="商品URL（Amazon/Shopify等）")
    product_image: Optional[str] = Field(None, description="商品图片路径")
    product_description: Optional[str] = Field(None, description="商品描述（手动指定）")
    product_id: Optional[str] = Field(None, description="商品ID（用于文件命名）")
    scenes: list[str] = Field(
        default=["studio"],
        description="场景列表：studio, outdoor_urban, outdoor_cafe, minimal_abstract, nature_outdoor, lifestyle_home, beach_resort, office_business, gym_fitness, luxury_interior, autumn_park, night_city, studio_color, rooftop, vintage_retro"
    )
    num_variants: int = Field(default=2, ge=1, le=5, description="每场景变体数")
    include_arms: bool = Field(default=True, description="强制显示双臂")
    enable_hr: bool = Field(default=True, description="启用高清修复")
    custom_prompt: Optional[str] = Field(None, description="自定义正向提示词")
    custom_negative: Optional[str] = Field(None, description="自定义负向提示词")
    sd_url: str = Field(default="http://127.0.0.1:7860", description="SD WebUI 地址")
    output_dir: str = Field(default="/mnt/user-data/outputs", description="输出目录")


class TaskStatus(BaseModel):
    """任务状态"""
    task_id: str
    status: str  # pending | parsing | generating | completed | failed
    progress: float = 0.0
    product_info: Optional[dict] = None
    results: Optional[dict] = None
    error: Optional[str] = None
    created_at: float
    updated_at: float


class TaskResponse(BaseModel):
    """任务响应"""
    task_id: str
    status: str
    message: str


# ============================================================================
# 核心工作流
# ============================================================================

def run_generation_workflow(task_id: str, request: GenerateRequest):
    """异步执行生成工作流"""
    task = TASKS_DB[task_id]
    try:
        # 阶段 1: 商品解析
        task["status"] = "parsing"
        task["updated_at"] = time.time()
        TASKS_DB[task_id] = task

        product_description = request.product_description
        product_id = request.product_id or f"product-{uuid.uuid4().hex[:8]}"

        if not product_description:
            parser = ProductParser()
            input_value = request.product_url or request.product_image
            if not input_value:
                raise ValueError("必须提供 product_url、product_image 或 product_description")

            product_info = parser.parse(input_value)
            task["product_info"] = product_info
            task["updated_at"] = time.time()
            TASKS_DB[task_id] = task

            if "error" in product_info:
                raise ValueError(product_info["error"])

            product_description = product_info.get("title", "") or "fashion product"
            if product_info.get("brand"):
                product_description = f"{product_info['brand']} {product_description}"

        # 阶段 2: 批量生成
        task["status"] = "generating"
        task["progress"] = 0.3
        task["updated_at"] = time.time()
        TASKS_DB[task_id] = task

        generator = StableDiffusionBatchGenerator(
            sd_url=request.sd_url,
            output_dir=request.output_dir,
            num_parallel=2,
        )

        # 构建默认提示词
        if not request.custom_prompt:
            custom_prompt = (
                f"Professional e-commerce fashion photography, beautiful Asian female model, "
                f"wearing {product_description}, full body view, both arms visible, "
                f"standing pose, fashion editorial style, ultra sharp focus, "
                f"8k ultra high definition, commercial product photography"
            )
        else:
            custom_prompt = request.custom_prompt

        if not request.custom_negative:
            custom_negative = (
                "blurry, low quality, deformed, bad anatomy, bad proportions, "
                "extra limbs, missing fingers, ugly, poorly drawn face, mutation, "
                "watermark, text, logo, one arm hidden, single arm, missing arm, "
                "arm behind back, arm cut off"
            )
        else:
            custom_negative = request.custom_negative

        custom_prompts = {scene: custom_prompt for scene in request.scenes}
        custom_negatives = {scene: custom_negative for scene in request.scenes}

        result = generator.batch_generate(
            product_description=product_description,
            scenes=request.scenes,
            product_id=product_id,
            num_variants=request.num_variants,
            custom_prompts=custom_prompts,
            custom_negatives=custom_negatives,
            include_arms=request.include_arms,
            enable_hr=request.enable_hr,
        )

        task["progress"] = 1.0
        task["results"] = result
        task["status"] = "completed" if result.get("success") else "failed"
        task["updated_at"] = time.time()
        TASKS_DB[task_id] = task

    except Exception as e:
        task["status"] = "failed"
        task["error"] = str(e)
        task["updated_at"] = time.time()
        TASKS_DB[task_id] = task


# ============================================================================
# API 端点
# ============================================================================

@app.get("/health")
async def health_check():
    """健康检查"""
    return {
        "status": "ok",
        "service": "kickart-clone-api",
        "version": "0.1.0",
        "timestamp": time.time(),
    }


@app.get("/scenes")
async def list_scenes():
    """列出所有可用场景模板"""
    templates_dir = PROJECT_ROOT / "templates" / "scenes"
    scenes = []
    if templates_dir.exists():
        for f in templates_dir.glob("*.json"):
            with open(f, "r", encoding="utf-8") as fp:
                data = json.load(fp)
                scenes.append({
                    "id": data.get("scene_type", f.stem),
                    "name": data.get("scene_name", f.stem),
                    "description": data.get("scene_description", ""),
                })
    return {"scenes": scenes, "total": len(scenes)}


@app.post("/generate", response_model=TaskResponse)
async def create_generation_task(
    request: GenerateRequest,
    background_tasks: BackgroundTasks,
):
    """创建批量生成任务（异步）"""
    task_id = f"task-{uuid.uuid4().hex[:12]}"

    TASKS_DB[task_id] = {
        "task_id": task_id,
        "status": "pending",
        "progress": 0.0,
        "product_info": None,
        "results": None,
        "error": None,
        "created_at": time.time(),
        "updated_at": time.time(),
        "request": request.dict(),
    }

    background_tasks.add_task(run_generation_workflow, task_id, request)

    return TaskResponse(
        task_id=task_id,
        status="pending",
        message=f"任务已创建，预计生成 {len(request.scenes) * request.num_variants} 张图片",
    )


@app.get("/tasks/{task_id}", response_model=TaskStatus)
async def get_task_status(task_id: str):
    """查询任务状态"""
    if task_id not in TASKS_DB:
        raise HTTPException(status_code=404, detail="任务不存在")
    task = TASKS_DB[task_id]
    return TaskStatus(**task)


@app.get("/tasks")
async def list_tasks(limit: int = 20):
    """列出所有任务"""
    tasks = list(TASKS_DB.values())
    tasks.sort(key=lambda x: x["created_at"], reverse=True)
    return {
        "tasks": tasks[:limit],
        "total": len(TASKS_DB),
    }


@app.delete("/tasks/{task_id}")
async def delete_task(task_id: str):
    """删除任务"""
    if task_id not in TASKS_DB:
        raise HTTPException(status_code=404, detail="任务不存在")
    del TASKS_DB[task_id]
    return {"message": f"任务 {task_id} 已删除"}


@app.post("/generate/sync")
async def generate_sync(request: GenerateRequest):
    """同步生成（适合小批量，会阻塞直到完成）"""
    task_id = f"task-{uuid.uuid4().hex[:12]}"
    TASKS_DB[task_id] = {
        "task_id": task_id,
        "status": "pending",
        "progress": 0.0,
        "product_info": None,
        "results": None,
        "error": None,
        "created_at": time.time(),
        "updated_at": time.time(),
        "request": request.dict(),
    }
    run_generation_workflow(task_id, request)
    return TASKS_DB[task_id]


# ============================================================================
# Lead Agent 编排 API（V2 阶段）
# ============================================================================

# 添加 Lead Agent 路径
sys.path.insert(0, str(PROJECT_ROOT / "agents" / "lead_agent" / "scripts"))

from orchestrator import LeadAgentOrchestrator, WorkflowType

# 全局编排器实例
LEAD_AGENT = LeadAgentOrchestrator(
    output_dir=os.environ.get("LEAD_AGENT_OUTPUT_DIR", "/mnt/user-data/workspace/lead_agent_runs")
)


class OrchestrateRequest(BaseModel):
    """Lead Agent 编排请求"""
    input_value: str = Field(..., description="商品 URL/ID/描述")
    workflow: str = Field("video", description="工作流类型：image/video/storyboard")
    num_scenes: int = Field(6, ge=3, le=10, description="场景数")
    aspect_ratio: str = Field("9:16", description="宽高比")
    voice: str = Field("xiaoxiao", description="TTS 音色")


@app.post("/orchestrate", response_model=TaskResponse)
async def orchestrate(request: OrchestrateRequest, background_tasks: BackgroundTasks):
    """Lead Agent 端到端编排（异步）"""
    run = LEAD_AGENT.plan_workflow(
        input_value=request.input_value,
        workflow_type=WorkflowType(request.workflow),
        num_scenes=request.num_scenes,
        aspect_ratio=request.aspect_ratio,
        voice=request.voice,
    )
    # 异步执行
    background_tasks.add_task(LEAD_AGENT.execute_workflow, run.run_id)
    return TaskResponse(
        task_id=run.run_id,
        status="running",
        message=f"Lead Agent 已启动 {request.workflow} 工作流",
    )


@app.post("/orchestrate/sync")
async def orchestrate_sync(request: OrchestrateRequest):
    """Lead Agent 端到端编排（同步，阻塞直到完成）"""
    run = LEAD_AGENT.plan_workflow(
        input_value=request.input_value,
        workflow_type=WorkflowType(request.workflow),
        num_scenes=request.num_scenes,
        aspect_ratio=request.aspect_ratio,
        voice=request.voice,
    )
    result = LEAD_AGENT.execute_workflow(run.run_id)
    return result.final_outputs


@app.get("/orchestrate/{run_id}")
async def get_orchestration(run_id: str):
    """查询编排运行状态"""
    run = LEAD_AGENT.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"运行不存在: {run_id}")
    return {
        "run_id": run.run_id,
        "workflow_type": run.workflow_type.value,
        "status": run.status.value,
        "tasks": [
            {
                "task_id": t.task_id,
                "agent": t.agent_name,
                "status": t.status.value,
                "degraded": t.degraded,
                "retries": t.retries,
            }
            for t in run.tasks
        ],
        "degradation_log": run.degradation_log,
        "final_outputs": run.final_outputs if run.status.value in ("success", "failed") else None,
    }


@app.get("/orchestrate")
async def list_orchestrations():
    """列出所有编排运行"""
    return {
        "runs": [
            {
                "run_id": r.run_id,
                "workflow_type": r.workflow_type.value,
                "status": r.status.value,
                "input": r.input_value[:80],
            }
            for r in LEAD_AGENT.list_runs()
        ]
    }


# ============================================================================
# 启动入口
# ============================================================================

@app.get("/")
async def index():
    """前端首页"""
    index_file = FRONTEND_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return {"message": "Kickart Clone API", "version": "2.0.0", "docs": "/docs"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api:app",
        host="0.0.0.0",
        port=8765,
        reload=True,
        log_level="info",
    )
