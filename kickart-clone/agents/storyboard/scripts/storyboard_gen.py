"""
Storyboard Agent - 分镜设计
将创意脚本转化为可执行的分镜列表，每个分镜对应一张图片或一段视频
输出符合 SOUL.md schema
"""
import argparse
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional


# 分镜类型映射：根据场景名推断镜头类型
SHOT_TYPE_RULES = {
    "钩子": ("medium", "eye-level", "rule-of-thirds", "dramatic"),
    "开场": ("medium", "eye-level", "rule-of-thirds", "dramatic"),
    "亮相": ("product", "front", "centered", "studio"),
    "细节": ("closeup", "macro", "centered", "soft"),
    "特写": ("closeup", "macro", "centered", "soft"),
    "工艺": ("closeup", "macro", "centered", "soft"),
    "成分": ("closeup", "top-down", "centered", "soft"),
    "演示": ("medium", "eye-level", "rule-of-thirds", "natural"),
    "场景": ("wide", "eye-level", "rule-of-thirds", "natural"),
    "应用": ("lifestyle", "eye-level", "rule-of-thirds", "natural"),
    "对比": ("product", "front", "split-screen", "studio"),
    "评价": ("medium", "eye-level", "centered", "soft"),
    "结尾": ("wide", "eye-level", "centered", "bright"),
    "CTA": ("product", "front", "centered", "bright"),
}


# 调性 → 色彩映射
TONE_COLOR_PALETTES = {
    "时尚": ["#2C2C2C", "#F5F5F5", "#C9A96E", "#8B6F47"],
    "自信": ["#1A1A2E", "#16213E", "#E94560", "#F5F5F5"],
    "生活化": ["#F5E6D3", "#A8B5A2", "#D4A574", "#7A6B5D"],
    "专业": ["#0A0A0A", "#1E1E1E", "#00D4FF", "#F5F5F5"],
    "科技感": ["#0A0E27", "#1A1F3A", "#00FF88", "#FFFFFF"],
    "未来感": ["#000000", "#0A0A2E", "#00FFFF", "#FF00FF"],
    "温柔": ["#FFF5F0", "#F4C2C2", "#E8B4B8", "#D4A5A5"],
    "治愈": ["#F0F4F8", "#C8E6C9", "#A5D6A7", "#81C784"],
    "温馨": ["#FFF8E7", "#D4A574", "#A0683E", "#6B4423"],
    "品质感": ["#1C1C1C", "#3D3D3D", "#C9A96E", "#F5F5F5"],
    "亲切": ["#FFF5E6", "#FFB347", "#FF9999", "#87CEEB"],
    "真实": ["#F5F5DC", "#D2B48C", "#BC8F8F", "#8B7355"],
    "有说服力": ["#FFFFFF", "#000000", "#FF6B6B", "#4ECDC4"],
}


# 通用负面提示词
DEFAULT_NEGATIVE_PROMPT = (
    "lowres, bad anatomy, bad hands, text, error, missing fingers, "
    "extra digit, fewer digits, cropped, worst quality, low quality, "
    "normal quality, jpeg artifacts, signature, watermark, username, blurry, "
    "deformed, disfigured, mutation, malformed, duplicate"
)


def infer_shot_type(scene_name: str) -> tuple:
    """根据场景名推断镜头参数"""
    for keyword, params in SHOT_TYPE_RULES.items():
        if keyword in scene_name:
            return params
    return ("medium", "eye-level", "rule-of-thirds", "natural")


def get_color_palette(tone: str) -> list:
    """根据调性获取色彩方案"""
    for keyword, palette in TONE_COLOR_PALETTES.items():
        if keyword in tone:
            return palette
    return ["#FFFFFF", "#000000", "#808080", "#C0C0C0"]


