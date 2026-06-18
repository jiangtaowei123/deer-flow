"""
V1 端到端测试 - 视频成片工作流
测试完整链路：商品信息 → Creative → Storyboard → TTS → Video
"""
import json
import os
import sys
import tempfile
from pathlib import Path

# 添加项目路径
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "agents" / "creative" / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "agents" / "storyboard" / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "agents" / "video_gen" / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "agents" / "tts" / "scripts"))

from creative_gen import generate_creative, detect_category
from storyboard_gen import generate_storyboard
from video_compose import compose_video, check_ffmpeg
from tts_gen import generate_narration, check_edge_tts


# 测试商品信息
TEST_PRODUCTS = [
    {
        "name": "服饰商品",
        "product_info": {
            "product_id": "B0TEST001",
            "platform": "amazon",
            "title": "Women's Casual Summer Dress Floral Print",
            "category": "apparel",
            "description": "优雅的夏季碎花连衣裙，适合多种场合穿着",
            "key_features": ["轻盈面料", "修身剪裁", "多场景适用"],
            "selling_points": ["时尚百搭", "舒适透气"],
            "target_audience": "18-35岁都市女性",
        },
        "expected_category": "apparel",
    },
    {
        "name": "电子产品",
        "product_info": {
            "product_id": "B0TEST002",
            "platform": "amazon",
            "title": "Wireless Bluetooth Headphones Noise Cancelling",
            "category": "electronics",
            "description": "高品质无线降噪耳机，沉浸式音乐体验",
            "key_features": ["主动降噪", "30小时续航", "蓝牙5.3"],
            "selling_points": ["音质卓越", "佩戴舒适"],
            "target_audience": "25-40岁科技爱好者",
        },
        "expected_category": "electronics",
    },
    {
        "name": "美妆产品",
        "product_info": {
            "product_id": "B0TEST003",
            "platform": "amazon",
            "title": "Vitamin C Serum Brightening Skincare",
            "category": "beauty",
            "description": "维C亮肤精华液，焕亮肌肤",
            "key_features": ["15%维C浓度", "玻尿酸", "烟酰胺"],
            "selling_points": ["提亮肤色", "淡化细纹"],
            "target_audience": "20-40岁爱美女性",
        },
        "expected_category": "beauty",
    },
]


def create_test_images(num_images: int, output_dir: str) -> list:
    """创建测试图片（纯色占位图）"""
    from PIL import Image, ImageDraw

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    colors = [
        (255, 105, 180),  # 粉色
        (100, 149, 237),  # 蓝色
        (144, 238, 144),  # 绿色
        (255, 165, 0),    # 橙色
        (186, 85, 211),   # 紫色
        (255, 215, 0),    # 金色
    ]

    image_paths = []
    for i in range(1, num_images + 1):
        color = colors[(i - 1) % len(colors)]
        img = Image.new("RGB", (1080, 1920), color)
        draw = ImageDraw.Draw(img)
        # 添加文字标识
        draw.text(
            (540, 960),
            f"Shot {i}",
            fill="white",
            anchor="mm",
        )
        img_path = output_dir / f"shot_{i}.png"
        img.save(img_path)
        image_paths.append(str(img_path))

    return image_paths


