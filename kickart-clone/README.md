# Kickart Clone - 一站式营销创作平台

> 基于 gstack 方法论管理，复刻字节跳动 Kickart 平台
> 底层：DeerFlow + Stable Diffusion + JNPF6.2 + 复利系统指令集

## 🎯 项目目标

复刻 [Kickart](https://bytedance.larkoffice.com/docx/SKCGdayW8or20dx2vm5cixQmnBg) 一站式营销创作平台，实现：
- **对话式一键成片**：商品URL → 创意 → 故事板 → 完整视频
- **Agent 自主规划**：多 Agent 协同，自主调度
- **多场景素材生成**：15+ 场景模板，批量生成

## 🏗️ 架构

```
用户交互 → gstack 编排 → DeerFlow Agent → SD/VLM/Video → JNPF6.2
```

详细方案见 [PLAN.md](PLAN.md)

## 📁 项目结构

```
kickart-clone/
├── PLAN.md                    # 落地方案
├── autoplan.yaml              # gstack 自动规划配置
├── agents/                    # 8 个专业 Agent
│   ├── lead_agent/            # 总指挥
│   ├── product_parser/        # 商品解析
│   ├── creative/              # 创意生成
│   ├── storyboard/            # 分镜设计
│   ├── image_gen/             # 图像生成
│   ├── video_gen/             # 视频合成
│   ├── template/              # 模板渲染
│   └── publish/               # 多平台发布
├── skills/                    # DeerFlow Skills
│   ├── product-parse/         # 商品解析
│   └── ...
├── templates/scenes/          # 15+ 场景模板
└── backend/orchestrator/      # gstack 编排器
```

## 🚀 快速开始

### 1. 查看 gstack 进度
```bash
python backend/orchestrator/gstack_orchestrator.py
```

### 2. 解析商品
```bash
python skills/product-parse/scripts/parse.py \
  --input "https://www.amazon.com/dp/B08XXX" \
  --output /mnt/user-data/workspace/product-info.json
```

### 3. 批量生成图片
```bash
python /workspace/skills/public/amazon-product-image/scripts/generate.py \
  --product-description "YOUR_PRODUCT" \
  --product-id "SKU-001" \
  --scenes studio outdoor_urban beach_resort gym_fitness \
  --num-variants 2 \
  --include-arms \
  --enable-hr
```

## 📊 场景模板库（15+）

| 场景 | 适用 | 文件 |
|------|------|------|
| studio | 棚拍 | [studio.json](templates/scenes/studio.json) |
| outdoor_urban | 街拍 | [outdoor_urban.json](templates/scenes/outdoor_urban.json) |
| outdoor_cafe | 咖啡馆 | [outdoor_cafe.json](templates/scenes/outdoor_cafe.json) |
| minimal_abstract | 白底图 | [minimal_abstract.json](templates/scenes/minimal_abstract.json) |
| nature_outdoor | 自然户外 | [nature_outdoor.json](templates/scenes/nature_outdoor.json) |
| lifestyle_home | 家居 | [lifestyle_home.json](templates/scenes/lifestyle_home.json) |
| beach_resort | 海滩度假 | [beach_resort.json](templates/scenes/beach_resort.json) |
| office_business | 商务办公 | [office_business.json](templates/scenes/office_business.json) |
| gym_fitness | 健身房 | [gym_fitness.json](templates/scenes/gym_fitness.json) |
| luxury_interior | 奢华室内 | [luxury_interior.json](templates/scenes/luxury_interior.json) |
| autumn_park | 秋日公园 | [autumn_park.json](templates/scenes/autumn_park.json) |
| night_city | 夜景城市 | [night_city.json](templates/scenes/night_city.json) |
| studio_color | 彩色棚拍 | [studio_color.json](templates/scenes/studio_color.json) |
| rooftop | 屋顶 | [rooftop.json](templates/scenes/rooftop.json) |
| vintage_retro | 复古怀旧 | [vintage_retro.json](templates/scenes/vintage_retro.json) |

## 📈 迭代路线

| 阶段 | 周期 | 目标 | 状态 |
|------|------|------|------|
| MVP | 第1周 | 图像生成闭环 | 🔄 进行中 |
| V1 | 第2-3周 | 视频成片 | ⏳ 计划 |
| V2 | 第4-5周 | Agent 协同 | ⏳ 计划 |
| V3 | 第6-7周 | 平台化 | ⏳ 计划 |

## 🔗 依赖

- [DeerFlow](https://github.com/bytedance/deer-flow) - Agent 编排
- [Stable Diffusion WebUI](https://github.com/AUTOMATIC1111/stable-diffusion-webui) - 图像生成
- [JNPF6.2](https://www.jnpfsoft.com/) - 低代码平台
- [gstack](https://github.com/garrytan/gstack) - 方法论参考
