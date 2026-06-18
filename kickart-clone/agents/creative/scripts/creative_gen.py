"""
Creative Agent - 营销创意脚本生成
基于商品信息生成结构化营销创意脚本，输出符合 SOUL.md schema
"""
import argparse
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional


# 创意模板库 - 按类目划分
CREATIVE_TEMPLATES = {
    "apparel": {
        "theme": "时尚穿搭日记",
        "target_audience": "18-35岁都市女性",
        "tone": "时尚、自信、生活化",
        "key_message": "一件单品，多种场景，定义你的风格",
        "scenes": [
            {
                "scene_name": "钩子开场",
                "description": "模特穿着商品在街头转身，镜头特写商品细节",
                "visual_prompt": "fashion model wearing {product}, street style, turning around, close-up on product details, golden hour lighting",
                "text_overlay": "这一件，就够了",
                "voiceover": "还在为每天穿什么发愁？",
                "duration_sec": 3,
            },
            {
                "scene_name": "场景一：通勤",
                "description": "模特在办公室场景穿着商品，展示职场穿搭",
                "visual_prompt": "model wearing {product} in modern office, professional setting, natural lighting, full body shot",
                "text_overlay": "通勤也时尚",
                "voiceover": "通勤也要美美的",
                "duration_sec": 5,
            },
            {
                "scene_name": "场景二：约会",
                "description": "模特在咖啡厅场景穿着商品，展示约会穿搭",
                "visual_prompt": "model wearing {product} in cozy cafe, romantic date setting, warm lighting, medium shot",
                "text_overlay": "约会必备",
                "voiceover": "下班直接去约会？没问题",
                "duration_sec": 5,
            },
            {
                "scene_name": "场景三：周末",
                "description": "模特在公园场景穿着商品，展示休闲穿搭",
                "visual_prompt": "model wearing {product} in autumn park, casual weekend vibe, soft sunlight, lifestyle shot",
                "text_overlay": "周末随心穿",
                "voiceover": "周末出街，自在随心",
                "duration_sec": 5,
            },
            {
                "scene_name": "细节展示",
                "description": "商品面料、剪裁、工艺特写",
                "visual_prompt": "product detail close-up, fabric texture, stitching quality, premium material, studio lighting",
                "text_overlay": "匠心工艺",
                "voiceover": "精选面料，匠心剪裁",
                "duration_sec": 4,
            },
            {
                "scene_name": "CTA结尾",
                "description": "模特自信微笑，展示商品全貌，出现购买引导",
                "visual_prompt": "confident model wearing {product}, full body, studio backdrop, bright lighting, product showcase",
                "text_overlay": "立即购买 | 限时优惠",
                "voiceover": "点击下方链接，立即拥有",
                "duration_sec": 3,
            },
        ],
        "cta": "点击下方链接立即购买，限时优惠！",
    },
    "electronics": {
        "theme": "科技改变生活",
        "target_audience": "25-40岁科技爱好者",
        "tone": "专业、科技感、未来感",
        "key_message": "智能科技，让生活更高效",
        "scenes": [
            {
                "scene_name": "钩子开场",
                "description": "产品在暗色背景中亮起，科技感十足",
                "visual_prompt": "{product} on dark background, glowing, futuristic, tech aesthetic, dramatic lighting",
                "text_overlay": "未来已来",
                "voiceover": "你准备好迎接未来了吗？",
                "duration_sec": 3,
            },
            {
                "scene_name": "痛点场景",
                "description": "用户在使用旧产品时遇到困扰",
                "visual_prompt": "frustrated person using old device, dim lighting, problem scenario, medium shot",
                "text_overlay": "还在忍受这些？",
                "voiceover": "还在为卡顿、续航发愁？",
                "duration_sec": 4,
            },
            {
                "scene_name": "产品亮相",
                "description": "新产品360度展示，突出设计",
                "visual_prompt": "{product} 360 degree rotation, premium design, studio lighting, product photography",
                "text_overlay": "全新{product}",
                "voiceover": "全新{product}，重新定义体验",
                "duration_sec": 5,
            },
            {
                "scene_name": "功能演示",
                "description": "实际使用场景，展示核心功能",
                "visual_prompt": "person using {product} in real scenario, feature demonstration, bright modern setting",
                "text_overlay": "高效 · 智能 · 便捷",
                "voiceover": "一秒启动，智能识别",
                "duration_sec": 6,
            },
            {
                "scene_name": "对比展示",
                "description": "新旧产品对比，突出优势",
                "visual_prompt": "side by side comparison, old vs new {product}, split screen, clear contrast",
                "text_overlay": "性能提升 300%",
                "voiceover": "性能提升3倍，续航延长50%",
                "duration_sec": 4,
            },
            {
                "scene_name": "CTA结尾",
                "description": "产品全家福，购买引导",
                "visual_prompt": "{product} family lineup, premium showcase, dark background with glow, hero shot",
                "text_overlay": "立即预订 | 首发优惠",
                "voiceover": "首发预订，立享优惠",
                "duration_sec": 3,
            },
        ],
        "cta": "立即预订，享受首发优惠！",
    },
    "beauty": {
        "theme": "肌肤焕新之旅",
        "target_audience": "20-40岁爱美女性",
        "tone": "温柔、治愈、专业",
        "key_message": "由内而外，焕发自信光彩",
        "scenes": [
            {
                "scene_name": "钩子开场",
                "description": "模特素颜特写，展示肌肤问题",
                "visual_prompt": "close-up of model face without makeup, natural skin, soft lighting, beauty shot",
                "text_overlay": "肌肤的困扰",
                "voiceover": "干燥、暗沉、细纹...你也有这些困扰吗？",
                "duration_sec": 3,
            },
            {
                "scene_name": "产品亮相",
                "description": "产品精致展示，水滴/质地特写",
                "visual_prompt": "{product} bottle with water droplets, premium skincare packaging, macro shot, clean background",
                "text_overlay": "全新{product}",
                "voiceover": "全新{product}，专为亚洲肌肤研发",
                "duration_sec": 4,
            },
            {
                "scene_name": "成分解析",
                "description": "核心成分可视化展示",
                "visual_prompt": "skincare ingredients visualization, natural elements, scientific aesthetic, clean composition",
                "text_overlay": "核心成分 · 科学配比",
                "voiceover": "蕴含珍稀成分，科学配比",
                "duration_sec": 5,
            },
            {
                "scene_name": "使用演示",
                "description": "模特使用产品，按摩手法展示",
                "visual_prompt": "model applying {product}, skincare routine, gentle massage, bathroom setting, soft lighting",
                "text_overlay": "简单三步，焕然一新",
                "voiceover": "简单三步，唤醒肌肤",
                "duration_sec": 5,
            },
            {
                "scene_name": "效果对比",
                "description": "使用前后对比，真实效果",
                "visual_prompt": "before and after comparison, skin transformation, split screen, beauty photography",
                "text_overlay": "28天见证改变",
                "voiceover": "28天，见证肌肤蜕变",
                "duration_sec": 4,
            },
            {
                "scene_name": "CTA结尾",
                "description": "模特自信笑容，产品展示",
                "visual_prompt": "confident model with glowing skin, smiling, {product} display, bright lighting",
                "text_overlay": "立即体验 | 7天无理由",
                "voiceover": "点击链接，开启你的焕新之旅",
                "duration_sec": 3,
            },
        ],
        "cta": "立即体验，7天无理由退换！",
    },
    "home": {
        "theme": "理想生活空间",
        "target_audience": "25-45岁家居改善人群",
        "tone": "温馨、生活化、品质感",
        "key_message": "小改变，大不同，让家更美好",
        "scenes": [
            {
                "scene_name": "钩子开场",
                "description": "普通家居空间，略显单调",
                "visual_prompt": "ordinary living room, plain decor, natural lighting, wide shot, before scenario",
                "text_overlay": "你的家，还可以更好",
                "voiceover": "觉得家里少了点什么？",
                "duration_sec": 3,
            },
            {
                "scene_name": "产品亮相",
                "description": "产品在场景中精致展示",
                "visual_prompt": "{product} in stylish home setting, interior design, warm lighting, lifestyle photography",
                "text_overlay": "点亮生活",
                "voiceover": "一件好物，点亮整个空间",
                "duration_sec": 5,
            },
            {
                "scene_name": "场景应用",
                "description": "产品在不同房间使用",
                "visual_prompt": "{product} in different rooms, bedroom, living room, kitchen, lifestyle montage",
                "text_overlay": "百搭 · 实用 · 美观",
                "voiceover": "客厅、卧室、厨房，处处适用",
                "duration_sec": 5,
            },
            {
                "scene_name": "细节工艺",
                "description": "产品材质、工艺特写",
                "visual_prompt": "{product} detail close-up, material texture, craftsmanship, macro photography",
                "text_overlay": "匠心品质",
                "voiceover": "精选材质，匠心工艺",
                "duration_sec": 4,
            },
            {
                "scene_name": "生活场景",
                "description": "家人使用产品，温馨画面",
                "visual_prompt": "family using {product} at home, happy moment, warm atmosphere, lifestyle shot",
                "text_overlay": "家的温度",
                "voiceover": "让家更有温度",
                "duration_sec": 5,
            },
            {
                "scene_name": "CTA结尾",
                "description": "产品全家福，购买引导",
                "visual_prompt": "{product} collection display, modern home setting, bright lighting, hero shot",
                "text_overlay": "限时特惠 | 立即下单",
                "voiceover": "限时特惠，立即下单",
                "duration_sec": 3,
            },
        ],
        "cta": "限时特惠，立即下单！",
    },
    "generic": {
        "theme": "好物推荐",
        "target_audience": "通用人群",
        "tone": "亲切、真实、有说服力",
        "key_message": "好产品，值得拥有",
        "scenes": [
            {
                "scene_name": "钩子开场",
                "description": "产品惊艳亮相",
                "visual_prompt": "{product} hero shot, premium display, dramatic lighting, product photography",
                "text_overlay": "好物推荐",
                "voiceover": "今天给大家推荐一款好物",
                "duration_sec": 3,
            },
            {
                "scene_name": "产品介绍",
                "description": "产品全貌展示",
                "visual_prompt": "{product} full view, clean background, studio lighting, product showcase",
                "text_overlay": "精选{product}",
                "voiceover": "这就是{product}",
                "duration_sec": 5,
            },
            {
                "scene_name": "核心卖点",
                "description": "突出产品核心卖点",
                "visual_prompt": "{product} feature highlight, close-up details, benefit demonstration",
                "text_overlay": "核心卖点",
                "voiceover": "它的核心卖点在于...",
                "duration_sec": 5,
            },
            {
                "scene_name": "使用场景",
                "description": "实际使用场景展示",
                "visual_prompt": "{product} in real usage scenario, lifestyle setting, natural lighting",
                "text_overlay": "场景应用",
                "voiceover": "看看实际使用效果",
                "duration_sec": 5,
            },
            {
                "scene_name": "用户评价",
                "description": "真实用户评价展示",
                "visual_prompt": "customer testimonials, real reviews display, social proof, clean layout",
                "text_overlay": "好评如潮",
                "voiceover": "看看用户怎么说",
                "duration_sec": 4,
            },
            {
                "scene_name": "CTA结尾",
                "description": "购买引导",
                "visual_prompt": "{product} with buy button overlay, promotional design, clear CTA",
                "text_overlay": "立即购买",
                "voiceover": "点击链接立即购买",
                "duration_sec": 3,
            },
        ],
        "cta": "点击链接立即购买！",
    },
}


