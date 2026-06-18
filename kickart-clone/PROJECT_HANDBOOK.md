# Kickart Clone 项目手册

> 版本：1.0.0 | 更新：2026-06-18 | 状态：全部 4 迭代完成（24/24 任务）

## 目录

1. [项目概述](#1-项目概述)
2. [架构设计](#2-架构设计)
3. [Agent 详解](#3-agent-详解)
4. [平台层详解](#4-平台层详解)
5. [API 参考](#5-api-参考)
6. [场景模板库](#6-场景模板库)
7. [部署指南](#7-部署指南)
8. [使用示例](#8-使用示例)
9. [测试说明](#9-测试说明)
10. [运维监控](#10-运维监控)
11. [gstack 方法论](#11-gstack-方法论)
12. [故障排查](#12-故障排查)

---

## 1. 项目概述

### 1.1 项目背景

复刻字节跳动 [Kickart](https://bytedance.larkoffice.com/docx/SKCGdayW8or20dx2vm5cixQmnBg) 一站式营销创作平台，实现从商品输入到营销视频的端到端自动化生成。

### 1.2 核心能力

| 能力 | 说明 |
|------|------|
| 商品解析 | 支持 Amazon/Shopify/淘宝/京东 URL，自动提取商品信息 |
| 创意脚本 | 5 大类目模板（服饰/电子/美妆/家居/通用），自动类目检测 |
| 分镜设计 | 镜头类型/角度/构图/光线/色彩方案，正负面提示词 |
| 图像生成 | Stable Diffusion 批量生成，ControlNet 姿势控制，LoRA 微调 |
| TTS 旁白 | edge-tts 6 音色，时长匹配，静音回退 |
| 视频合成 | Ken Burns 效果，转场拼接，字幕烧录 |
| Agent 协同 | Lead Agent 自主调度 6 个专业 Agent，失败降级 |
| 平台化 | JNPF6.2 适配，多租户，监控告警 |

### 1.3 技术栈

- **Agent 编排**：DeerFlow 架构参考 + 自研 Lead Agent
- **图像生成**：Stable Diffusion WebUI API（/sdapi/v1/txt2img, /sdapi/v1/img2img）
- **视频合成**：ffmpeg + Ken Burns + ASS/SRT 字幕
- **TTS**：edge-tts（微软 Edge 神经网络语音）
- **后端**：FastAPI + Pydantic
- **低代码平台**：JNPF6.2 适配层
- **方法论**：gstack autoplan 自动规划

### 1.4 用户规则对齐

根据用户规则，所有开发的系统都在以下基础上生成和复刻：
- ✅ JNPF6.2 低代码平台（platform/jnpf/adapter.py）
- ✅ 复利系统指令集（platform/compound/instruction_set.py）

---

## 2. 架构设计

### 2.1 分层架构

```
┌─────────────────────────────────────────────────────────────┐
│                     用户交互层（JNPF6.2）                     │
│  Dashboard │ Creative Form │ Run Detail │ Runs List         │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                    平台层（V3 平台化）                        │
│  JNPF 适配 │ 复利指令集 │ 多租户 │ 监控告警                  │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                   Lead Agent 编排层（V2）                    │
│   任务规划 → Agent 调度 → 失败降级 → 状态跟踪                │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                    专业 Agent 层（V1）                       │
│  ProductParser → Creative → Storyboard → ImageGen          │
│                                          ↓                  │
│                                   TTS → VideoGen           │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                    基础能力层（MVP）                         │
│  Stable Diffusion │ ffmpeg │ edge-tts │ 15 场景模板         │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 数据流

```
用户输入（URL/ID/描述）
    │
    ▼
[Product Parser] → 商品信息 JSON
    │
    ▼
[Creative Agent] → 创意脚本 JSON（6 场景）
    │
    ▼
[Storyboard Agent] → 分镜列表 JSON（6 分镜）
    │
    ├──────────────────┐
    ▼                  ▼
[Image Gen]        [TTS Agent]
    │                  │
    └────────┬─────────┘
             ▼
      [Video Gen] → 营销视频 MP4
```

### 2.3 迭代里程碑

| 迭代 | 名称 | 周期 | 核心交付 |
|------|------|------|----------|
| MVP-1 | 图像生成闭环 | 1周 | 商品解析 + 15 场景 + SD 批量生成 + API |
| V1-2 | 视频成片 | 2周 | Creative + Storyboard + TTS + Video 合成 |
| V2-3 | Agent 协同 | 2周 | Lead Agent 编排 + 多 Agent 调度 + 失败降级 |
| V3-4 | 平台化 | 2周 | JNPF6.2 + 复利指令集 + 多租户 + 监控告警 |

---

## 3. Agent 详解

### 3.1 Lead Agent（总指挥）

**文件**：[agents/lead_agent/scripts/orchestrator.py](file:///workspace/kickart-clone/agents/lead_agent/scripts/orchestrator.py)

**职责**：自主调度全流程，任务规划、Agent 调度、失败降级、状态跟踪。

**核心类**：`LeadAgentOrchestrator`

**工作流类型**：
- `video`：完整视频流程（6 任务）
- `image`：仅图片（4 任务）
- `storyboard`：仅分镜（3 任务）

**Agent 注册表**：

| Agent | 必需 | 降级方案 |
|-------|------|----------|
| product_parser | ✅ | manual_input（用原始输入作商品信息）|
| creative | ✅ | generic_template（通用创意模板）|
| storyboard | ✅ | simple_shots（简单分镜）|
| image_gen | ❌ | placeholder_images（占位图）|
| tts | ❌ | silence_audio（静音音频）|
| video_gen | ✅ | 无降级 |

**关键参数**：
- `MAX_RETRIES = 3`：单任务最大重试次数
- `TASK_TIMEOUT = 120`：单任务超时（秒）

**使用示例**：
```python
from orchestrator import LeadAgentOrchestrator, WorkflowType

orchestrator = LeadAgentOrchestrator(output_dir="./runs")
run = orchestrator.plan_workflow(
    input_value="https://amazon.com/dp/B0XXX",
    workflow_type=WorkflowType.VIDEO,
    num_scenes=6,
    aspect_ratio="9:16",
    voice="xiaoxiao",
)
result = orchestrator.execute_workflow(run.run_id)
```

### 3.2 Product Parser Agent（商品解析）

**文件**：[skills/product-parse/scripts/parse.py](file:///workspace/kickart-clone/skills/product-parse/scripts/parse.py)

**支持平台**：
- Amazon（ASIN 提取）
- Shopify（.json API）
- 淘宝/天猫
- 京东
- 通用 OG 标签

**输出 Schema**：
```json
{
  "product_id": "B0XXX",
  "platform": "amazon",
  "url": "https://...",
  "title": "商品标题",
  "category": "apparel",
  "description": "商品描述",
  "key_features": ["特点1", "特点2"],
  "brand": "品牌",
  "price_range": "$29.99",
  "main_image_url": "https://...",
  "gallery_urls": [],
  "selling_points": [],
  "target_audience": "general"
}
```

### 3.3 Creative Agent（创意脚本）

**文件**：[agents/creative/scripts/creative_gen.py](file:///workspace/kickart-clone/agents/creative/scripts/creative_gen.py)

**类目模板**：

| 类目 | 主题 | 目标人群 | 调性 |
|------|------|----------|------|
| apparel | 时尚穿搭日记 | 18-35岁都市女性 | 时尚、自信、生活化 |
| electronics | 科技改变生活 | 25-40岁科技爱好者 | 专业、科技感、未来感 |
| beauty | 肌肤焕新之旅 | 20-40岁爱美女性 | 温柔、治愈、专业 |
| home | 理想生活空间 | 25-45岁家居改善人群 | 温馨、生活化、品质感 |
| generic | 好物推荐 | 通用人群 | 亲切、真实、有说服力 |

**创意原则**：
1. 3秒钩子：前3秒必须抓住注意力
2. 痛点-解决方案：明确痛点，展示解决方案
3. 社会证明：融入用户评价/使用场景
4. 明确CTA：结尾有明确的行动召唤

**自动类目检测**：通过关键词匹配自动判断类目。

### 3.4 Storyboard Agent（分镜设计）

**文件**：[agents/storyboard/scripts/storyboard_gen.py](file:///workspace/kickart-clone/agents/storyboard/scripts/storyboard_gen.py)

**镜头类型**：
- `wide`：全景，展示环境
- `medium`：中景，展示人物+产品
- `closeup`：特写，展示细节
- `product`：产品图，纯展示
- `lifestyle`：生活场景

**调性色彩映射**：
- 时尚 → `#2C2C2C, #F5F5F5, #C9A96E, #8B6F47`
- 科技感 → `#0A0E27, #1A1F3A, #00FF88, #FFFFFF`
- 温柔 → `#FFF5F0, #F4C2C2, #E8B4B8, #D4A5A5`
- 温馨 → `#FFF8E7, #D4A574, #A0683E, #6B4423`

**默认负面提示词**：
```
lowres, bad anatomy, bad hands, text, error, missing fingers,
extra digit, fewer digits, cropped, worst quality, low quality,
normal quality, jpeg artifacts, signature, watermark, username, blurry,
deformed, disfigured, mutation, malformed, duplicate
```

### 3.5 Image Gen Agent（图像生成）

**文件**：[/workspace/skills/public/amazon-product-image/scripts/generate.py](file:///workspace/skills/public/amazon-product-image/scripts/generate.py)

**核心能力**：
- txt2img / img2img 两种模式
- ControlNet 姿势控制（OpenPose）
- LoRA 服装专用微调
- 高清修复（enable_hr）
- 强制显示双臂（include_arms）

**关键参数**：
- `--reference-image`：参考图片（img2img）
- `--denoising-strength`：去噪强度（0.0-1.0）
- `--controlnet`：启用 ControlNet
- `--controlnet-model`：ControlNet 模型
- `--include-arms`：强制显示双臂
- `--enable-hr`：启用高清修复

### 3.6 TTS Agent（语音合成）

**文件**：[agents/tts/scripts/tts_gen.py](file:///workspace/kickart-clone/agents/tts/scripts/tts_gen.py)

**音色列表**：

| 名称 | 音色 ID | 特点 |
|------|---------|------|
| xiaoxiao | zh-CN-XiaoxiaoNeural | 女声，温暖亲切（默认）|
| yunxi | zh-CN-YunxiNeural | 男声，年轻活力 |
| yunjian | zh-CN-YunjianNeural | 男声，沉稳专业 |
| xiaoyi | zh-CN-XiaoyiNeural | 女声，活泼可爱 |
| yunyang | zh-CN-YunyangNeural | 男声，新闻播报 |
| xiaohan | zh-CN-XiaohanNeural | 女声，温柔抒情 |

**降级机制**：edge-tts 不可用时自动生成静音音频。

### 3.7 Video Gen Agent（视频合成）

**文件**：[agents/video_gen/scripts/video_compose.py](file:///workspace/kickart-clone/agents/video_gen/scripts/video_compose.py)

**合成流程**：
1. 为每个分镜生成视频片段（Ken Burns 效果）
2. 拼接片段（concat）
3. 添加音轨（TTS 旁白）
4. 烧录字幕（SRT）

**Ken Burns 效果**：
- `in`：缓慢放大（zoompan z=min(zoom+0.0015,1.5)）
- `out`：缓慢缩小
- `pan`：平移

**宽高比支持**：
- `9:16` → 1080x1920（竖屏，默认）
- `16:9` → 1920x1080（横屏）
- `1:1` → 1080x1080（方形）
- `4:3` → 1440x1080
- `3:4` → 1080x1440

---

## 4. 平台层详解

### 4.1 JNPF6.2 适配层

**文件**：[platform/jnpf/adapter.py](file:///workspace/kickart-clone/platform/jnpf/adapter.py)

**平台元信息**：
```python
PLATFORM_META = {
    "platform": "JNPF6.2",
    "version": "6.2.0",
    "spec": "low-code-platform",
    "compatibility": "jnpf6.2+",
}
```

**提供的能力**：

| 能力 | 方法 | 说明 |
|------|------|------|
| 表单定义 | `get_creative_form()` | 创意生成表单（7 字段）|
| 表单定义 | `get_product_form()` | 商品解析表单（3 字段）|
| 数据模型 | `get_data_models()` | 4 个表（products/creatives/storyboards/videos）|
| 流程编排 | `get_workflow_definition()` | 8 节点流程（start→task→decision→end）|
| 页面定义 | `get_pages()` | 4 个页面（dashboard/form/detail/list）|
| API 注册 | `get_api_registry()` | 6 个 API 端点 |
| 应用清单 | `get_app_manifest()` | 一键部署清单 |
| 配置导出 | `export_full_config()` | 完整 JSON 配置 |
| 执行入口 | `execute_creative(form_data)` | JNPF 表单提交入口 |

**数据模型表**：

| 表名 | 说明 | 关联 |
|------|------|------|
| kickart_products | 商品信息 | - |
| kickart_creatives | 创意脚本 | product_id → products.id |
| kickart_storyboards | 分镜列表 | creative_id → creatives.id |
| kickart_videos | 视频产物 | storyboard_id → storyboards.id |

### 4.2 复利系统指令集

**文件**：[platform/compound/instruction_set.py](file:///workspace/kickart-clone/platform/compound/instruction_set.py)

**核心理念**：每次生成的系统/组件都可累积复用，形成资产复利。

**指令模板（8 条）**：

| 指令 | 类型 | 说明 |
|------|------|------|
| `generate.creative` | GENERATE | 生成营销创意脚本 |
| `generate.storyboard` | GENERATE | 生成分镜列表 |
| `generate.images` | GENERATE | 批量生成图片 |
| `generate.video` | GENERATE | 合成营销视频 |
| `generate.tts` | GENERATE | 生成 TTS 旁白 |
| `clone.kickart` | CLONE | 复刻 Kickart 平台 |
| `compose.workflow` | COMPOSE | 组合端到端工作流（5 步链）|
| `integrate.jnpf` | INTEGRATE | 集成 JNPF6.2 |
| `accumulate.asset` | ACCUMULATE | 累积资产到注册表 |

**指令链执行**：
```python
engine = CompoundInstructionEngine(registry_path="./registry")
result = engine.execute_chain("compose.workflow", {
    "input_value": "优雅夏季连衣裙",
    "product_info": {...},
})
# 自动执行：creative → storyboard → images → tts → video
```

**资产累积**：每次指令执行成功后自动累积到注册表，支持复用计数。

### 4.3 多租户支持

**文件**：[platform/tenant/manager.py](file:///workspace/kickart-clone/platform/tenant/manager.py)

**套餐配额**：

| 套餐 | 日视频 | 日图片 | 并发 | 存储 | Agent |
|------|--------|--------|------|------|-------|
| free | 3 | 30 | 1 | 500MB | 3 个（无 image/tts/video）|
| pro | 50 | 500 | 5 | 5GB | 6 个（全部）|
| enterprise | 1000 | 10000 | 20 | 100GB | 6 个（全部）|

**核心功能**：
- 租户 CRUD
- API Key 鉴权（格式：`kk_xxx`）
- 配额检查与用量记录
- Agent 访问控制（按套餐）
- 资源隔离（租户专属工作空间）

### 4.4 监控告警

**文件**：[platform/monitoring/monitor.py](file:///workspace/kickart-clone/platform/monitoring/monitor.py)

**默认告警规则（6 条）**：

| 规则名 | 指标 | 条件 | 阈值 | 级别 |
|--------|------|------|------|------|
| agent_success_rate_low | agent_success_rate | lt | 0.95 | WARNING |
| agent_success_rate_critical | agent_success_rate | lt | 0.80 | CRITICAL |
| e2e_latency_high | e2e_latency | gt | 300 | WARNING |
| e2e_latency_critical | e2e_latency | gt | 600 | CRITICAL |
| api_error_rate_high | api_error_rate | gt | 0.05 | WARNING |
| daily_videos_low | daily_videos | lt | 5 | INFO |

**健康检查项**：
- api_server：API 服务器状态
- sd_webui：Stable Diffusion WebUI 可用性
- ffmpeg：ffmpeg 可用性
- edge_tts：edge-tts 可用性
- storage：存储空间

**告警生命周期**：`firing → acknowledged → resolved`

---

## 5. API 参考

**文件**：[backend/api/api.py](file:///workspace/kickart-clone/backend/api/api.py)

**Base URL**：`http://localhost:8765`

### 5.1 基础端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| GET | `/scenes` | 列出 15 个场景模板 |

### 5.2 图像生成端点（MVP）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/generate` | 异步创建批量生成任务 |
| POST | `/generate/sync` | 同步生成（阻塞）|
| GET | `/tasks/{task_id}` | 查询任务状态 |
| GET | `/tasks` | 列出所有任务 |
| DELETE | `/tasks/{task_id}` | 删除任务 |

**GenerateRequest 参数**：

| 字段 | 类型 | 默认 | 说明 |
|------|------|------|------|
| product_url | string | - | 商品 URL |
| product_image | string | - | 商品图片路径 |
| product_description | string | - | 商品描述 |
| scenes | list | ["studio"] | 场景列表 |
| num_variants | int | 2 | 每场景变体数（1-5）|
| include_arms | bool | true | 强制显示双臂 |
| enable_hr | bool | true | 启用高清修复 |
| sd_url | string | http://127.0.0.1:7860 | SD WebUI 地址 |

### 5.3 Lead Agent 编排端点（V2）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/orchestrate` | 异步编排（后台执行）|
| POST | `/orchestrate/sync` | 同步编排（阻塞）|
| GET | `/orchestrate/{run_id}` | 查询运行状态 |
| GET | `/orchestrate` | 列出所有运行 |

**OrchestrateRequest 参数**：

| 字段 | 类型 | 默认 | 说明 |
|------|------|------|------|
| input_value | string | 必填 | 商品 URL/ID/描述 |
| workflow | string | video | 工作流类型：image/video/storyboard |
| num_scenes | int | 6 | 场景数（3-10）|
| aspect_ratio | string | 9:16 | 宽高比 |
| voice | string | xiaoxiao | TTS 音色 |

**示例**：
```bash
# 异步启动
curl -X POST http://localhost:8765/orchestrate \
  -H "Content-Type: application/json" \
  -d '{"input_value":"https://amazon.com/dp/B0XXX","workflow":"video"}'

# 查询状态
curl http://localhost:8765/orchestrate/run_xxxxx

# 同步执行（阻塞）
curl -X POST http://localhost:8765/orchestrate/sync \
  -H "Content-Type: application/json" \
  -d '{"input_value":"优雅夏季连衣裙","workflow":"video"}'
```

---

## 6. 场景模板库

**目录**：[templates/scenes/](file:///workspace/kickart-clone/templates/scenes/)

共 15 个场景模板：

| 场景 | 适用 | 文件 |
|------|------|------|
| studio | 棚拍 | [studio.json](file:///workspace/kickart-clone/templates/scenes/studio.json) |
| outdoor_urban | 街拍 | [outdoor_urban.json](file:///workspace/kickart-clone/templates/scenes/outdoor_urban.json) |
| outdoor_cafe | 咖啡馆 | [outdoor_cafe.json](file:///workspace/kickart-clone/templates/scenes/outdoor_cafe.json) |
| minimal_abstract | 白底图 | [minimal_abstract.json](file:///workspace/kickart-clone/templates/scenes/minimal_abstract.json) |
| nature_outdoor | 自然户外 | [nature_outdoor.json](file:///workspace/kickart-clone/templates/scenes/nature_outdoor.json) |
| lifestyle_home | 家居 | [lifestyle_home.json](file:///workspace/kickart-clone/templates/scenes/lifestyle_home.json) |
| beach_resort | 海滩度假 | [beach_resort.json](file:///workspace/kickart-clone/templates/scenes/beach_resort.json) |
| office_business | 商务办公 | [office_business.json](file:///workspace/kickart-clone/templates/scenes/office_business.json) |
| gym_fitness | 健身房 | [gym_fitness.json](file:///workspace/kickart-clone/templates/scenes/gym_fitness.json) |
| luxury_interior | 奢华室内 | [luxury_interior.json](file:///workspace/kickart-clone/templates/scenes/luxury_interior.json) |
| autumn_park | 秋日公园 | [autumn_park.json](file:///workspace/kickart-clone/templates/scenes/autumn_park.json) |
| night_city | 夜景城市 | [night_city.json](file:///workspace/kickart-clone/templates/scenes/night_city.json) |
| studio_color | 彩色棚拍 | [studio_color.json](file:///workspace/kickart-clone/templates/scenes/studio_color.json) |
| rooftop | 屋顶 | [rooftop.json](file:///workspace/kickart-clone/templates/scenes/rooftop.json) |
| vintage_retro | 复古怀旧 | [vintage_retro.json](file:///workspace/kickart-clone/templates/scenes/vintage_retro.json) |

---

## 7. 部署指南

### 7.1 环境要求

- Python 3.10+
- ffmpeg 6.0+
- Stable Diffusion WebUI（可选，用于图像生成）
- 网络访问（用于 edge-tts 和商品解析）

### 7.2 安装依赖

```bash
# 基础依赖
pip install fastapi uvicorn pydantic pyyaml requests Pillow --break-system-packages

# TTS 依赖
pip install edge-tts --break-system-packages

# SD WebUI 依赖（可选）
# 参考 https://github.com/AUTOMATIC1111/stable-diffusion-webui
```

### 7.3 启动服务

```bash
# 1. 启动 Stable Diffusion WebUI（可选）
cd /path/to/stable-diffusion-webui
./webui.sh --api --listen

# 2. 启动 Kickart API 服务
cd /workspace/kickart-clone/backend/api
python api.py
# 服务运行在 http://localhost:8765
```

### 7.4 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| SD_WEBUI_URL | http://localhost:7860 | SD WebUI 地址 |
| LEAD_AGENT_OUTPUT_DIR | /mnt/user-data/workspace/lead_agent_runs | Lead Agent 输出目录 |

### 7.5 目录结构

| 路径 | 说明 |
|------|------|
| /mnt/user-data/workspace/ | 默认工作空间 |
| /mnt/user-data/workspace/lead_agent_runs/ | Lead Agent 运行记录 |
| /mnt/user-data/workspace/jnpf/ | JNPF6.2 配置 |
| /mnt/user-data/workspace/compound_registry/ | 复利资产注册表 |
| /mnt/user-data/workspace/tenants/ | 租户数据 |
| /mnt/user-data/workspace/monitoring/ | 监控数据 |

---

## 8. 使用示例

### 8.1 完整视频工作流（API）

```bash
# 1. 启动 API
cd backend/api && python api.py &

# 2. 同步执行完整视频工作流
curl -X POST http://localhost:8765/orchestrate/sync \
  -H "Content-Type: application/json" \
  -d '{
    "input_value": "优雅的夏季碎花连衣裙，轻盈面料，修身剪裁",
    "workflow": "video",
    "num_scenes": 6,
    "aspect_ratio": "9:16",
    "voice": "xiaoxiao"
  }'

# 3. 查询运行状态
curl http://localhost:8765/orchestrate
```

### 8.2 分步执行（CLI）

```bash
# 1. 商品解析
python skills/product-parse/scripts/parse.py \
  --input "https://www.amazon.com/dp/B08XXX" \
  --output product.json

# 2. 创意脚本生成
python agents/creative/scripts/creative_gen.py \
  --product-json product.json \
  --output creative.json

# 3. 分镜生成
python agents/storyboard/scripts/storyboard_gen.py \
  --creative-json creative.json \
  --output storyboard.json

# 4. TTS 旁白
python agents/tts/scripts/tts_gen.py \
  --storyboard-json storyboard.json \
  --voice xiaoxiao \
  --output-dir ./audio

# 5. 视频合成
python agents/video_gen/scripts/video_compose.py \
  --storyboard-json storyboard.json \
  --images-dir ./images \
  --audio ./audio/audio_xxx.aac \
  --output-dir ./videos
```

### 8.3 复利指令集执行

```bash
# 1. 执行单条指令
python platform/compound/instruction_set.py \
  --action execute \
  --instruction generate.creative \
  --params-json params.json

# 2. 执行指令链
python platform/compound/instruction_set.py \
  --action chain \
  --instruction compose.workflow \
  --params-json params.json

# 3. 查看资产
python platform/compound/instruction_set.py --action assets
```

### 8.4 多租户管理

```bash
# 1. 创建租户
python platform/tenant/manager.py \
  --action create --name "我的公司" --plan pro

# 2. 鉴权
python platform/tenant/manager.py \
  --action auth --api-key kk_xxxxx

# 3. 检查配额
python platform/tenant/manager.py \
  --action quota --tenant-id tenant_xxx --resource video
```

### 8.5 JNPF6.2 配置导出

```bash
# 导出完整配置
python platform/jnpf/adapter.py --action export

# 查看应用清单
python platform/jnpf/adapter.py --action manifest

# 查看表单定义
python platform/jnpf/adapter.py --action forms
```

---

## 9. 测试说明

### 9.1 测试概览

| 测试文件 | 阶段 | 测试数 | 说明 |
|----------|------|--------|------|
| test_workflow.py | MVP | 7 | 健康检查/场景/任务 CRUD |
| test_v1_workflow.py | V1 | 3 | 服饰/电子/美妆视频工作流 |
| test_v2_workflow.py | V2 | 6 | 规划/注册表/端到端/降级/必需失败/持久化 |
| test_v3_workflow.py | V3 | 5 | JNPF/复利/多租户/监控/集成 |

### 9.2 运行测试

```bash
# MVP 测试
python tests/e2e/test_workflow.py

# V1 测试（视频成片）
python tests/e2e/test_v1_workflow.py

# V2 测试（Agent 协同）
python tests/e2e/test_v2_workflow.py

# V3 测试（平台化）
python tests/e2e/test_v3_workflow.py
```

### 9.3 测试结果

所有 17 个测试全部通过：
- ✅ MVP：7/7 通过
- ✅ V1：3/3 通过
- ✅ V2：6/6 通过
- ✅ V3：5/5 通过

---

## 10. 运维监控

### 10.1 健康检查

```bash
# API 健康检查
curl http://localhost:8765/health

# 平台健康检查
python platform/monitoring/monitor.py --action health
```

### 10.2 监控仪表盘

```bash
python platform/monitoring/monitor.py --action dashboard
```

输出包含：
- 系统健康状态
- 5 个核心指标（日视频/日素材/成功率/耗时/错误率）
- 活跃告警列表
- 24 小时告警数

### 10.3 告警管理

```bash
# 查看活跃告警
python platform/monitoring/monitor.py --action alerts

# 查看告警历史
python platform/monitoring/monitor.py --action history

# 查看告警规则
python platform/monitoring/monitor.py --action rules

# 记录指标
python platform/monitoring/monitor.py \
  --action record --metric agent_success_rate --value 0.98
```

### 10.4 gstack 进度跟踪

```bash
python backend/orchestrator/gstack_orchestrator.py
```

输出包含：
- 项目总体进度（24/24）
- 各迭代状态
- 度量指标达成情况

---

## 11. gstack 方法论

### 11.1 核心理念

借鉴 [gstack](https://github.com/garrytan/gstack) 方法论：
- **autoplan**：自动规划迭代与任务
- **可衡量产出**：每个任务有明确的成功标准
- **Agentic Workflow**：Agent 自主调度
- **Solo Shipper**：单人全栈交付

### 11.2 autoplan 配置

**文件**：[autoplan.yaml](file:///workspace/kickart-clone/autoplan.yaml)

```yaml
project:
  name: kickart-clone
  goal: 复刻字节跳动 Kickart 一站式营销创作平台
  base: DeerFlow + Stable Diffusion + JNPF6.2 + 复利系统指令集

iterations:
  - id: MVP-1    # 图像生成闭环
  - id: V1-2     # 视频成片
  - id: V2-3     # Agent 协同
  - id: V3-4     # 平台化

metrics:
  - daily_videos: 10
  - daily_assets: 100
  - agent_success_rate: 0.95
  - e2e_latency: 300s
  - cost_per_video: 1.0 CNY
```

### 11.3 度量体系

| 指标 | 目标 | 单位 | 说明 |
|------|------|------|------|
| daily_videos | 10 | count | 日成片数 |
| daily_assets | 100 | count | 日素材数 |
| agent_success_rate | 0.95 | percentage | Agent 成功率 |
| e2e_latency | 300 | seconds | 端到端耗时 |
| cost_per_video | 1.0 | CNY | 单视频成本 |

### 11.4 风险跟踪

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| SD WebUI 资源不足 | medium | high | 限制并发，云端 API 兜底 |
| 视频合成质量不达标 | high | high | 先做图片序列，逐步提升 |
| JNPF6.2 集成困难 | medium | medium | 提前对接，预留适配层 |

---

## 12. 故障排查

### 12.1 常见问题

#### Q1: Stable Diffusion WebUI 连接失败

**现象**：图像生成返回失败

**排查**：
```bash
# 检查 SD WebUI 是否运行
curl http://localhost:7860/sdapi/v1/options

# 检查环境变量
echo $SD_WEBUI_URL
```

**解决**：启动 SD WebUI 时添加 `--api --listen` 参数。

#### Q2: edge-tts 连接超时

**现象**：TTS 生成失败，日志显示 `Connection timeout`

**排查**：
```bash
# 检查 edge-tts 是否可用
edge-tts --version
```

**解决**：系统已内置降级机制，edge-tts 不可用时自动使用静音音频。

#### Q3: ffmpeg 不可用

**现象**：视频合成失败

**排查**：
```bash
ffmpeg -version
```

**解决**：`apt install ffmpeg` 或 `brew install ffmpeg`。

#### Q4: Lead Agent 工作流失败

**现象**：编排返回 `success: false`

**排查**：
```bash
# 查看运行详情
curl http://localhost:8765/orchestrate/{run_id}

# 查看降级日志
python -c "
import json
with open('runs/{run_id}.json') as f:
    data = json.load(f)
    print(json.dumps(data.get('degradation_log', []), indent=2))
"
```

**解决**：
- 必需 Agent（product_parser/creative/storyboard/video_gen）失败会终止工作流
- 可选 Agent（image_gen/tts）失败会自动降级

#### Q5: 多租户配额超限

**现象**：API 返回 403 或配额错误

**排查**：
```bash
python platform/tenant/manager.py \
  --action quota --tenant-id tenant_xxx --resource video
```

**解决**：升级套餐或等待次日重置。

### 12.2 日志位置

| 组件 | 日志位置 |
|------|----------|
| API 服务 | 控制台输出 |
| Lead Agent | /mnt/user-data/workspace/lead_agent_runs/{run_id}.json |
| 监控告警 | /mnt/user-data/workspace/monitoring/monitoring_state.json |
| 租户数据 | /mnt/user-data/workspace/tenants/tenants.json |
| 复利资产 | /mnt/user-data/workspace/compound_registry/assets.json |

### 12.3 性能优化建议

1. **图像生成并发**：限制 2-4 路并发，避免 SD WebUI 资源不足
2. **视频合成**：串行执行，避免 ffmpeg 资源竞争
3. **TTS 生成**：可并行，但注意 edge-tts 连接数限制
4. **存储清理**：定期清理 work 目录和过期产物

---

## 附录

### A. 文件索引

| 文件 | 说明 |
|------|------|
| [README.md](file:///workspace/kickart-clone/README.md) | 项目入口 |
| [PROJECT_HANDBOOK.md](file:///workspace/kickart-clone/PROJECT_HANDBOOK.md) | 完整项目手册（本文件）|
| [PLAN.md](file:///workspace/kickart-clone/PLAN.md) | 落地方案 |
| [autoplan.yaml](file:///workspace/kickart-clone/autoplan.yaml) | gstack 自动规划 |

### B. Agent 文件索引

| Agent | SOUL.md | 脚本 |
|-------|---------|------|
| Lead Agent | [SOUL.md](file:///workspace/kickart-clone/agents/lead_agent/SOUL.md) | [orchestrator.py](file:///workspace/kickart-clone/agents/lead_agent/scripts/orchestrator.py) |
| Product Parser | [SOUL.md](file:///workspace/kickart-clone/agents/product_parser/SOUL.md) | [parse.py](file:///workspace/kickart-clone/skills/product-parse/scripts/parse.py) |
| Creative | [SOUL.md](file:///workspace/kickart-clone/agents/creative/SOUL.md) | [creative_gen.py](file:///workspace/kickart-clone/agents/creative/scripts/creative_gen.py) |
| Storyboard | [SOUL.md](file:///workspace/kickart-clone/agents/storyboard/SOUL.md) | [storyboard_gen.py](file:///workspace/kickart-clone/agents/storyboard/scripts/storyboard_gen.py) |
| Image Gen | [SOUL.md](file:///workspace/kickart-clone/agents/image_gen/SOUL.md) | [generate.py](file:///workspace/skills/public/amazon-product-image/scripts/generate.py) |
| TTS | [SOUL.md](file:///workspace/kickart-clone/agents/tts/SOUL.md) | [tts_gen.py](file:///workspace/kickart-clone/agents/tts/scripts/tts_gen.py) |
| Video Gen | [SOUL.md](file:///workspace/kickart-clone/agents/video_gen/SOUL.md) | [video_compose.py](file:///workspace/kickart-clone/agents/video_gen/scripts/video_compose.py) |

### C. 平台层文件索引

| 模块 | 文件 |
|------|------|
| JNPF6.2 适配 | [adapter.py](file:///workspace/kickart-clone/platform/jnpf/adapter.py) |
| 复利指令集 | [instruction_set.py](file:///workspace/kickart-clone/platform/compound/instruction_set.py) |
| 多租户 | [manager.py](file:///workspace/kickart-clone/platform/tenant/manager.py) |
| 监控告警 | [monitor.py](file:///workspace/kickart-clone/platform/monitoring/monitor.py) |

### D. 测试文件索引

| 测试 | 文件 |
|------|------|
| MVP 测试 | [test_workflow.py](file:///workspace/kickart-clone/tests/e2e/test_workflow.py) |
| V1 测试 | [test_v1_workflow.py](file:///workspace/kickart-clone/tests/e2e/test_v1_workflow.py) |
| V2 测试 | [test_v2_workflow.py](file:///workspace/kickart-clone/tests/e2e/test_v2_workflow.py) |
| V3 测试 | [test_v3_workflow.py](file:///workspace/kickart-clone/tests/e2e/test_v3_workflow.py) |

---

**文档版本**：1.0.0  
**最后更新**：2026-06-18  
**项目状态**：全部 4 迭代完成，24/24 任务通过，17 个测试通过
