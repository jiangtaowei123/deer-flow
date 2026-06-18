---
name: product-parse
description: Use this skill when parsing product information from URLs, IDs, or uploaded images. Supports major e-commerce platforms (Amazon, Shopify, Taobao, JD) and extracts structured product data for marketing content generation.
---

# Product Parse Skill

## Overview
解析商品信息，支持 URL 抓取、图片识别、结构化输出。为创意生成提供标准化输入。

## Supported Platforms
- Amazon (amazon.com, amazon.cn)
- Shopify (任意 .myshopify.com 域名)
- 淘宝/天猫
- 京东
- 通用 OG 标签解析

## Workflow

### Step 1: Identify Input Type
- URL → web_fetch 抓取页面
- 图片路径 → VLM 识别
- 商品ID+平台 → 调用对应 API

### Step 2: Parse Product Info
```bash
python /mnt/skills/public/product-parse/scripts/parse.py \
  --input "https://www.amazon.com/dp/B08XXX" \
  --output /mnt/user-data/workspace/product-info.json
```

### Step 3: VLM Enhancement (Optional)
对商品图片调用 VLM 补充识别：
- 材质、颜色、款式
- 适用场景
- 目标人群

## Output Schema
```json
{
  "product_id": "string",
  "title": "string",
  "category": "string",
  "description": "string",
  "key_features": ["string"],
  "target_audience": "string",
  "price_range": "string",
  "brand": "string",
  "main_image_url": "string",
  "gallery_urls": ["string"],
  "selling_points": ["string"]
}
```
