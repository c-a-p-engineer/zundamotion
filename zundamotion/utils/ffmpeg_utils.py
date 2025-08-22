import json
import re
import subprocess
from typing import List, Optional, Tuple

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


def get_hardware_accelerator(ffmpeg_path: str = "ffmpeg") -> Optional[str]:
    """
    Detects available hardware accelerators using 'ffmpeg -hwaccels'.
    Returns the name of the first detected accelerator or None.
    """
    try:
        cmd = [ffmpeg_path, "-hwaccels"]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        output = result.stdout.lower()

        if "cuda" in output or "nvenc" in output:
            return "cuda"
        if "qsv" in output:
            return "qsv"
        if "vaapi" in output:
            return "vaapi"
        if "videotoolbox" in output:
            return "videotoolbox"
        if "amf" in output:
            return "amf"
        # Add more accelerators as needed

        return None
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        logger.error(f"Error detecting hardware accelerators: {e}")
        return None


def get_video_encoder_options(
    ffmpeg_path: str = "ffmpeg",
) -> Tuple[List[str], List[str], List[str]]:
    """
    Determines the best available H.264 and HEVC video encoder options,
    prioritizing hardware encoders if available, otherwise falling back to CPU.

    Returns:
        Tuple[List[str], List[str], List[str]]: A tuple containing three lists:
                                     - HW accel input options (e.g., ['-hwaccel', 'cuda'])
                                     - H.264 encoder options (e.g., ['-c:v', 'h264_nvenc'])
                                     - HEVC encoder options (e.g., ['-c:v', 'hevc_nvenc'])
    """
    hw_accel = get_hardware_accelerator(ffmpeg_path)
    hw_accel_options: List[str] = []
    h264_encoder_options = ["-c:v", "libx264", "-preset", "fast", "-crf", "23"]
    hevc_encoder_options = [
        "-c:v",
        "libx265",
        "-preset",
        "fast",
        "-crf",
        "28",
    ]  # HEVC default CRF is higher

    if hw_accel:
        logger.info(
            f"Detected hardware accelerator: {hw_accel}. Attempting to use GPU encoding."
        )
        if hw_accel == "cuda":
            # NVIDIA NVENC
            h264_encoder_options = [
                "-c:v",
                "h264_nvenc",
                "-preset",
                "fast",
                "-cq",
                "23",
            ]
            hevc_encoder_options = [
                "-c:v",
                "hevc_nvenc",
                "-preset",
                "fast",
                "-cq",
                "28",
            ]
            hw_accel_options = ["-hwaccel", "cuda"]
        elif hw_accel == "qsv":
            # Intel QSV
            h264_encoder_options = [
                "-c:v",
                "h264_qsv",
                "-preset",
                "veryfast",
                "-q",
                "23",
            ]
            hevc_encoder_options = [
                "-c:v",
                "hevc_qsv",
                "-preset",
                "veryfast",
                "-q",
                "28",
            ]
            hw_accel_options = ["-hwaccel", "qsv", "-hwaccel_output_format", "qsv"]
        elif hw_accel == "vaapi":
            # Generic VAAPI (Intel, AMD)
            h264_encoder_options = ["-c:v", "h264_vaapi", "-qp", "23"]
            hevc_encoder_options = ["-c:v", "hevc_vaapi", "-qp", "28"]
            # VAAPI requires a device, typically /dev/dri/renderD128
            # This might need to be configured externally or detected more robustly
            hw_accel_options = [
                "-hwaccel",
                "vaapi",
                "-hwaccel_output_format",
                "vaapi",
                "-vaapi_device",
                "/dev/dri/renderD128",
            ]
        elif hw_accel == "videotoolbox":
            # Apple VideoToolbox
            h264_encoder_options = [
                "-c:v",
                "h264_videotoolbox",
                "-b:v",
                "5M",
            ]  # VideoToolbox uses bitrate, not CRF
            hevc_encoder_options = ["-c:v", "hevc_videotoolbox", "-b:v", "5M"]
        elif hw_accel == "amf":
            # AMD AMF (Windows only, typically)
            h264_encoder_options = [
                "-c:v",
                "h264_amf",
                "-quality",
                "balanced",
                "-qp_i",
                "23",
                "-qp_p",
                "23",
            ]
            hevc_encoder_options = [
                "-c:v",
                "hevc_amf",
                "-quality",
                "balanced",
                "-qp_i",
                "28",
                "-qp_p",
                "28",
            ]
            # AMF might not need explicit -hwaccel if it's the encoder itself
    else:
        logger.info(
            "No hardware accelerator detected. Falling back to CPU encoding (libx264/libx265)."
        )

    return hw_accel_options, h264_encoder_options, hevc_encoder_options


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


