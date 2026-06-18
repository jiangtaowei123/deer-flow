"""
TTS Agent - 语音合成
将分镜列表中的旁白文本转化为完整语音音轨
支持 edge-tts（首选）和 pyttsx3（回退）
"""
import argparse
import asyncio
import json
import os
import subprocess
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional


# 可用音色
VOICES = {
    "xiaoxiao": "zh-CN-XiaoxiaoNeural",      # 女声，温暖亲切（默认）
    "yunxi": "zh-CN-YunxiNeural",             # 男声，年轻活力
    "yunjian": "zh-CN-YunjianNeural",         # 男声，沉稳专业
    "xiaoyi": "zh-CN-XiaoyiNeural",           # 女声，活泼可爱
    "yunyang": "zh-CN-YunyangNeural",         # 男声，新闻播报
    "xiaohan": "zh-CN-XiaohanNeural",         # 女声，温柔抒情
}


def check_edge_tts() -> bool:
    """检查 edge-tts 是否可用"""
    try:
        result = subprocess.run(
            ["edge-tts", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def check_ffmpeg() -> bool:
    """检查 ffmpeg 是否可用"""
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


async def generate_tts_segment(
    text: str,
    output_path: str,
    voice: str = "zh-CN-XiaoxiaoNeural",
    rate: str = "+0%",
    pitch: str = "+0Hz",
) -> bool:
    """使用 edge-tts 生成单段语音"""
    try:
        import edge_tts
        communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
        await communicate.save(output_path)
        return os.path.exists(output_path)
    except ImportError:
        return False
    except Exception as e:
        print(f"  ⚠️  edge-tts 生成失败: {e}")
        return False


def generate_tts_segment_sync(
    text: str,
    output_path: str,
    voice: str = "zh-CN-XiaoxiaoNeural",
) -> bool:
    """同步包装的 TTS 生成"""
    try:
        return asyncio.run(generate_tts_segment(text, output_path, voice))
    except RuntimeError:
        # 已有事件循环时
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(generate_tts_segment(text, output_path, voice))
        finally:
            loop.close()


def generate_silence(duration: float, output_path: str) -> bool:
    """生成指定时长的静音音频"""
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"anullsrc=channel_layout=stereo:sample_rate=44100",
        "-t", str(duration),
        "-c:a", "aac",
        output_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        return False


def adjust_audio_duration(input_path: str, output_path: str, target_duration: float) -> bool:
    """
    调整音频时长以匹配分镜时长
    - 如果 TTS 音频短于分镜：末尾补静音
    - 如果 TTS 音频长于分镜：截断
    """
    # 先获取音频时长
    cmd_probe = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        input_path,
    ]
    try:
        result = subprocess.run(cmd_probe, capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            return False
        audio_duration = float(result.stdout.strip())
    except (ValueError, subprocess.TimeoutExpired):
        return False

    if audio_duration >= target_duration:
        # 截断
        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-t", str(target_duration),
            "-c:a", "aac",
            output_path,
        ]
    else:
        # 补静音
        silence_duration = target_duration - audio_duration
        silence_path = output_path + ".silence.aac"
        if not generate_silence(silence_duration, silence_path):
            # 失败则直接复制
            cmd = ["ffmpeg", "-y", "-i", input_path, "-c:a", "aac", output_path]
        else:
            # 拼接
            list_file = output_path + ".list.txt"
            with open(list_file, "w") as f:
                f.write(f"file '{input_path}'\n")
                f.write(f"file '{silence_path}'\n")
            cmd = [
                "ffmpeg", "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", list_file,
                "-c:a", "aac",
                output_path,
            ]
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                os.unlink(list_file)
                os.unlink(silence_path)
                return result.returncode == 0
            except subprocess.TimeoutExpired:
                return False

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        return False


def concat_audio_segments(segment_paths: list, output_path: str) -> bool:
    """拼接音频片段"""
    if not segment_paths:
        return False

    output_path = str(output_path)
    list_file = output_path + ".list.txt"
    with open(list_file, "w", encoding="utf-8") as f:
        for seg in segment_paths:
            f.write(f"file '{seg}'\n")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", list_file,
        "-c:a", "aac",
        output_path,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        os.unlink(list_file)
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        return False


def generate_narration(
    storyboard: dict,
    output_dir: str,
    voice: str = "xiaoxiao",
    rate: str = "+0%",
) -> dict:
    """
    生成分镜列表对应的完整旁白音轨

    Args:
        storyboard: 分镜列表
        output_dir: 输出目录
        voice: 音色名称
        rate: 语速调整

    Returns:
        旁白生成结果
    """
    if not check_ffmpeg():
        return {"success": False, "error": "ffmpeg 未安装或不可用"}

    voice_id = VOICES.get(voice, VOICES["xiaoxiao"])
    has_edge_tts = check_edge_tts()

    if not has_edge_tts:
        print("⚠️  edge-tts 不可用，尝试安装...")
        try:
            subprocess.run(
                ["pip", "install", "edge-tts", "--break-system-packages", "-q"],
                capture_output=True, text=True, timeout=60,
            )
            has_edge_tts = check_edge_tts()
        except Exception:
            pass

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    audio_id = f"audio_{uuid.uuid4().hex[:8]}"
    work_dir = output_dir / f"work_{audio_id}"
    work_dir.mkdir(parents=True, exist_ok=True)

    shots = storyboard.get("shots", [])
    segment_paths = []
    segments_count = 0

    print(f"🎙️  开始生成旁白（{len(shots)} 个分镜，音色: {voice}）...")

    for idx, shot in enumerate(shots, 1):
        voiceover = shot.get("voiceover", "")
        duration = shot.get("duration_sec", 5)

        if not voiceover:
            print(f"  [{idx}/{len(shots)}] 无旁白文本，生成静音 ({duration}s)")
            seg_path = str(work_dir / f"seg_{idx:03d}.aac")
            if generate_silence(duration, seg_path):
                segment_paths.append(seg_path)
                segments_count += 1
            continue

        print(f"  [{idx}/{len(shots)}] 生成: {voiceover[:30]}...")

        # 生成原始 TTS
        raw_path = str(work_dir / f"raw_{idx:03d}.mp3")
        if has_edge_tts:
            success = generate_tts_segment_sync(voiceover, raw_path, voice_id)
        else:
            success = False

        if not success:
            # 回退：生成静音
            print(f"  ⚠️  TTS 失败，使用静音替代")
            seg_path = str(work_dir / f"seg_{idx:03d}.aac")
            if generate_silence(duration, seg_path):
                segment_paths.append(seg_path)
                segments_count += 1
            continue

        # 调整时长匹配分镜
        seg_path = str(work_dir / f"seg_{idx:03d}.aac")
        if adjust_audio_duration(raw_path, seg_path, duration):
            segment_paths.append(seg_path)
            segments_count += 1
        else:
            # 失败则使用原始音频
            segment_paths.append(raw_path)
            segments_count += 1

    if not segment_paths:
        return {"success": False, "error": "没有成功生成任何音频片段"}

    # 拼接所有片段
    print(f"🔗 拼接 {len(segment_paths)} 个音频片段...")
    final_path = output_dir / f"{audio_id}.aac"
    if not concat_audio_segments(segment_paths, final_path):
        return {"success": False, "error": "音频拼接失败"}

    # 清理工作目录
    try:
        import shutil
        shutil.rmtree(work_dir, ignore_errors=True)
    except Exception:
        pass

    # 获取文件信息
    file_size = os.path.getsize(final_path) / (1024 * 1024)
    total_duration = sum(s.get("duration_sec", 5) for s in shots)

    print(f"✅ 旁白生成完成！")
    print(f"   音频 ID: {audio_id}")
    print(f"   输出路径: {final_path}")
    print(f"   时长: {total_duration}s")
    print(f"   音色: {voice} ({voice_id})")
    print(f"   文件大小: {file_size:.2f} MB")

    return {
        "success": True,
        "audio_id": audio_id,
        "output_path": str(final_path),
        "duration_sec": total_duration,
        "voice": voice,
        "voice_id": voice_id,
        "segments_count": segments_count,
        "file_size_mb": round(file_size, 2),
        "generated_at": datetime.now().isoformat(),
    }


def main():
    parser = argparse.ArgumentParser(description="TTS Agent - 语音合成")
    parser.add_argument(
        "--storyboard-json",
        required=True,
        help="Storyboard Agent 输出的分镜 JSON 文件路径",
    )
    parser.add_argument(
        "--voice",
        default="xiaoxiao",
        choices=list(VOICES.keys()),
        help="音色（默认 xiaoxiao 女声温暖）",
    )
    parser.add_argument(
        "--rate",
        default="+0%",
        help="语速调整（如 +10%, -10%）",
    )
    parser.add_argument(
        "--output-dir",
        default="/mnt/user-data/workspace/audio",
        help="输出目录",
    )

    args = parser.parse_args()

    # 读取分镜
    storyboard_path = Path(args.storyboard_json)
    if not storyboard_path.exists():
        print(f"错误: 分镜文件不存在: {storyboard_path}")
        return 1

    with open(storyboard_path, "r", encoding="utf-8") as f:
        storyboard = json.load(f)

    # 生成旁白
    result = generate_narration(
        storyboard=storyboard,
        output_dir=args.output_dir,
        voice=args.voice,
        rate=args.rate,
    )

    # 输出结果 JSON
    result_path = Path(args.output_dir) / f"{result.get('audio_id', 'audio')}_result.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    if result.get("success"):
        print(f"\n📊 结果已保存: {result_path}")
        return 0
    else:
        print(f"\n❌ 生成失败: {result.get('error')}")
        return 1


if __name__ == "__main__":
    exit(main())