# 类目关键词映射
CATEGORY_KEYWORDS = {
    "apparel": ["服饰", "服装", "衣服", "dress", "shirt", "pants", "fashion", "穿搭", "模特", "shirt", "skirt", "jacket", "coat"],
    "electronics": ["电子", "数码", "手机", "耳机", "speaker", "phone", "laptop", "tech", "智能", "device", "gadget"],
    "beauty": ["美妆", "护肤", "化妆品", "skincare", "cosmetic", "makeup", "cream", "serum", "beauty"],
    "home": ["家居", "家具", "home", "furniture", "decor", "装饰", "厨房", "kitchen", "living"],
}


def detect_category(product_info: dict) -> str:
    """根据商品信息自动检测类目"""
    text = " ".join([
        str(product_info.get("title", "")),
        str(product_info.get("description", "")),
        str(product_info.get("category", "")),
        " ".join(product_info.get("key_features", []) or []),
        " ".join(product_info.get("selling_points", []) or []),
    ]).lower()

    scores = {}
    for cat, keywords in CATEGORY_KEYWORDS.items():
        scores[cat] = sum(1 for kw in keywords if kw.lower() in text)

    best_cat = max(scores, key=scores.get) if scores else "generic"
    return best_cat if scores.get(best_cat, 0) > 0 else "generic"


