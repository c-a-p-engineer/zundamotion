import json
import re
import subprocess
from typing import Optional


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
    except (subprocess.CalledProcessError, FileNotFoundError):
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
    except (subprocess.CalledProcessError, FileNotFoundError):
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
        probe_data = json.loads(result.stdout)
        duration = float(probe_data["format"]["duration"])
        return round(duration, 2)
    except subprocess.CalledProcessError as e:
        print(f"Error running ffprobe for {file_path}: {e}")
        print(e.stderr)
        raise
    except (json.JSONDecodeError, KeyError) as e:
        print(f"Error parsing ffprobe output for {file_path}: {e}")
        raise
