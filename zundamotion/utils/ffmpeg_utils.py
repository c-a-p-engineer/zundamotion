import json
import re
import subprocess
from typing import Optional

from zundamotion.utils.logger import logger


def get_ffmpeg_version(ffmpeg_path: str = "ffmpeg") -> Optional[str]:
    """
    Gets the FFmpeg version string.
    """
    try:
        cmd = [ffmpeg_path, "-version"]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        match = re.search(r"ffmpeg version (\S+)", result.stdout)
        if match:
            return match.group(1)
        return None
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        logger.error(f"Error getting FFmpeg version: {e}")
        return None


def get_hardware_encoder(ffmpeg_path: str = "ffmpeg") -> Optional[str]:
    """
    Detects available hardware encoders (NVENC, VAAPI, VideoToolbox).
    Returns the name of the first detected encoder or None.
    """
    try:
        cmd = [ffmpeg_path, "-encoders"]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        output = result.stdout

        if "h264_nvenc" in output or "hevc_nvenc" in output:
            return "nvenc"
        if "h264_vaapi" in output or "hevc_vaapi" in output:
            return "vaapi"
        if "h264_videotoolbox" in output or "hevc_videotoolbox" in output:
            return "videotoolbox"
        # Add more encoders as needed

        return None
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        logger.error(f"Error detecting hardware encoder: {e}")
        return None


def get_audio_duration(file_path: str) -> float:
    """
    Get the duration of an audio file using ffprobe.

    Args:
        file_path (str): Path to the audio file.

    Returns:
        float: Duration in seconds.
    """
    try:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            file_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)

        logger.debug(f"ffprobe stdout for {file_path}: {result.stdout}")

        probe_data = json.loads(result.stdout)

        logger.debug(f"Type of probe_data: {type(probe_data)}, Value: {probe_data}")

        duration = float(probe_data["format"]["duration"])
        return round(duration, 2)
    except subprocess.CalledProcessError as e:
        logger.error(f"Error running ffprobe for {file_path}: {e}")
        logger.error(e.stderr)
        raise
    except (json.JSONDecodeError, KeyError) as e:
        logger.error(f"Error parsing ffprobe output for {file_path}: {e}")
        raise


def add_bgm_to_video(
    video_path: str,
    bgm_path: str,
    output_path: str,
    bgm_volume: float = 0.5,
    bgm_start_time: float = 0.0,
    fade_in_duration: float = 0.0,
    fade_out_duration: float = 0.0,
    video_duration: Optional[float] = None,
):
    """
    Adds background music to a video file with fade-in/out and volume control.

    Args:
        video_path (str): Path to the input video file.
        bgm_path (str): Path to the background music file.
        output_path (str): Path for the output video file with BGM.
        bgm_volume (float): Volume of the BGM (0.0 to 1.0).
        bgm_start_time (float): Start time of the BGM in the video (seconds).
        fade_in_duration (float): Duration of BGM fade-in (seconds).
        fade_out_duration (float): Duration of BGM fade-out (seconds).
        video_duration (Optional[float]): Duration of the video in seconds.
                                          If None, it will be detected automatically.
    """
    if video_duration is None:
        video_duration = get_audio_duration(
            video_path
        )  # Assuming video duration can be obtained like audio

    bgm_duration = get_audio_duration(bgm_path)

    # Calculate effective BGM end time
    effective_bgm_end_time = min(video_duration, bgm_start_time + bgm_duration)

    # FFmpeg command construction
    cmd = [
        "ffmpeg",
        "-i",
        video_path,
        "-i",
        bgm_path,
        "-filter_complex",
    ]

    # Audio filter for BGM
    audio_filters = []
    audio_filters.append(f"volume={bgm_volume}")

    if fade_in_duration > 0:
        audio_filters.append(f"afade=t=in:st=0:d={fade_in_duration}")

    if fade_out_duration > 0:
        # フェードアウトはBGMファイルの終了位置から逆算
        fade_out_start_relative_to_bgm = bgm_duration - fade_out_duration
        if fade_out_start_relative_to_bgm < 0:
            fade_out_start_relative_to_bgm = 0  # BGMの長さよりフェードアウトが長い場合
        audio_filters.append(
            f"afade=t=out:st={fade_out_start_relative_to_bgm}:d={fade_out_duration}"
        )

    # Apply audio filters to BGM stream
    bgm_filter_str = f"[1:a]{','.join(audio_filters)}[bgm_filtered]"

    # Delay the filtered BGM
    delayed_bgm_str = (
        f"[bgm_filtered]adelay={int(bgm_start_time * 1000)}:all=1[delayed_bgm]"
    )

    # Mix original video audio with delayed BGM
    filter_complex_str = f"{bgm_filter_str};{delayed_bgm_str};[0:a][delayed_bgm]amix=inputs=2:duration=shortest[aout]"

    cmd.append(filter_complex_str)

    cmd.extend(
        [
            "-map",
            "0:v",  # Map video stream from input 0 (original video)
            "-map",
            "[aout]",  # Map the mixed audio stream
            "-c:v",
            "copy",  # Copy video codec
            "-c:a",
            "aac",  # Encode audio to AAC
            "-b:a",
            "192k",  # Audio bitrate
            "-shortest",  # Finish encoding when the shortest input stream ends (video)
            output_path,
        ]
    )

    try:
        # FFmpegの出力を捕捉し、logger.debugでログに記録
        process = subprocess.run(
            cmd, check=True, capture_output=True, text=True, encoding="utf-8"
        )
        logger.debug(f"FFmpeg stdout:\n{process.stdout}")
        logger.debug(f"FFmpeg stderr:\n{process.stderr}")
        logger.info(
            f"Successfully added BGM to {video_path} and saved to {output_path}"
        )
    except subprocess.CalledProcessError as e:
        logger.error(f"Error adding BGM to video: {e}")
        logger.error(f"FFmpeg stdout:\n{e.stdout}")
        logger.error(f"FFmpeg stderr:\n{e.stderr}")
        raise


