"""
Video Gen Agent - 视频合成
将分镜列表和已生成的图片合成为完整的营销视频
支持 Ken Burns 效果、转场、TTS 旁白、字幕烧录
"""
import argparse
import json
import os
import subprocess
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional


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


def parse_aspect_ratio(aspect: str) -> tuple:
    """解析宽高比为 (width, height)"""
    ratios = {
        "9:16": (1080, 1920),
        "16:9": (1920, 1080),
        "1:1": (1080, 1080),
        "4:3": (1440, 1080),
        "3:4": (1080, 1440),
    }
    return ratios.get(aspect, (1080, 1920))


def build_ken_burns_filter(
    duration: float,
    width: int,
    height: int,
    zoom_direction: str = "in",
) -> str:
    """
    构建 Ken Burns 效果的 ffmpeg 滤镜
    zoom_direction: in（放大）或 out（缩小）或 pan（平移）
    """
    if zoom_direction == "in":
        # 缓慢放大
        return (
            f"scale={width*2}:{height*2}:flags=lanczos,"
            f"zoompan=z='min(zoom+0.0015,1.5)':d={int(duration*25)}:"
            f"s={width}x{height}:fps=25"
        )
    elif zoom_direction == "out":
        # 缓慢缩小
        return (
            f"scale={width*2}:{height*2}:flags=lanczos,"
            f"zoompan=z='if(eq(on,0),1.5,max(zoom-0.0015,1.0))':d={int(duration*25)}:"
            f"s={width}x{height}:fps=25"
        )
    else:
        # 平移
        return (
            f"scale={width*2}:{height*2}:flags=lanczos,"
            f"zoompan=z=1.2:x='iw/2-(iw/zoom/2)+sin(on/40)*50':"
            f"y='ih/2-(ih/zoom/2)':d={int(duration*25)}:s={width}x{height}:fps=25"
        )


def generate_shot_clip(
    image_path: str,
    duration: float,
    width: int,
    height: int,
    output_path: str,
    zoom_direction: str = "in",
) -> bool:
    """为单张图片生成带 Ken Burns 效果的视频片段"""
    if not os.path.exists(image_path):
        print(f"  ⚠️  图片不存在: {image_path}，生成黑场片段")
        # 生成黑场片段
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"color=c=black:s={width}x{height}:d={duration}:r=25",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            output_path,
        ]
    else:
        filter_str = build_ken_burns_filter(duration, width, height, zoom_direction)
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1",
            "-i", image_path,
            "-vf", filter_str,
            "-t", str(duration),
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-r", "25",
            output_path,
        ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        print(f"  ⚠️  ffmpeg 超时: {image_path}")
        return False


def concat_clips(clip_paths: list, output_path: str, transition: str = "cut") -> bool:
    """拼接视频片段"""
    if not clip_paths:
        return False

    # 创建 concat 列表文件
    list_file = Path(output_path).parent / "concat_list.txt"
    with open(list_file, "w", encoding="utf-8") as f:
        for clip in clip_paths:
            f.write(f"file '{clip}'\n")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(list_file),
        "-c", "copy",
        output_path,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        list_file.unlink(missing_ok=True)
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        return False


def add_audio_track(
    video_path: str,
    audio_path: str,
    output_path: str,
) -> bool:
    """为视频添加音轨"""
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", audio_path,
        "-c:v", "copy",
        "-c:a", "aac",
        "-shortest",
        "-map", "0:v:0",
        "-map", "1:a:0",
        output_path,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        return False


def burn_subtitles(
    video_path: str,
    subtitle_path: str,
    output_path: str,
) -> bool:
    """烧录字幕到视频"""
    # 转义路径中的特殊字符
    escaped_sub = subtitle_path.replace("'", "\\'").replace(":", "\\:")
    filter_str = f"subtitles='{escaped_sub}'"

    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vf", filter_str,
        "-c:a", "copy",
        output_path,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        return False