def get_media_info(file_path: str) -> dict:
    """
    Get media information using ffprobe.

    Args:
        file_path (str): Path to the media file.

    Returns:
        dict: A dictionary containing media information.
    """
    try:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-of",
            "json",
            file_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        info = json.loads(result.stdout)

        video_stream = next(
            (s for s in info.get("streams", []) if s.get("codec_type") == "video"), None
        )
        audio_stream = next(
            (s for s in info.get("streams", []) if s.get("codec_type") == "audio"), None
        )

        media_info = {}
        if video_stream:
            media_info["video"] = {
                "width": int(video_stream.get("width", 0)),
                "height": int(video_stream.get("height", 0)),
                "pix_fmt": video_stream.get("pix_fmt"),
                "r_frame_rate": video_stream.get("r_frame_rate", "0/0"),
            }
            # Convert frame rate to a float
            num, den = map(int, media_info["video"]["r_frame_rate"].split("/"))
            media_info["video"]["fps"] = float(num) / float(den) if den != 0 else 0.0

        if audio_stream:
            media_info["audio"] = {
                "sample_rate": int(audio_stream.get("sample_rate", 0)),
                "channels": int(audio_stream.get("channels", 0)),
                "channel_layout": audio_stream.get("channel_layout"),
            }

        return media_info

    except subprocess.CalledProcessError as e:
        logger.error(f"Error running ffprobe for {file_path}: {e.stderr}")
        raise
    except (json.JSONDecodeError, KeyError) as e:
        logger.error(f"Error parsing ffprobe output for {file_path}: {e}")
        raise


def normalize_video(
    input_path: str, output_path: str, target_fps: int = 30, target_ar: int = 48000
):
    """
    Normalizes a video to a standard format (30fps, 48kHz audio) with timestamp correction.

    Args:
        input_path (str): Path to the input video file.
        output_path (str): Path to save the normalized video file.
        target_fps (int): Target frames per second.
        target_ar (int): Target audio sample rate.
    """
    video_filter = f"fps={target_fps},setpts=PTS-STARTPTS"
    audio_filter = f"aresample={target_ar},asetpts=PTS-STARTPTS"

    hw_accel_options, h264_encoder_options, _ = get_video_encoder_options()

    cmd = [
        "ffmpeg",
        "-y",
    ]
    cmd.extend(hw_accel_options)
    cmd.extend(
        [
            "-i",
            input_path,
            "-vf",
            video_filter,
            "-af",
            audio_filter,
        ]
    )
    cmd.extend(h264_encoder_options)  # Use detected H.264 encoder options
    cmd.extend(
        [
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            output_path,
        ]
    )
    try:
        process = subprocess.run(
            cmd, check=True, capture_output=True, text=True, encoding="utf-8"
        )
        logger.debug(f"FFmpeg stdout:\n{process.stdout}")
        logger.debug(f"FFmpeg stderr:\n{process.stderr}")
        logger.info(f"Successfully normalized {input_path} to {output_path}")
    except subprocess.CalledProcessError as e:
        logger.error(f"Error normalizing video {input_path}: {e}")
        logger.error(f"FFmpeg stdout:\n{e.stdout}")
        logger.error(f"FFmpeg stderr:\n{e.stderr}")
        raise


def create_silent_audio(
    output_path: str, duration: float, sample_rate: int = 44100, channels: int = 2
):
    """
    Creates a silent audio file of a specified duration.

    Args:
        output_path (str): Path to save the silent audio file.
        duration (float): Duration of the silent audio in seconds.
        sample_rate (int): Audio sample rate (Hz).
        channels (int): Number of audio channels.
    """
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"anullsrc=r={sample_rate}:cl={channels}",
        "-t",
        str(duration),
        "-c:a",
        "pcm_s16le",  # Use uncompressed PCM for silent audio
        output_path,
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        logger.debug(
            f"Created silent audio file: {output_path} with duration {duration}s"
        )
    except subprocess.CalledProcessError as e:
        logger.error(f"Error creating silent audio file {output_path}: {e}")
        logger.error(f"STDOUT: {e.stdout}")
        logger.error(f"STDERR: {e.stderr}")
        raise