def generate_creative(
    product_info: dict,
    category: Optional[str] = None,
    theme: Optional[str] = None,
    target_audience: Optional[str] = None,
    tone: Optional[str] = None,
    num_scenes: int = 6,
) -> dict:
    """
    生成营销创意脚本

    Args:
        product_info: 商品信息 dict
        category: 指定类目（auto detect if None）
        theme: 自定义主题
        target_audience: 自定义目标人群
        tone: 自定义调性
        num_scenes: 场景数量

    Returns:
        符合 SOUL.md schema 的创意脚本
    """
    # 类目检测
    if not category:
        category = detect_category(product_info)
    template = CREATIVE_TEMPLATES.get(category, CREATIVE_TEMPLATES["generic"])

    # 商品名称（用于 prompt 替换）
    product_name = product_info.get("title", "the product")
    product_desc = product_info.get("description", "")

    # 应用自定义参数
    final_theme = theme or template["theme"]
    final_audience = target_audience or template["target_audience"]
    final_tone = tone or template["tone"]
    key_message = template["key_message"]

    # 生成场景列表
    scenes = []
    template_scenes = template["scenes"][:num_scenes]
    for idx, scene_tpl in enumerate(template_scenes, 1):
        # 替换 prompt 中的 {product} 占位符
        visual_prompt = scene_tpl["visual_prompt"].replace("{product}", product_name)
        voiceover = scene_tpl["voiceover"].replace("{product}", product_name)
        text_overlay = scene_tpl["text_overlay"].replace("{product}", product_name)

        scenes.append({
            "scene_id": idx,
            "scene_name": scene_tpl["scene_name"],
            "description": scene_tpl["description"],
            "visual_prompt": visual_prompt,
            "text_overlay": text_overlay,
            "voiceover": voiceover,
            "duration_sec": scene_tpl["duration_sec"],
        })

    total_duration = sum(s["duration_sec"] for s in scenes)

    # 生成 storyline
    storyline = f"以'{final_theme}'为主题，针对{final_audience}，通过{len(scenes)}个场景展示{product_name}的{final_tone}调性。核心信息：{key_message}"

    return {
        "creative_id": f"creative_{uuid.uuid4().hex[:8]}",
        "generated_at": datetime.now().isoformat(),
        "product": {
            "product_id": product_info.get("product_id", ""),
            "title": product_name,
            "category": category,
            "description": product_desc,
        },
        "theme": final_theme,
        "storyline": storyline,
        "target_audience": final_audience,
        "tone": final_tone,
        "key_message": key_message,
        "scenes": scenes,
        "total_duration": total_duration,
        "cta": template["cta"],
    }


