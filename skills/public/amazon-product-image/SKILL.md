---
name: amazon-product-image
description: Use this skill when generating e-commerce product images for Amazon or similar platforms, including fashion clothing, apparel models, multi-scene product photography, and batch image generation workflows.
---

# Amazon Product Image Generation Skill

## Overview

This skill generates professional e-commerce product images for Amazon listings using Stable Diffusion WebUI API. It supports batch generation across multiple scenes with variant options.

## Prerequisites

1. **Stable Diffusion WebUI** must be running with API enabled
   ```bash
   # 启动 SD WebUI 并启用 API
   ./webui-user.bat  # Windows
   ./webui-user.sh   # Linux
   # 确保添加 --api 参数或勾选 "Enable API" 选项
   ```

2. **Required Python packages** (usually pre-installed in DeerFlow sandbox):
   ```bash
   pip install requests Pillow
   ```

## Supported Scenes

| Scene ID | Description | Best For |
|----------|-------------|----------|
| `studio` | Professional photography studio | Standard product shots |
| `outdoor_urban` | Urban street scene | Casual fashion |
| `outdoor_cafe` | Stylish cafe interior | Lifestyle content |
| `minimal_abstract` | Clean gradient background | Amazon white background |
| `nature_outdoor` | Garden/nature backdrop | Vacation style |
| `lifestyle_home` | Cozy home interior | Everyday clothing |

## Workflow

### Step 1: Understand Requirements

When generating product images, identify:
- Product type: Clothing category (dress, shirt, pants, etc.)
- Style direction: Casual, formal, sporty, etc.
- Required scenes: Number of scenes needed
- Variants per scene: Different poses/angles

### Step 2: Prepare Product Information

Create a product info JSON file in `/mnt/user-data/workspace/`:

```json
{
  "product_id": "SKU-001",
  "product_description": "floral print summer dress, v-neck, midi length, lightweight chiffon fabric",
  "required_scenes": ["studio", "outdoor_urban", "minimal_abstract"],
  "num_variants": 2,
  "model_settings": {
    "ethnicity": "Asian female",
    "model_type": "slender fit model",
    "pose_style": "editorial fashion"
  }
}
```

### Step 3: Execute Batch Generation

Call the generation script:

```bash
python /mnt/skills/public/amazon-product-image/scripts/generate.py \
  --product-description "floral print summer dress, v-neck, midi length" \
  --product-id "SKU-001" \
  --scenes studio outdoor_urban minimal_abstract \
  --num-variants 2 \
  --output-dir /mnt/user-data/outputs \
  --enable-hr
```

### Step 4: Review and Post-Process

After generation:
1. Images are saved to `/mnt/user-data/outputs/`
2. Use `present_files` tool to display to user
3. Recommend additional processing (background removal, resize)

## Command Options

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `--product-description` | Yes | - | Detailed product description |
| `--product-id` | Yes | - | Product ID for file naming |
| `--scenes` | No | studio | Space-separated scene list |
| `--num-variants` | No | 2 | Variants per scene |
| `--sd-url` | No | http://127.0.0.1:7860 | SD WebUI API URL |
| `--output-dir` | No | /mnt/user-data/outputs | Output directory |
| `--num-parallel` | No | 2 | Parallel generation tasks |
| `--width` | No | 1024 | Image width |
| `--height` | No | 1280 | Image height |
| `--steps` | No | 30 | Sampling steps |
| `--cfg-scale` | No | 7.0 | CFG scale |
| `--sampler` | No | DPM++ 2M Karras | Sampler name |
| `--enable-hr` | No | False | Enable high-res fix |
| `--lora-name` | No | - | LoRA model name |
| `--lora-weight` | No | 0.8 | LoRA weight (0-1) |
| `--custom-prompt` | No | - | Override prompt |
| `--custom-negative` | No | - | Override negative prompt |
| `--reference-image` | No | - | Reference image path (img2img mode) |
| `--denoising-strength` | No | 0.75 | Denoising strength for img2img (0-1) |
| `--controlnet` | No | False | Enable ControlNet for pose preservation |
| `--controlnet-model` | No | openpose | ControlNet model type |
| `--include-arms` | No | False | Force both arms visible in output |

## Scene Template Customization

Templates are located at: `/mnt/skills/public/amazon-product-image/templates/`

### Example: Custom Scene Template

Create `my_scene.json`:

```json
{
  "scene_type": "custom_beach",
  "scene_name": "Beach Scene",
  "default_prompt_template": "Fashion model wearing {product_description}, tropical beach background, crystal clear ocean, palm trees, sunny day, vacation resort, beach fashion photography, natural lighting, ultra sharp, 8k",
  "default_negative_prompt": "blurry, low quality, deformed, watermark, text, logo, dirty, cluttered",
  "recommended_settings": {
    "steps": 30,
    "cfg_scale": 7,
    "sampler": "DPM++ 2M Karras",
    "width": 1024,
    "height": 1280
  }
}
```

## Recommended Settings for Amazon

### White Background (Amazon Standard)
```bash
python /mnt/skills/public/amazon-product-image/scripts/generate.py \
  --product-description "YOUR_PRODUCT" \
  --product-id "SKU" \
  --scenes minimal_abstract \
  --num-variants 3 \
  --enable-hr
```

### Lifestyle Images
```bash
python /mnt/skills/public/amazon-product-image/scripts/generate.py \
  --product-description "YOUR_PRODUCT" \
  --product-id "SKU" \
  --scenes studio outdoor_urban outdoor_cafe \
  --num-variants 2 \
  --enable-hr
```

### Full Scene Set (7 scenes)
```bash
python /mnt/skills/public/amazon-product-image/scripts/generate.py \
  --product-description "YOUR_PRODUCT" \
  --product-id "SKU" \
  --scenes studio outdoor_urban outdoor_cafe minimal_abstract nature_outdoor lifestyle_home \
  --num-variants 2 \
  --num-parallel 3 \
  --enable-hr
```

## Integration with DeerFlow Agents

The agent can invoke this skill for multi-turn workflows:

1. User requests: "Generate images for my new dress collection"
2. Agent creates product info JSON with scene specifications
3. Agent executes batch generation script
4. Agent presents generated images to user
5. Agent offers refinements based on feedback

## Tips

- Always use English prompts for better SD compatibility
- Include fabric/material details in product description
- Use `--enable-hr` flag for Amazon's 1500px+ requirement
- Batch generation can take 5-15 minutes depending on settings
- Monitor SD WebUI console for progress updates

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "SD WebUI not running" | Start SD WebUI with API enabled |
| Slow generation | Reduce `--steps` or disable `--enable-hr` |
| Poor quality | Increase `--steps` to 40-50, use LoRA models |
| Inconsistent model | Set fixed `--seed` value for reproducibility |
| Connection timeout | Increase SD WebUI timeout or reduce batch size |

## LoRA Recommendations

Add `--lora-name` for better results:

| LoRA Name | Effect |
|-----------|--------|
| epiCRealism | Realistic skin tones |
| more_details | Enhanced fabric details |
| glamour_v2 | Fashion magazine quality |
| fashion_girl | Clothing-focused enhancements |