def has_audio_stream(file_path: str) -> bool:
    """
    Checks if a video file has an audio stream using ffprobe.

    Args:
        file_path (str): Path to the video file.

    Returns:
        bool: True if an audio stream exists, False otherwise.
    """
    try:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "json",
            file_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        probe_data = json.loads(result.stdout)
        return len(probe_data.get("streams", [])) > 0
    except subprocess.CalledProcessError as e:
        logger.error(
            f"Error running ffprobe to check audio stream for {file_path}: {e}"
        )
        logger.error(e.stderr)
        return False
    except (json.JSONDecodeError, KeyError) as e:
        logger.error(f"Error parsing ffprobe output for {file_path}: {e}")
        return False


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
    If the input video has no audio stream, the BGM will be added as the primary audio.

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

    # Determine if the input video has an audio stream
    video_has_audio = has_audio_stream(video_path)

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

    if video_has_audio:
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
    else:
        # If no audio stream in video, just add BGM as the primary audio
        # The [aout] label should be the output of the adelay filter directly.
        filter_complex_str = f"{bgm_filter_str};{delayed_bgm_str}"
        cmd.append(filter_complex_str)
        cmd.extend(
            [
                "-map",
                "0:v",  # Map video stream from input 0 (original video)
                "-map",
                "[delayed_bgm]",  # Map the BGM as the audio stream (output of adelay)
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


def apply_transition(
    input_video1_path: str,
    input_video2_path: str,
    output_path: str,
    transition_type: str,
    duration: float,
    offset: float,
):
    """
    映像は xfade、音声は acrossfade で正しくクロスフェードさせる。
    """
    import logging
    import subprocess

    logger = logging.getLogger(__name__)

    has_audio1 = has_audio_stream(input_video1_path)
    has_audio2 = has_audio_stream(input_video2_path)

    hw_accel_options, h264_encoder_options, _ = get_video_encoder_options()

    cmd = ["ffmpeg", "-y"]
    cmd.extend(hw_accel_options)
    cmd.extend(
        [
            "-i",
            input_video1_path,
            "-i",
            input_video2_path,
        ]
    )

    # 映像は従来どおり
    vf = f"[0:v][1:v]xfade=transition={transition_type}:duration={duration}:offset={offset}[v]"

    filter_parts = [vf]

    # 音声：両方ある→ acrossfade、どちらかのみ→それ用の処理
    if has_audio1 and has_audio2:
        # 形式を統一してから acrossfade
        af = (
            "[0:a]aresample=async=1:first_pts=0,"
            "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[a0];"
            "[1:a]aresample=async=1:first_pts=0,"
            "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[a1];"
            f"[a0][a1]acrossfade=d={duration}:c1=tri:c2=tri[a]"
        )
        filter_parts.append(af)
        cmd += ["-filter_complex", ";".join(filter_parts), "-map", "[v]", "-map", "[a]"]

    elif has_audio1:
        # 1本目だけ音声 → 映像のトランジションに合わせてフェードアウト
        af = (
            "[0:a]aresample=async=1:first_pts=0,"
            "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
            f"afade=t=out:st={offset}:d={duration}[a]"
        )
        filter_parts.append(af)
        cmd += ["-filter_complex", ";".join(filter_parts), "-map", "[v]", "-map", "[a]"]

    elif has_audio2:
        # 2本目だけ音声 → offset だけ無音で遅らせてからフェードイン
        delay_ms = int(offset * 1000)
        af = (
            "[1:a]aresample=async=1:first_pts=0,"
            "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
            f"adelay={delay_ms}|{delay_ms},afade=t=in:st=0:d={duration}[a]"
        )
        filter_parts.append(af)
        cmd += ["-filter_complex", ";".join(filter_parts), "-map", "[v]", "-map", "[a]"]
    else:
        # 音声なし
        cmd += ["-filter_complex", vf, "-map", "[v]"]

    # エンコード設定
    cmd.extend(h264_encoder_options)
    cmd.extend(
        [
            "-pix_fmt",
            "yuv420p",  # X(Twitter)互換性のために追加
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            # "-shortest",  # 必要なら出力を最短ストリーム長に合わせる
            output_path,
        ]
    )

    try:
        process = subprocess.run(
            cmd, check=True, capture_output=True, text=True, encoding="utf-8"
        )
        logger.debug("FFmpeg stdout:\n%s", process.stdout)
        logger.debug("FFmpeg stderr:\n%s", process.stderr)
        logger.info(
            "Applied '%s' transition with proper audio crossfade: %s + %s -> %s",
            transition_type,
            input_video1_path,
            input_video2_path,
            output_path,
        )
    except subprocess.CalledProcessError as e:
        logger.error("Error applying transition: %s", e)
        logger.error("FFmpeg stdout:\n%s", e.stdout)
        logger.error("FFmpeg stderr:\n%s", e.stderr)
        raise


def calculate_overlay_position(
    bg_width_expr: str,
    bg_height_expr: str,
    fg_width_expr: str,
    fg_height_expr: str,
    anchor: str,
    offset_x: str = "0",
    offset_y: str = "0",
) -> Tuple[str, str]:
    """
    Calculates the x and y expressions for FFmpeg's overlay filter based on anchor and offset.

    Args:
        bg_width_expr (str): FFmpeg expression for background width (e.g., "W").
        bg_height_expr (str): FFmpeg expression for background height (e.g., "H").
        fg_width_expr (str): FFmpeg expression for foreground width (e.g., "w").
        fg_height_expr (str): FFmpeg expression for foreground height (e.g., "h").
        anchor (str): Anchor point (e.g., "top_left", "bottom_center").
        offset_x (str): X-axis offset.
        offset_y (str): Y-axis offset.

    Returns:
        Tuple[str, str]: A tuple containing the x and y expressions for the overlay filter.
    """
    x_expr = ""
    y_expr = ""

    if anchor == "top_left":
        x_expr = "0"
        y_expr = "0"
    elif anchor == "top_center":
        x_expr = f"({bg_width_expr}-{fg_width_expr})/2"
        y_expr = "0"
    elif anchor == "top_right":
        x_expr = f"{bg_width_expr}-{fg_width_expr}"
        y_expr = "0"
    elif anchor == "middle_left":
        x_expr = "0"
        y_expr = f"({bg_height_expr}-{fg_height_expr})/2"
    elif anchor == "middle_center":
        x_expr = f"({bg_width_expr}-{fg_width_expr})/2"
        y_expr = f"({bg_height_expr}-{fg_height_expr})/2"
    elif anchor == "middle_right":
        x_expr = f"{bg_width_expr}-{fg_width_expr}"
        y_expr = f"({bg_height_expr}-{fg_height_expr})/2"
    elif anchor == "bottom_left":
        x_expr = "0"
        y_expr = f"{bg_height_expr}-{fg_height_expr}"
    elif anchor == "bottom_center":
        x_expr = f"({bg_width_expr}-{fg_width_expr})/2"
        y_expr = f"{bg_height_expr}-{fg_height_expr}"
    elif anchor == "bottom_right":
        x_expr = f"{bg_width_expr}-{fg_width_expr}"
        y_expr = f"{bg_height_expr}-{fg_height_expr}"
    else:
        # Default to top_left if anchor is unknown
        x_expr = "0"
        y_expr = "0"
        logger.warning(f"Unknown anchor point: {anchor}. Defaulting to top_left.")

    # Apply offsets
    if offset_x and offset_x != "0":
        if offset_x.startswith("-"):
            x_expr = f"{x_expr}{offset_x}"
        else:
            x_expr = f"{x_expr}+{offset_x}"
    if offset_y and offset_y != "0":
        if offset_y.startswith("-"):
            y_expr = f"{y_expr}{offset_y}"
        else:
            y_expr = f"{y_expr}+{offset_y}"

    return x_expr, y_expr


def mix_audio_tracks(
    audio_tracks: List[Tuple[str, float, float]],
    output_path: str,
    total_duration: float,
):
    """
    Mixes multiple audio tracks using FFmpeg.

    Args:
        audio_tracks (List[Tuple[str, float, float]]): A list of tuples, where each tuple
            contains the path to the audio file, the start time in seconds, and the volume.
        output_path (str): The path to the output audio file.
        total_duration (float): The total duration of the mixed audio.
    """
    try:
        # Build the FFmpeg command
        cmd = ["ffmpeg", "-y"]  # -y: Overwrite output file if it exists

        # Add input files
        for i, track in enumerate(audio_tracks):
            cmd.extend(["-i", track[0]])

        # Create the filter complex string
        filter_complex = ""
        amix_inputs = len(audio_tracks)
        for i, track in enumerate(audio_tracks):
            track_path, start_time, volume = track
            # Apply volume and delay to each track
            filter_complex += (
                f"[{i}:a]volume={volume},adelay={int(start_time * 1000)}:all=1[a{i}];"
            )

        # Mix all tracks
        mix_string = "".join([f"[a{i}]" for i in range(amix_inputs)])
        filter_complex += (
            f"{mix_string}amix=inputs={amix_inputs}:dropout_transition=0[aout]"
        )

        # Add the filter complex to the command
        cmd.extend(["-filter_complex", filter_complex])

        # Map the output audio stream
        cmd.extend(["-map", "[aout]"])

        # Set the output format and path, and explicitly set total duration
        cmd.extend(
            [
                "-acodec",
                "libmp3lame",
                "-ab",
                "192k",
                "-t",
                str(total_duration),
                output_path,
            ]
        )

        logger.debug(f"FFmpeg command: {' '.join(cmd)}")

        # Execute the command
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=True
        )  # Removed encoding="utf-8"
        logger.debug(f"FFmpeg stdout:\n{result.stdout}")
        logger.debug(f"FFmpeg stderr:\n{result.stderr}")
        logger.info(f"Successfully mixed audio tracks to {output_path}")

    except subprocess.CalledProcessError as e:
        logger.error(f"Error mixing audio tracks: {e}")
        logger.error(f"FFmpeg stdout:\n{e.stdout}")
        logger.error(f"FFmpeg stderr:\n{e.stderr}")
        raise