def generate_srt(storyboard: dict, output_path: str) -> str:
    """根据分镜列表生成 SRT 字幕文件"""
    shots = storyboard.get("shots", [])
    srt_lines = []
    current_time = 0.0

    for idx, shot in enumerate(shots, 1):
        duration = shot.get("duration_sec", 5)
        text_overlay = shot.get("text_overlay", "")
        voiceover = shot.get("voiceover", "")

        # 使用 voiceover 作为字幕（更完整）
        subtitle_text = voiceover if voiceover else text_overlay
        if not subtitle_text:
            current_time += duration
            continue

        start_time = current_time
        end_time = current_time + duration

        # 格式化时间 SRT: HH:MM:SS,mmm
        start_str = _format_srt_time(start_time)
        end_str = _format_srt_time(end_time)

        srt_lines.append(str(idx))
        srt_lines.append(f"{start_str} --> {end_str}")
        srt_lines.append(subtitle_text)
        srt_lines.append("")

        current_time = end_time

    srt_content = "\n".join(srt_lines)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(srt_content)

    return output_path


def _format_srt_time(seconds: float) -> str:
    """格式化秒数为 SRT 时间格式"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def compose_video(
    storyboard: dict,
    images_dir: str,
    output_dir: str,
    audio_path: Optional[str] = None,
    burn_subs: bool = True,
    aspect_ratio: str = "9:16",
) -> dict:
    """
    合成完整视频

    Args:
        storyboard: 分镜列表
        images_dir: 图片目录
        output_dir: 输出目录
        audio_path: TTS 旁白音频路径（可选）
        burn_subs: 是否烧录字幕
        aspect_ratio: 宽高比

    Returns:
        视频合成结果
    """
    if not check_ffmpeg():
        return {
            "success": False,
            "error": "ffmpeg 未安装或不可用",
        }

    width, height = parse_aspect_ratio(aspect_ratio)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    video_id = f"video_{uuid.uuid4().hex[:8]}"
    work_dir = output_dir / f"work_{video_id}"
    work_dir.mkdir(parents=True, exist_ok=True)

    shots = storyboard.get("shots", [])
    clip_paths = []
    zoom_modes = ["in", "out", "pan"]

    print(f"🎬 开始合成视频（{len(shots)} 个分镜）...")

    # 阶段1：为每个分镜生成视频片段
    for idx, shot in enumerate(shots, 1):
        shot_id = shot.get("shot_id", idx)
        duration = shot.get("duration_sec", 5)

        # 查找对应图片
        image_path = None
        images_dir_path = Path(images_dir)
        # 尝试多种命名：shot_{id}, scene_{id}, {id}
        for pattern in [f"shot_{shot_id}.png", f"shot_{shot_id}.jpg",
                        f"scene_{shot_id}.png", f"scene_{shot_id}.jpg",
                        f"{shot_id}.png", f"{shot_id}.jpg",
                        f"shot_{shot_id:02d}.png", f"shot_{shot_id:02d}.jpg"]:
            candidate = images_dir_path / pattern
            if candidate.exists():
                image_path = str(candidate)
                break

        zoom_dir = zoom_modes[idx % len(zoom_modes)]
        clip_path = str(work_dir / f"clip_{idx:03d}.mp4")

        print(f"  [{idx}/{len(shots)}] 生成片段（{duration}s, zoom={zoom_dir}）...")
        success = generate_shot_clip(
            image_path=image_path,
            duration=duration,
            width=width,
            height=height,
            output_path=clip_path,
            zoom_direction=zoom_dir,
        )

        if success and os.path.exists(clip_path):
            clip_paths.append(clip_path)
        else:
            print(f"  ⚠️  片段 {idx} 生成失败")

    if not clip_paths:
        return {"success": False, "error": "没有成功生成任何视频片段"}

    # 阶段2：拼接片段
    print(f"🔗 拼接 {len(clip_paths)} 个片段...")
    concat_path = str(work_dir / "concat.mp4")
    if not concat_clips(clip_paths, concat_path):
        return {"success": False, "error": "视频拼接失败"}

    current_video = concat_path

    # 阶段3：添加音轨
    if audio_path and os.path.exists(audio_path):
        print(f"🎵 添加音轨: {audio_path}")
        audio_path_out = str(work_dir / "with_audio.mp4")
        if add_audio_track(current_video, audio_path, audio_path_out):
            current_video = audio_path_out
        else:
            print("  ⚠️  音轨添加失败，继续无音轨版本")

    # 阶段4：烧录字幕
    if burn_subs:
        print(f"📝 生成并烧录字幕...")
        srt_path = str(work_dir / "subtitles.srt")
        generate_srt(storyboard, srt_path)

        subs_path = str(work_dir / "with_subs.mp4")
        if burn_subtitles(current_video, srt_path, subs_path):
            current_video = subs_path
        else:
            print("  ⚠️  字幕烧录失败，继续无字幕版本")

    # 阶段5：输出最终视频
    final_path = output_dir / f"{video_id}.mp4"
    os.replace(current_video, final_path)

    # 清理工作目录
    try:
        import shutil
        shutil.rmtree(work_dir, ignore_errors=True)
    except Exception:
        pass

    # 获取文件大小
    file_size = os.path.getsize(final_path) / (1024 * 1024)

    # 计算总时长
    total_duration = sum(s.get("duration_sec", 5) for s in shots)

    print(f"✅ 视频合成完成！")
    print(f"   视频 ID: {video_id}")
    print(f"   输出路径: {final_path}")
    print(f"   时长: {total_duration}s")
    print(f"   分辨率: {width}x{height}")
    print(f"   文件大小: {file_size:.2f} MB")

    return {
        "success": True,
        "video_id": video_id,
        "output_path": str(final_path),
        "duration_sec": total_duration,
        "resolution": f"{width}x{height}",
        "fps": 25,
        "shots_count": len(clip_paths),
        "audio_track": audio_path if audio_path and os.path.exists(audio_path) else None,
        "subtitle_track": "burned-in" if burn_subs else None,
        "file_size_mb": round(file_size, 2),
        "generated_at": datetime.now().isoformat(),
    }


def main():
    parser = argparse.ArgumentParser(description="Video Gen Agent - 视频合成")
    parser.add_argument(
        "--storyboard-json",
        required=True,
        help="Storyboard Agent 输出的分镜 JSON 文件路径",
    )
    parser.add_argument(
        "--images-dir",
        required=True,
        help="图片资源目录（包含 shot_1.png, shot_2.png 等）",
    )
    parser.add_argument(
        "--audio",
        help="TTS 旁白音频文件路径（可选）",
    )
    parser.add_argument(
        "--no-subs",
        action="store_true",
        help="不烧录字幕",
    )
    parser.add_argument(
        "--aspect-ratio",
        default="9:16",
        choices=["9:16", "16:9", "1:1", "4:3", "3:4"],
        help="宽高比（默认 9:16 竖屏）",
    )
    parser.add_argument(
        "--output-dir",
        default="/mnt/user-data/workspace/videos",
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

    # 合成视频
    result = compose_video(
        storyboard=storyboard,
        images_dir=args.images_dir,
        output_dir=args.output_dir,
        audio_path=args.audio,
        burn_subs=not args.no_subs,
        aspect_ratio=args.aspect_ratio,
    )

    # 输出结果 JSON
    result_path = Path(args.output_dir) / f"{result.get('video_id', 'video')}_result.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    if result.get("success"):
        print(f"\n📊 结果已保存: {result_path}")
        return 0
    else:
        print(f"\n❌ 合成失败: {result.get('error')}")
        return 1


if __name__ == "__main__":
    exit(main())
