"""
视频转场增强 - 专业级转场效果
基于 ffmpeg xfade 滤镜，支持多种转场效果
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

# 添加 observability 路径
_OBS_PATH = Path(__file__).parent.parent.parent.parent / "platform" / "observability"
if str(_OBS_PATH) not in sys.path:
    sys.path.insert(0, str(_OBS_PATH))

from logger import get_logger

logger = get_logger(__name__)


# ffmpeg xfade 转场类型
TRANSITION_TYPES = {
    "fade": "fade",
    "dissolve": "dissolve",
    "wipeleft": "wipeleft",
    "wiperight": "wiperight",
    "wipeup": "wipeup",
    "wipedown": "wipedown",
    "slideleft": "slideleft",
    "slideright": "slideright",
    "slideup": "slideup",
    "slidedown": "slidedown",
    "circlecrop": "circlecrop",
    "rectcrop": "rectcrop",
    "distance": "distance",
    "fadeblack": "fadeblack",
    "fadewhite": "fadewhite",
    "radial": "radial",
    "smoothleft": "smoothleft",
    "smoothright": "smoothright",
    "smoothup": "smoothup",
    "smoothdown": "smoothdown",
    "circleopen": "circleopen",
    "circleclose": "circleclose",
    "vertopen": "vertopen",
    "vertclose": "vertclose",
    "horzopen": "horzopen",
    "horzclose": "horzclose",
    "dissolve": "dissolve",
    "pixelize": "pixelize",
    "diagtl": "diagtl",
    "diagtr": "diagtr",
    "diagbl": "diagbl",
    "diagbr": "diagbr",
    "hlslice": "hlslice",
    "hrslice": "hrslice",
    "vuslice": "vuslice",
    "vdslice": "vdslice",
    "hblur": "hblur",
    "fadegrays": "fadegrays",
    "wipetl": "wipetl",
    "wipetr": "wipetr",
    "wipebl": "wipebl",
    "wipebr": "wipebr",
    "squeezeh": "squeezeh",
    "squeezev": "squeezev",
    "zoomin": "zoomin",
}


# 字幕样式预设
SUBTITLE_STYLES = {
    "default": {
        "fontname": "Microsoft YaHei",
        "fontsize": 48,
        "primary_colour": "&H00FFFFFF",  # 白色
        "outline_colour": "&H00000000",  # 黑色描边
        "outline": 2,
        "shadow": 1,
        "alignment": 2,  # 底部居中
        "margin_v": 80,
    },
    "bold": {
        "fontname": "Microsoft YaHei",
        "fontsize": 56,
        "bold": 1,
        "primary_colour": "&H00FFFFFF",
        "outline_colour": "&H00000000",
        "outline": 3,
        "shadow": 2,
        "alignment": 2,
        "margin_v": 80,
    },
    "modern": {
        "fontname": "Microsoft YaHei",
        "fontsize": 44,
        "primary_colour": "&H00F0F0F0",
        "outline_colour": "&H80000000",
        "outline": 1,
        "shadow": 0,
        "alignment": 2,
        "margin_v": 100,
        "back_colour": "&H80000000",
        "border_style": 4,  # 框选
    },
    "cinematic": {
        "fontname": "Microsoft YaHei",
        "fontsize": 40,
        "primary_colour": "&H00E8E8E8",
        "outline_colour": "&H00000000",
        "outline": 1,
        "shadow": 3,
        "alignment": 2,
        "margin_v": 60,
    },
    "viral": {
        "fontname": "Microsoft YaHei",
        "fontsize": 64,
        "bold": 1,
        "primary_colour": "&H0000FFFF",  # 黄色
        "outline_colour": "&H00000000",
        "outline": 4,
        "shadow": 2,
        "alignment": 2,
        "margin_v": 120,
    },
}


def apply_transitions(
    clip_paths: list,
    output_path: str,
    transition_type: str = "fade",
    transition_duration: float = 0.5,
) -> bool:
    """
    使用 ffmpeg xfade 滤镜应用转场效果

    Args:
        clip_paths: 视频片段路径列表
        output_path: 输出路径
        transition_type: 转场类型（见 TRANSITION_TYPES）
        transition_duration: 转场时长（秒）

    Returns:
        是否成功
    """
    if len(clip_paths) < 2:
        # 单片段直接复制
        if clip_paths:
            import shutil
            shutil.copy(clip_paths[0], output_path)
            return True
        return False

    xfade_type = TRANSITION_TYPES.get(transition_type, "fade")
    logger.info(f"应用转场: type={xfade_type}, duration={transition_duration}s, clips={len(clip_paths)}")

    # 构建 ffmpeg 命令
    cmd = ["ffmpeg", "-y"]

    # 输入文件
    for clip in clip_paths:
        cmd.extend(["-i", clip])

    # 构建 filter_complex
    filter_parts = []
    # 第一个片段直接使用
    filter_parts.append(f"[0:v]setpts=PTS-STARTPTS[v0]")

    # 获取第一个片段时长（用于计算 offset）
    # 这里简化处理：假设每个片段时长固定，实际应探测
    # 使用 concat 方式 + xfade
    prev_label = "v0"
    offset = 0

    for i in range(1, len(clip_paths)):
        # 探测前一个片段时长
        duration = _get_video_duration(clip_paths[i - 1])
        if duration is None:
            duration = 5.0  # 默认

        offset += max(0, duration - transition_duration)

        curr_label = f"v{i}"
        filter_parts.append(f"[{i}:v]setpts=PTS-STARTPTS[{curr_label}]")

        out_label = f"x{i}" if i < len(clip_paths) - 1 else "vout"
        filter_parts.append(
            f"[{prev_label}][{curr_label}]xfade=transition={xfade_type}:"
            f"duration={transition_duration}:offset={offset}[{out_label}]"
        )
        prev_label = out_label

    filter_complex = ";".join(filter_parts)

    cmd.extend([
        "-filter_complex", filter_complex,
        "-map", "[vout]",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-preset", "medium",
        "-crf", "23",
        output_path,
    ])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            logger.error(f"转场应用失败: {result.stderr[-500:]}")
            return False
        logger.info(f"转场应用成功: {output_path}")
        return True
    except subprocess.TimeoutExpired:
        logger.error("转场应用超时")
        return False


def _get_video_duration(video_path: str) -> Optional[float]:
    """获取视频时长"""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            return float(result.stdout.strip())
    except (ValueError, subprocess.TimeoutExpired):
        pass
    return None


def generate_styled_srt(storyboard: dict, output_path: str, style: str = "default") -> str:
    """
    生成带样式的 SRT 字幕文件（使用 ASS 格式以支持更多样式）

    Args:
        storyboard: 分镜列表
        output_path: 输出路径（.ass）
        style: 样式预设名

    Returns:
        输出文件路径
    """
    style_config = SUBTITLE_STYLES.get(style, SUBTITLE_STYLES["default"])
    shots = storyboard.get("shots", [])

    # 构建 ASS 文件头
    ass_header = f"""[Script Info]