def test_creative_agent(product_info: dict, expected_category: str) -> dict:
    """测试 Creative Agent"""
    print("\n" + "=" * 60)
    print("📝 测试 1: Creative Agent 脚本生成")
    print("=" * 60)

    # 测试类目检测
    detected = detect_category(product_info)
    print(f"  类目检测: {detected} (期望: {expected_category})")
    assert detected == expected_category, f"类目检测失败: {detected} != {expected_category}"

    # 生成创意脚本
    creative = generate_creative(
        product_info=product_info,
        num_scenes=6,
    )

    # 验证 schema
    assert "creative_id" in creative, "缺少 creative_id"
    assert "theme" in creative, "缺少 theme"
    assert "scenes" in creative, "缺少 scenes"
    assert len(creative["scenes"]) == 6, f"场景数不匹配: {len(creative['scenes'])}"
    assert creative["total_duration"] > 0, "总时长应大于0"

    # 验证每个场景
    for scene in creative["scenes"]:
        assert "scene_id" in scene, "场景缺少 scene_id"
        assert "visual_prompt" in scene, "场景缺少 visual_prompt"
        assert "voiceover" in scene, "场景缺少 voiceover"
        assert "duration_sec" in scene, "场景缺少 duration_sec"
        # 验证 {product} 占位符已替换
        assert "{product}" not in scene["visual_prompt"], "visual_prompt 中 {product} 未替换"

    print(f"  ✅ 创意ID: {creative['creative_id']}")
    print(f"  ✅ 主题: {creative['theme']}")
    print(f"  ✅ 场景数: {len(creative['scenes'])}")
    print(f"  ✅ 总时长: {creative['total_duration']}s")
    print(f"  ✅ CTA: {creative['cta']}")

    return creative


def test_storyboard_agent(creative: dict) -> dict:
    """测试 Storyboard Agent"""
    print("\n" + "=" * 60)
    print("🎬 测试 2: Storyboard Agent 分镜生成")
    print("=" * 60)

    storyboard = generate_storyboard(
        creative=creative,
        aspect_ratio="9:16",
        default_transition="cut",
    )

    # 验证 schema
    assert "storyboard_id" in storyboard, "缺少 storyboard_id"
    assert "shots" in storyboard, "缺少 shots"
    assert storyboard["total_shots"] == len(creative["scenes"]), "分镜数应等于场景数"
    assert storyboard["aspect_ratio"] == "9:16", "宽高比应为 9:16"

    # 验证每个分镜
    for shot in storyboard["shots"]:
        assert "shot_id" in shot, "分镜缺少 shot_id"
        assert "shot_type" in shot, "分镜缺少 shot_type"
        assert "positive_prompt" in shot, "分镜缺少 positive_prompt"
        assert "negative_prompt" in shot, "分镜缺少 negative_prompt"
        assert "duration_sec" in shot, "分镜缺少 duration_sec"
        assert "transition" in shot, "分镜缺少 transition"
        assert shot["shot_type"] in ["wide", "medium", "closeup", "product", "lifestyle"], \
            f"无效的 shot_type: {shot['shot_type']}"

    # 验证最后一个分镜无转场
    assert storyboard["shots"][-1]["transition"] == "none", "最后一个分镜应无转场"

    print(f"  ✅ 分镜ID: {storyboard['storyboard_id']}")
    print(f"  ✅ 总分镜数: {storyboard['total_shots']}")
    print(f"  ✅ 总时长: {storyboard['total_duration']}s")
    print(f"  ✅ 宽高比: {storyboard['aspect_ratio']}")

    # 打印分镜摘要
    for shot in storyboard["shots"]:
        print(f"     #{shot['shot_id']} [{shot['shot_type']:8s}] {shot['scene_name']}")

    return storyboard


def test_tts_agent(storyboard: dict, output_dir: str) -> dict:
    """测试 TTS Agent"""
    print("\n" + "=" * 60)
    print("🎙️  测试 3: TTS Agent 语音合成")
    print("=" * 60)

    has_edge_tts = check_edge_tts()
    if not has_edge_tts:
        print("  ⚠️  edge-tts 不可用，将使用静音回退")

    result = generate_narration(
        storyboard=storyboard,
        output_dir=output_dir,
        voice="xiaoxiao",
    )

    assert result["success"], f"TTS 生成失败: {result.get('error')}"
    assert os.path.exists(result["output_path"]), "音频文件不存在"

    print(f"  ✅ 音频ID: {result['audio_id']}")
    print(f"  ✅ 输出: {result['output_path']}")
    print(f"  ✅ 时长: {result['duration_sec']}s")
    print(f"  ✅ 片段数: {result['segments_count']}")

    return result


