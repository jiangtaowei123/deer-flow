# Kickart Clone - 一站式营销创作平台

> 基于 gstack 方法论管理，复刻字节跳动 Kickart 平台
> 底层：DeerFlow + Stable Diffusion + JNPF6.2 + 复利系统指令集

## 🎯 项目目标

复刻 [Kickart](https://bytedance.larkoffice.com/docx/SKCGdayW8or20dx2vm5cixQmnBg) 一站式营销创作平台，实现：
- **对话式一键成片**：商品URL → 创意 → 故事板 → 完整视频
- **Agent 自主规划**：6 个专业 Agent 协同，自主调度
- **多场景素材生成**：15+ 场景模板，批量生成
- **平台化运营**：JNPF6.2 适配 + 多租户 + 监控告警

## 📊 项目状态

**全部 4 个迭代完成，24/24 任务通过，17 个端到端测试通过**

| 迭代 | 名称 | 任务 | 状态 |
|------|------|------|------|
| MVP-1 | 图像生成闭环 | 6/6 | ✅ 完成 |
| V1-2 | 视频成片 | 6/6 | ✅ 完成 |
| V2-3 | Agent 协同 | 6/6 | ✅ 完成 |
| V3-4 | 平台化 | 6/6 | ✅ 完成 |

## 🏗️ 架构总览

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

## 📁 项目结构

```
kickart-clone/
├── agents/                         # 6 个专业 Agent
│   ├── lead_agent/                 # Lead Agent 编排器（V2）
│   │   ├── scripts/orchestrator.py # 自主调度 + 失败降级
│   │   ├── SOUL.md                 # 身份定义
│   │   └── config.yaml             # 配置
│   ├── product_parser/             # 商品解析（MVP）
│   ├── creative/                   # 创意脚本（V1）
│   │   └── scripts/creative_gen.py # 5 类目模板
│   ├── storyboard/                 # 分镜设计（V1）
│   │   └── scripts/storyboard_gen.py
│   ├── image_gen/                  # 图像生成（MVP）
│   ├── tts/                        # TTS 旁白（V1）
│   │   └── scripts/tts_gen.py      # edge-tts 6 音色
│   └── video_gen/                  # 视频合成（V1）
│       └── scripts/video_compose.py # Ken Burns + 字幕
├── platform/                       # 平台层（V3）
│   ├── jnpf/adapter.py             # JNPF6.2 适配
│   ├── compound/instruction_set.py # 复利系统指令集
│   ├── tenant/manager.py           # 多租户管理
│   └── monitoring/monitor.py       # 监控告警
├── backend/
│   ├── api/api.py                  # FastAPI 服务（10 端点）
│   └── orchestrator/gstack_orchestrator.py
├── skills/product-parse/           # 商品解析 Skill
├── templates/scenes/               # 15 个场景模板
├── tests/e2e/                      # 端到端测试
│   ├── test_workflow.py            # MVP 测试
│   ├── test_v1_workflow.py         # V1 测试
│   ├── test_v2_workflow.py         # V2 测试
│   └── test_v3_workflow.py         # V3 测试
├── autoplan.yaml                   # gstack 自动规划
├── PLAN.md                         # 落地方案
├── PROJECT_HANDBOOK.md             # 完整项目手册
└── README.md                       # 项目入口
```

## 🚀 快速开始

### 1. 查看 gstack 进度
```bash
python backend/orchestrator/gstack_orchestrator.py
```

### 2. 启动 API 服务
```bash
cd backend/api && python api.py
# 服务运行在 http://localhost:8765
```

### 3. 一键编排（Lead Agent）
```bash
# 同步执行完整视频工作流
curl -X POST http://localhost:8765/orchestrate/sync \
  -H "Content-Type: application/json" \
  -d '{"input_value":"优雅夏季连衣裙","workflow":"video"}'
```

### 4. 单独使用各 Agent
```bash
# 创意脚本生成
python agents/creative/scripts/creative_gen.py \
  --product-json product.json --output creative.json

# 分镜生成
python agents/storyboard/scripts/storyboard_gen.py \
  --creative-json creative.json --output storyboard.json

# TTS 旁白
python agents/tts/scripts/tts_gen.py \
  --storyboard-json storyboard.json --voice xiaoxiao

# 视频合成
python agents/video_gen/scripts/video_compose.py \
  --storyboard-json storyboard.json \
  --images-dir ./images \
  --audio ./audio.aac
```

### 5. 平台管理
```bash
# 导出 JNPF6.2 配置
python platform/jnpf/adapter.py --action export

# 创建租户
python platform/tenant/manager.py --action create --name "我的公司" --plan pro

# 查看监控仪表盘
python platform/monitoring/monitor.py --action dashboard
```

## 📚 文档

- [完整项目手册](PROJECT_HANDBOOK.md) - 架构、API、部署、运维详解
- [落地方案](PLAN.md) - gstack 方法论与 Kickart 对齐
- [自动规划](autoplan.yaml) - 迭代任务与度量

## 🔗 依赖

- [DeerFlow](https://github.com/bytedance/deer-flow) - Agent 编排参考
- [Stable Diffusion WebUI](https://github.com/AUTOMATIC1111/stable-diffusion-webui) - 图像生成
- [JNPF6.2](https://www.jnpfsoft.com/) - 低代码平台
- [gstack](https://github.com/garrytan/gstack) - 方法论参考
- [edge-tts](https://github.com/rany2/edge-tts) - TTS 语音合成
- [ffmpeg](https://ffmpeg.org/) - 视频合成