def calculate_overlay_position(
    bg_width_expr: str,
    bg_height_expr: str,
    fg_width_expr: str,
    fg_height_expr: str,
    anchor: str,
    offset_x: str,
    offset_y: str,
) -> tuple[str, str]:
    """
    Calculates FFmpeg overlay x, y expressions based on anchor point and offsets.

    Args:
        bg_width_expr (str): FFmpeg expression for background width (e.g., 'W').
        bg_height_expr (str): FFmpeg expression for background height (e.g., 'H').
        fg_width_expr (str): FFmpeg expression for foreground width (e.g., 'w').
        fg_height_expr (str): FFmpeg expression for foreground height (e.g., 'h').
        anchor (str): Anchor point (e.g., 'bottom_center').
        offset_x (str): X offset from the anchor point.
        offset_y (str): Y offset from the anchor point.

    Returns:
        tuple[str, str]: (x_expression, y_expression) for FFmpeg overlay filter.
    """
    x_base = "0"
    y_base = "0"

    if anchor == "top_left":
        x_base = "0"
        y_base = "0"
    elif anchor == "top_center":
        x_base = f"({bg_width_expr}-{fg_width_expr})/2"
        y_base = "0"
    elif anchor == "top_right":
        x_base = f"{bg_width_expr}-{fg_width_expr}"
        y_base = "0"
    elif anchor == "middle_left":
        x_base = "0"
        y_base = f"({bg_height_expr}-{fg_height_expr})/2"
    elif anchor == "middle_center":
        x_base = f"({bg_width_expr}-{fg_width_expr})/2"
        y_base = f"({bg_height_expr}-{fg_height_expr})/2"
    elif anchor == "middle_right":
        x_base = f"{bg_width_expr}-{fg_width_expr}"
        y_base = f"({bg_height_expr}-{fg_height_expr})/2"
    elif anchor == "bottom_left":
        x_base = "0"
        y_base = f"{bg_height_expr}-{fg_height_expr}"
    elif anchor == "bottom_center":
        x_base = f"({bg_width_expr}-{fg_width_expr})/2"
        y_base = f"{bg_height_expr}-{fg_height_expr}"
    elif anchor == "bottom_right":
        x_base = f"{bg_width_expr}-{fg_width_expr}"
        y_base = f"{bg_height_expr}-{fg_height_expr}"
    else:
        logger.warning(f"Unknown anchor point: {anchor}. Defaulting to top_left.")
        x_base = "0"
        y_base = "0"

    # Add offsets
    x_expr = f"{x_base}+{offset_x}" if offset_x and offset_x != "0" else x_base
    y_expr = f"{y_base}+{offset_y}" if offset_y and offset_y != "0" else y_base

    # Handle negative offsets (e.g., y-50 instead of y+-50)
    x_expr = x_expr.replace("+-", "-")
    y_expr = y_expr.replace("+-", "-")

    return x_expr, y_expr