def main():
    parser = argparse.ArgumentParser(description="Creative Agent - 营销创意脚本生成")
    parser.add_argument(
        "--product-json",
        required=True,
        help="商品信息 JSON 文件路径",
    )
    parser.add_argument(
        "--category",
        choices=["apparel", "electronics", "beauty", "home", "generic"],
        help="商品类目（不指定则自动检测）",
    )
    parser.add_argument("--theme", help="自定义主题")
    parser.add_argument("--target-audience", help="自定义目标人群")
    parser.add_argument("--tone", help="自定义调性")
    parser.add_argument(
        "--num-scenes",
        type=int,
        default=6,
        help="场景数量（默认6）",
    )
    parser.add_argument(
        "--output",
        default="/mnt/user-data/workspace/creative.json",
        help="输出文件路径",
    )

    args = parser.parse_args()

    # 读取商品信息
    product_path = Path(args.product_json)
    if not product_path.exists():
        print(f"错误: 商品信息文件不存在: {product_path}")
        return 1

    with open(product_path, "r", encoding="utf-8") as f:
        product_info = json.load(f)

    # 生成创意脚本
    creative = generate_creative(
        product_info=product_info,
        category=args.category,
        theme=args.theme,
        target_audience=args.target_audience,
        tone=args.tone,
        num_scenes=args.num_scenes,
    )

    # 输出
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(creative, f, ensure_ascii=False, indent=2)

    print(f"✅ 创意脚本生成成功！")
    print(f"   创意ID: {creative['creative_id']}")
    print(f"   主题: {creative['theme']}")
    print(f"   类目: {creative['product']['category']}")
    print(f"   场景数: {len(creative['scenes'])}")
    print(f"   总时长: {creative['total_duration']}s")
    print(f"   输出: {output_path}")
    return 0


if __name__ == "__main__":
    exit(main())