def test_video_agent(storyboard: dict, images_dir: str, audio_path: str, output_dir: str) -> dict:
    """测试 Video Agent"""
    print("\n" + "=" * 60)
    print("🎞️  测试 4: Video Agent 视频合成")
    print("=" * 60)

    if not check_ffmpeg():
        print("  ⚠️  ffmpeg 不可用，跳过视频合成测试")
        return {"success": False, "error": "ffmpeg 不可用"}

    result = compose_video(
        storyboard=storyboard,
        images_dir=images_dir,
        output_dir=output_dir,
        audio_path=audio_path,
        burn_subs=True,
        aspect_ratio="9:16",
    )

    assert result["success"], f"视频合成失败: {result.get('error')}"
    assert os.path.exists(result["output_path"]), "视频文件不存在"
    assert result["shots_count"] > 0, "合成的分镜数应大于0"

    print(f"  ✅ 视频ID: {result['video_id']}")
    print(f"  ✅ 输出: {result['output_path']}")
    print(f"  ✅ 时长: {result['duration_sec']}s")
    print(f"  ✅ 分辨率: {result['resolution']}")
    print(f"  ✅ 分镜数: {result['shots_count']}")
    print(f"  ✅ 文件大小: {result['file_size_mb']} MB")

    return result


def test_e2e_workflow():
    """端到端工作流测试"""
    print("\n" + "=" * 60)
    print("🚀 V1 端到端测试：视频成片工作流")
    print("=" * 60)

    # 创建临时工作目录
    with tempfile.TemporaryDirectory(prefix="kickart_v1_test_") as work_dir:
        work_dir = Path(work_dir)
        images_dir = work_dir / "images"
        audio_dir = work_dir / "audio"
        video_dir = work_dir / "videos"

        all_results = []

        for test_case in TEST_PRODUCTS:
            print(f"\n{'#' * 60}")
            print(f"# 测试商品: {test_case['name']}")
            print(f"{'#' * 60}")

            product_info = test_case["product_info"]
            expected_category = test_case["expected_category"]

            try:
                # 1. Creative Agent
                creative = test_creative_agent(product_info, expected_category)

                # 2. Storyboard Agent
                storyboard = test_storyboard_agent(creative)

                # 3. 创建测试图片
                num_shots = len(storyboard["shots"])
                print(f"\n📸 创建 {num_shots} 张测试图片...")
                create_test_images(num_shots, images_dir)

                # 4. TTS Agent
                tts_result = test_tts_agent(storyboard, str(audio_dir))

                # 5. Video Agent
                video_result = test_video_agent(
                    storyboard=storyboard,
                    images_dir=str(images_dir),
                    audio_path=tts_result["output_path"],
                    output_dir=str(video_dir),
                )

                all_results.append({
                    "product": test_case["name"],
                    "creative_id": creative["creative_id"],
                    "storyboard_id": storyboard["storyboard_id"],
                    "audio_id": tts_result["audio_id"],
                    "video_id": video_result["video_id"],
                    "video_path": video_result["output_path"],
                    "duration": video_result["duration_sec"],
                    "success": True,
                })

                print(f"\n✅ {test_case['name']} 测试通过！")

            except Exception as e:
                print(f"\n❌ {test_case['name']} 测试失败: {e}")
                all_results.append({
                    "product": test_case["name"],
                    "success": False,
                    "error": str(e),
                })
                import traceback
                traceback.print_exc()

        # 汇总
        print("\n" + "=" * 60)
        print("📊 测试汇总")
        print("=" * 60)

        passed = sum(1 for r in all_results if r.get("success"))
        total = len(all_results)

        for r in all_results:
            status = "✅ PASS" if r.get("success") else "❌ FAIL"
            print(f"  {status} - {r['product']}")
            if r.get("success"):
                print(f"         视频: {r.get('video_path', 'N/A')}")
                print(f"         时长: {r.get('duration', 0)}s")

        print(f"\n  总计: {passed}/{total} 通过")

        if passed == total:
            print("\n🎉 所有测试通过！V1 视频成片工作流就绪。")
            return 0
        else:
            print(f"\n⚠️  {total - passed} 个测试失败")
            return 1


if __name__ == "__main__":
    exit(test_e2e_workflow())