Title: Kickart Subtitles
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{style_config.get('fontname', 'Microsoft YaHei')},{style_config.get('fontsize', 48)},{style_config.get('primary_colour', '&H00FFFFFF')},&H000000FF,{style_config.get('outline_colour', '&H00000000')},{style_config.get('back_colour', '&H80000000')},{style_config.get('bold', 0)},0,0,0,100,100,0,0,{style_config.get('border_style', 1)},{style_config.get('outline', 2)},{style_config.get('shadow', 1)},{style_config.get('alignment', 2)},40,40,{style_config.get('margin_v', 80)},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    # 构建字幕事件
    events = []
    current_time = 0.0

    for idx, shot in enumerate(shots, 1):
        duration = shot.get("duration_sec", 5)
        voiceover = shot.get("voiceover", "")
        text_overlay = shot.get("text_overlay", "")

        subtitle_text = voiceover if voiceover else text_overlay
        if not subtitle_text:
            current_time += duration
            continue

        start_time = current_time
        end_time = current_time + duration

        start_str = _format_ass_time(start_time)
        end_str = _format_ass_time(end_time)

        # 转义特殊字符
        subtitle_text = subtitle_text.replace("\\N", " ").replace("\\n", " ").replace("\\h", " ")
        # 换行处理（长文本自动换行）
        if len(subtitle_text) > 20:
            mid = len(subtitle_text) // 2
            # 找最近的空格
            for i in range(mid, min(mid + 5, len(subtitle_text))):
                if subtitle_text[i] == " ":
                    subtitle_text = subtitle_text[:i] + "\\N" + subtitle_text[i+1:]
                    break

        events.append(
            f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{subtitle_text}"
        )

        current_time = end_time

    ass_content = ass_header + "\n".join(events) + "\n"

    # 如果输出路径是 .srt，也生成 srt 版本
    output_path = Path(output_path)
    if output_path.suffix.lower() == ".srt":
        # 生成 SRT
        srt_content = _generate_srt_content(storyboard)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(srt_content)
    else:
        # 生成 ASS
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(ass_content)

    logger.info(f"字幕生成: {output_path} (style={style})")
    return str(output_path)


