# Kickart 复刻落地方案 - 基于 gstack 管理

> **目标**：使用 gstack 方法论管理项目推进，复刻字节跳动 Kickart 一站式营销创作平台
> **基础**：DeerFlow + Stable Diffusion + JNPF6.2 低代码平台 + 复利系统指令集
> **日期**：2026-05-12

---

## 一、项目背景与对齐分析

### 1.1 gstack 核心理念

gstack 是 Y Combinator 总裁 Garry Tan 的个人 AI 开发栈，核心理念：

| 理念 | 说明 | 在本项目中的应用 |
|------|------|------------------|
| **AI 优先** | AI 写大部分代码，人类做决策 | 用 DeerFlow Agent 驱动开发 |
| **Solo Shipper** | 一人抵一个团队 | 单人推进 Kickart 复刻 |
| **Agentic Workflow** | Agent 自主规划+执行 | 复用 Kickart 的 Agent 架构 |
| **autoplan** | 自动规划迭代 | 自动生成开发任务与素材 |
| **可衡量产出** | 量化产出而非工时 | 按"成片数/素材数"度量 |

### 1.2 Kickart 目标系统拆解

来源：[飞书文档](https://bytedance.larkoffice.com/docx/SKCGdayW8or20dx2vm5cixQmnBg)

**产品定位**：一站式营销创作平台，Agent 自主规划素材生成，服务营销、电商场景。

**核心能力矩阵**：

| 模块 | Kickart 描述 | 复刻方案 |
|------|--------------|----------|
| 对话式一键成片 | 商品URL/ID → 创意 → 故事板 → 完整视频 | DeerFlow Agent + SD + 视频合成 |
| Agent 自主规划 | 结合场景、热点、输入信息调度 | Lead Agent + Subagents |
| VLM 创作模型 | 自研创作 VLM | 复用 GPT-4V / Gemini / SDXL |
| 营销素材生成 | 一键生成营销、电商素材 | 已实现的 amazon-product-image skill |
| 电商促销场景 | 覆盖电商促销等多种场景 | 多场景模板库 |
| UGC 互动玩法 | 用户互动、电商促销 | 互动模板 + 评论驱动生成 |

### 1.3 差距分析（Gap Analysis）

| 能力项 | 当前状态 | 目标状态 | 差距 |
|--------|----------|----------|------|
| Agent 编排 | ✅ DeerFlow 已有 | 多 Agent 协同创作 | 需新增创作 Agent |
| 图像生成 | ✅ SD Skill 已建 | 多场景批量生成 | 已具备 |
| 视频生成 | ⚠️ 仅有 skill 雏形 | 一键成片 | 需集成视频合成 |
| 商品理解 | ❌ 无 | URL→素材解析 | 需新增解析器 |
| 故事板生成 | ❌ 无 | 创意→分镜 | 需新增 Storyboard Agent |
| 模板库 | ⚠️ 6 个场景 | 营销/电商全套 | 需扩充 |
| 低代码后台 | ❌ 无 | JNPF6.2 集成 | 需对接 |

---

## 二、整体架构设计

### 2.1 系统架构图

```
┌─────────────────────────────────────────────────────────────┐
│                    用户交互层 (Frontend)                      │
│   对话式 UI  │  商品URL输入  │  素材上传  │  模板选择         │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                  gstack 管理层 (Orchestrator)                │
│   autoplan  │  任务调度  │  产出度量  │  迭代反馈            │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                DeerFlow Agent 编排层                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐    │
│  │ Lead     │→ │ Product  │→ │ Creative │→ │ Storyboard│   │
│  │ Agent    │  │ Parser   │  │ Agent    │  │ Agent    │    │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘    │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐    │
│  │ Image    │→ │ Video    │→ │ Template │→ │ Publish  │   │
│  │ Agent    │  │ Agent    │  │ Agent    │  │ Agent    │    │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘    │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                    模型与工具层                              │
│  Stable Diffusion  │  VLM (GPT-4V/Gemini)  │  TTS  │  Video │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│              JNPF6.2 低代码平台 + 复利系统指令集              │
│     数据持久化  │  权限管理  │  工作流引擎  │  API 网关        │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 核心数据流

```
[商品URL/素材] → [Product Parser] → [商品理解]
                                          ↓
[用户意图] → [Lead Agent] → [Creative Agent] → [创意脚本]
                                          ↓
                                    [Storyboard Agent]
                                          ↓
                                    [分镜列表]
                                          ↓
                              ┌───────────┴───────────┐
                              ↓                       ↓
                        [Image Agent]           [Video Agent]
                              ↓                       ↓
                        [SD 生成图片]            [视频合成]
                              ↓                       ↓
                              └───────────┬───────────┘
                                          ↓
                                    [Template Agent]
                                          ↓
                                    [最终成品]
                                          ↓
                                    [Publish Agent]
                                          ↓
                                    [JNPF 存储/发布]
```

---

## 三、gstack 项目管理方法论

### 3.1 autoplan 自动规划

借鉴 gstack 的 autoplan 机制，建立自动迭代规划：

```yaml
# autoplan-config.yaml
project: kickart-clone
goal: 复刻 Kickart 一站式营销创作平台
iterations:
  - name: MVP-图像生成
    duration: 1周
    deliverables:
      - 多场景批量图像生成
      - 商品素材解析
  - name: V1-视频成片
    duration: 2周
    deliverables:
      - 故事板生成
      - 视频合成
  - name: V2-Agent协同
    duration: 2周
    deliverables:
      - Lead Agent 编排
      - 多 Agent 协同
  - name: V3-平台化
    duration: 2周
    deliverables:
      - JNPF6.2 集成
      - 模板库扩充
metrics:
  - 成片数/天
  - 素材生成数/天
  - Agent 调用成功率
  - 用户满意度
```

### 3.2 度量体系

| 指标 | 目标值 | 度量方式 |
|------|--------|----------|
| 日成片数 | ≥10 | Publish Agent 统计 |
| 日素材数 | ≥100 | Image Agent 统计 |
| Agent 成功率 | ≥95% | 日志分析 |
| 端到端耗时 | ≤5分钟 | 时间戳差值 |
| 模型调用成本 | ≤¥1/成片 | API 计费统计 |

---

## 四、技术选型与集成方案

### 4.1 技术栈对齐

| 层级 | Kickart 原方案 | 复刻方案 | 说明 |
|------|----------------|----------|------|
| Agent 编排 | 自研 Agent 架构 | DeerFlow + LangGraph | 复用已有 |
| VLM 模型 | 自研创作 VLM | GPT-4V / Gemini 2.5 | 云端 API |
| 图像生成 | 自研 | Stable Diffusion XL | 本地部署 |
| 视频生成 | 自研 | FFmpeg + 图片序列 | 开源工具 |
| 低代码 | - | JNPF6.2 | 用户规则要求 |
| 指令集 | - | 复利系统指令集 | 用户规则要求 |
| 后端 | - | FastAPI (DeerFlow) | 复用已有 |
| 前端 | - | Next.js (DeerFlow) | 复用已有 |

### 4.2 DeerFlow 集成点

复用 DeerFlow 现有能力：

| DeerFlow 能力 | 在 Kickart 中的角色 |
|---------------|---------------------|
| Lead Agent | 创作总指挥 |
| Subagents | 各专业 Agent（解析/创意/分镜/生成） |
| Skills | 图像生成、视频生成、模板等 |
| Sandbox | 代码执行与文件处理 |
| Memory | 用户偏好与历史创意 |
| Channels | 多平台发布（飞书/微信/电商） |

---

## 五、迭代路线图

### Phase 1: MVP - 图像生成闭环（第1周）

**目标**：完成商品→多场景图片生成的端到端流程

**任务清单**：
- [ ] T1.1 创建 kickart-clone 项目骨架
- [ ] T1.2 实现 Product Parser Agent（URL/图片解析）
- [ ] T1.3 扩充场景模板库至 15 个
- [ ] T1.4 完善 amazon-product-image skill
- [ ] T1.5 实现批量生成 API
- [ ] T1.6 端到端测试

**交付物**：
- 输入商品 URL → 输出 10 张多场景图片

### Phase 2: V1 - 视频成片（第2-3周）

**目标**：实现对话式一键成片

**任务清单**：
- [ ] T2.1 实现 Creative Agent（创意脚本生成）
- [ ] T2.2 实现 Storyboard Agent（分镜生成）
- [ ] T2.3 实现 Video Agent（视频合成）
- [ ] T2.4 集成 TTS 旁白
- [ ] T2.5 实现视频模板库
- [ ] T2.6 端到端测试

**交付物**：
- 输入商品 URL → 输出 30s 营销视频

### Phase 3: V2 - Agent 协同（第4-5周）

**目标**：多 Agent 自主协同

**任务清单**：
- [ ] T3.1 Lead Agent 编排逻辑
- [ ] T3.2 Agent 间通信协议
- [ ] T3.3 失败降级与重试
- [ ] T3.4 并发控制
- [ ] T3.5 端到端测试

**交付物**：
- Lead Agent 自主调度全流程

### Phase 4: V3 - 平台化（第6-7周）

**目标**：JNPF6.2 集成，平台化运营

**任务清单**：
- [ ] T4.1 JNPF6.2 数据模型设计
- [ ] T4.2 工作流引擎对接
- [ ] T4.3 权限与多租户
- [ ] T4.4 复利系统指令集集成
- [ ] T4.5 监控与告警
- [ ] T4.6 上线发布

**交付物**：
- 可运营的营销创作平台

---

## 六、目录结构设计

```
/workspace/kickart-clone/
├── README.md                          # 项目说明
├── PLAN.md                            # 本落地方案
├── autoplan.yaml                      # gstack 自动规划配置
├── config.yaml                        # DeerFlow 配置
│
├── agents/                            # Agent 定义
│   ├── lead_agent/                    # 总指挥 Agent
│   │   ├── SOUL.md
│   │   └── config.yaml
│   ├── product_parser/                # 商品解析 Agent
│   ├── creative/                      # 创意 Agent
│   ├── storyboard/                    # 分镜 Agent
│   ├── image_gen/                     # 图像生成 Agent
│   ├── video_gen/                     # 视频生成 Agent
│   ├── template/                      # 模板 Agent
│   └── publish/                       # 发布 Agent
│
├── skills/                            # DeerFlow Skills
│   ├── product-parse/                 # 商品解析
│   ├── creative-script/               # 创意脚本
│   ├── storyboard-gen/                # 分镜生成
│   ├── image-batch-gen/               # 批量图像生成（已实现）
│   ├── video-compose/                 # 视频合成
│   ├── template-render/               # 模板渲染
│   └── multi-publish/                 # 多平台发布
│
├── templates/                         # 模板库
│   ├── scenes/                        # 场景模板（15+）
│   ├── video/                         # 视频模板
│   ├── marketing/                     # 营销模板
│   └── ecommerce/                     # 电商模板
│
├── backend/                           # 后端服务
│   ├── api/                           # API 接口
│   ├── orchestrator/                  # gstack 编排器
│   ├── metrics/                       # 度量收集
│   └── jnpf-bridge/                   # JNPF6.2 桥接
│
├── frontend/                          # 前端 UI
│   ├── chat/                          # 对话式界面
│   ├── workspace/                     # 工作台
│   └── templates/                     # 模板选择
│
└── tests/                             # 测试
    ├── e2e/                           # 端到端测试
    └── unit/                          # 单元测试
```

---

## 七、风险与应对

| 风险 | 概率 | 影响 | 应对措施 |
|------|------|------|----------|
| SD WebUI 资源不足 | 中 | 高 | 限制并发，使用云端 API 兜底 |
| 视频合成质量不达标 | 高 | 高 | 先做图片序列，逐步提升 |
| Agent 协同复杂度高 | 高 | 中 | 分阶段实现，先串行后并行 |
| JNPF6.2 集成困难 | 中 | 中 | 提前对接，预留适配层 |
| 模型调用成本高 | 中 | 中 | 优先本地模型，云端按需 |

---

## 八、下一步行动

立即开始 Phase 1 MVP：

1. 创建项目骨架
2. 实现 Product Parser Agent
3. 扩充场景模板库
4. 端到端验证图像生成闭环

**预期产出**：1周内完成商品 URL → 10 张多场景图片的端到端流程。