def generate_storyboard(
    creative: dict,
    aspect_ratio: str = "9:16",
    default_transition: str = "cut",
) -> dict:
    """
    将创意脚本转化为分镜列表

    Args:
        creative: Creative Agent 输出的创意脚本
        aspect_ratio: 默认宽高比（9:16 竖屏适合短视频）
        default_transition: 默认转场

    Returns:
        符合 SOUL.md schema 的分镜列表
    """
    tone = creative.get("tone", "")
    color_palette = get_color_palette(tone)
    scenes = creative.get("scenes", [])

    shots = []
    for idx, scene in enumerate(scenes, 1):
        scene_name = scene.get("scene_name", f"场景{idx}")
        shot_type, angle, composition, lighting = infer_shot_type(scene_name)

        # 构建正面提示词
        visual_prompt = scene.get("visual_prompt", "")
        positive_prompt = visual_prompt

        # 根据镜头类型增强提示词
        enhancements = {
            "wide": "wide angle shot, full scene, environmental",
            "medium": "medium shot, waist up, balanced framing",
            "closeup": "extreme close-up, macro detail, sharp focus",
            "product": "product photography, studio shot, centered composition",
            "lifestyle": "lifestyle photography, candid moment, natural pose",
        }
        if shot_type in enhancements:
            positive_prompt = f"{visual_prompt}, {enhancements[shot_type]}"

        # 添加调性增强
        if "时尚" in tone:
            positive_prompt += ", editorial fashion, vogue style"
        elif "科技" in tone or "未来" in tone:
            positive_prompt += ", cinematic, futuristic, high detail"
        elif "温柔" in tone or "治愈" in tone:
            positive_prompt += ", soft focus, dreamy, pastel tones"
        elif "温馨" in tone:
            positive_prompt += ", warm tones, cozy atmosphere"

        # 转场：最后一个场景无转场
        transition = default_transition if idx < len(scenes) else "none"

        shots.append({
            "shot_id": idx,
            "scene_ref": scene.get("scene_id", idx),
            "scene_name": scene_name,
            "shot_type": shot_type,
            "angle": angle,
            "composition": composition,
            "lighting": lighting,
            "color_palette": color_palette,
            "positive_prompt": positive_prompt,
            "negative_prompt": DEFAULT_NEGATIVE_PROMPT,
            "aspect_ratio": aspect_ratio,
            "duration_sec": scene.get("duration_sec", 5),
            "transition": transition,
            "text_overlay": scene.get("text_overlay", ""),
            "voiceover": scene.get("voiceover", ""),
        })

    return {
        "storyboard_id": f"storyboard_{uuid.uuid4().hex[:8]}",
        "generated_at": datetime.now().isoformat(),
        "creative_id": creative.get("creative_id", ""),
        "product_title": creative.get("product", {}).get("title", ""),
        "total_shots": len(shots),
        "total_duration": sum(s["duration_sec"] for s in shots),
        "aspect_ratio": aspect_ratio,
        "shots": shots,
    }


def main():
    parser = argparse.ArgumentParser(description="Storyboard Agent - 分镜设计")
    parser.add_argument(
        "--creative-json",
        required=True,
        help="Creative Agent 输出的创意脚本 JSON 文件路径",
    )
    parser.add_argument(
        "--aspect-ratio",
        default="9:16",
        choices=["9:16", "16:9", "1:1", "4:3", "3:4"],
        help="宽高比（默认 9:16 竖屏）",
    )
    parser.add_argument(
        "--transition",
        default="cut",
        choices=["cut", "fade", "dissolve", "slide", "zoom"],
        help="默认转场效果",
    )
    parser.add_argument(
        "--output",
        default="/mnt/user-data/workspace/storyboard.json",
        help="输出文件路径",
    )

    args = parser.parse_args()

    # 读取创意脚本
    creative_path = Path(args.creative_json)
    if not creative_path.exists():
        print(f"错误: 创意脚本文件不存在: {creative_path}")
        return 1

    with open(creative_path, "r", encoding="utf-8") as f:
        creative = json.load(f)

    # 生成分镜
    storyboard = generate_storyboard(
        creative=creative,
        aspect_ratio=args.aspect_ratio,
        default_transition=args.transition,
    )

    # 输出
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(storyboard, f, ensure_ascii=False, indent=2)

    print(f"✅ 分镜列表生成成功！")
    print(f"   分镜ID: {storyboard['storyboard_id']}")
    print(f"   总分镜数: {storyboard['total_shots']}")
    print(f"   总时长: {storyboard['total_duration']}s")
    print(f"   宽高比: {storyboard['aspect_ratio']}")
    print(f"   输出: {output_path}")

    # 打印分镜摘要
    print(f"\n📋 分镜摘要:")
    for shot in storyboard["shots"]:
        print(f"   #{shot['shot_id']} [{shot['shot_type']}] {shot['scene_name']} ({shot['duration_sec']}s) → {shot['transition']}")
    return 0


if __name__ == "__main__":
    exit(main())