def _format_ass_time(seconds: float) -> str:
    """格式化为 ASS 时间格式 H:MM:SS.cc"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    centis = int((seconds % 1) * 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


def _generate_srt_content(storyboard: dict) -> str:
    """生成 SRT 格式字幕"""
    shots = storyboard.get("shots", [])
    srt_lines = []
    current_time = 0.0

    for idx, shot in enumerate(shots, 1):
        duration = shot.get("duration_sec", 5)
        subtitle_text = shot.get("voiceover", "") or shot.get("text_overlay", "")
        if not subtitle_text:
            current_time += duration
            continue

        start_time = current_time
        end_time = current_time + duration

        start_str = _format_srt_time(start_time)
        end_str = _format_srt_time(end_time)

        srt_lines.append(str(idx))
        srt_lines.append(f"{start_str} --> {end_str}")
        srt_lines.append(subtitle_text)
        srt_lines.append("")

        current_time = end_time

    return "\n".join(srt_lines)


def _format_srt_time(seconds: float) -> str:
    """格式化为 SRT 时间格式 HH:MM:SS,mmm"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def add_watermark(
    video_path: str,
    watermark_text: str = "Kickart",
    position: str = "bottom-right",
    output_path: str = None,
) -> bool:
    """
    添加文字水印

    Args:
        video_path: 视频路径
        watermark_text: 水印文字
        position: 位置（top-left/top-right/bottom-left/bottom-right/center）
        output_path: 输出路径（None 则覆盖）

    Returns:
        是否成功
    """
    output_path = output_path or video_path
    tmp_path = output_path + ".tmp.mp4"

    # 位置映射
    positions = {
        "top-left": "x=40:y=40",
        "top-right": "x=w-tw-40:y=40",
        "bottom-left": "x=40:y=h-th-40",
        "bottom-right": "x=w-tw-40:y=h-th-40",
        "center": "x=(w-tw)/2:y=(h-th)/2",
    }
    pos = positions.get(position, positions["bottom-right"])

    # drawtext 滤镜
    filter_str = (
        f"drawtext=text='{watermark_text}':"
        f"fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
        f"fontcolor=white@0.6:fontsize=36:"
        f"{pos}:shadowcolor=black:shadowx=2:shadowy=2"
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vf", filter_str,
        "-c:a", "copy",
        "-c:v", "libx264",
        "-preset", "medium",
        tmp_path,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if result.returncode == 0:
            os.replace(tmp_path, output_path)
            logger.info(f"水印添加成功: {watermark_text} @ {position}")
            return True
        else:
            logger.error(f"水印添加失败: {result.stderr[-300:]}")
            return False
    except subprocess.TimeoutExpired:
        logger.error("水印添加超时")
        return False


def add_background_music(
    video_path: str,
    music_path: str,
    output_path: str,
    music_volume: float = 0.15,
    voice_volume: float = 1.0,
) -> bool:
    """
    添加背景音乐（混合音轨）

    Args:
        video_path: 视频路径
        music_path: 背景音乐路径
        output_path: 输出路径
        music_volume: 音乐音量（0.0-1.0）
        voice_volume: 旁白音量

    Returns:
        是否成功
    """
    # 使用 amix 混合音轨
    filter_str = (
        f"[1:a]volume={music_volume},aloop=loop=-1:size=2e9[bgm];"
        f"[0:a]volume={voice_volume}[voice];"
        f"[bgm][voice]amix=inputs=2:duration=first:dropout_transition=0[aout]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", music_path,
        "-filter_complex", filter_str,
        "-map", "0:v",
        "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac",
        "-shortest",
        output_path,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if result.returncode == 0:
            logger.info(f"背景音乐添加成功: volume={music_volume}")
            return True
        else:
            logger.error(f"背景音乐添加失败: {result.stderr[-300:]}")
            return False
    except subprocess.TimeoutExpired:
        return False
