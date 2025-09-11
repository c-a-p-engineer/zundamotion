"""ffprobe を利用したメディア情報取得ヘルパー。"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Dict, Optional, TypedDict

from .ffmpeg_runner import run_ffmpeg_async
from .logger import logger

_media_info_memo: Dict[tuple, "MediaInfo"] = {}
_duration_memo: Dict[tuple, float] = {}


class VideoInfo(TypedDict, total=False):
    """動画ストリームの基本情報。"""

    codec_name: str
    width: int
    height: int
    pix_fmt: str
    r_frame_rate: str
    fps: float


class AudioInfo(TypedDict, total=False):
    """音声ストリームの基本情報。"""

    codec_name: str
    sample_rate: int
    channels: int
    channel_layout: str


class MediaInfo(TypedDict, total=False):
    """動画/音声のメタ情報。"""

    video: Optional[VideoInfo]
    audio: Optional[AudioInfo]


async def get_media_info(file_path: str) -> MediaInfo:
    """動画/音声ファイルのメタ情報を取得する。"""
    try:
        p = Path(file_path)
        st = p.stat()
        key = (str(p.resolve()), int(st.st_mtime), st.st_size)
        if key in _media_info_memo:
            return _media_info_memo[key]
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-of",
            "json",
            file_path,
        ]
        result = await run_ffmpeg_async(cmd)
        info = json.loads(result.stdout)

        media_info: MediaInfo = {"video": None, "audio": None}
        for s in info.get("streams", []):
            if s.get("codec_type") == "video" and media_info["video"] is None:
                r_rate = s.get("r_frame_rate", "0/0")
                try:
                    num, den = map(int, r_rate.split("/"))
                    fps = float(num) / float(den) if den else 0.0
                except Exception:
                    fps = 0.0
                media_info["video"] = {
                    "codec_name": s.get("codec_name"),
                    "width": int(s.get("width", 0)),
                    "height": int(s.get("height", 0)),
                    "pix_fmt": s.get("pix_fmt"),
                    "r_frame_rate": r_rate,
                    "fps": fps,
                }
            elif s.get("codec_type") == "audio" and media_info["audio"] is None:
                media_info["audio"] = {
                    "codec_name": s.get("codec_name"),
                    "sample_rate": int(s.get("sample_rate", 0)) if s.get("sample_rate") else 0,
                    "channels": int(s.get("channels", 0)) if s.get("channels") else 0,
                    "channel_layout": s.get("channel_layout"),
                }
        _media_info_memo[key] = media_info
        return media_info
    except subprocess.CalledProcessError as e:
        logger.error(f"Error running ffprobe for {file_path}: {e.stderr}")
        raise
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.error(f"Error parsing ffprobe output for {file_path}: {e}")
        raise



async def probe_media_params_async(path: Path) -> Dict[str, Any]:
    """ffprobe で幅やFPSなど最小限の情報を取得する。"""
    try:
        media_info = await get_media_info(str(path))
        result: Dict[str, Any] = {}
        video_info = media_info.get("video")
        if video_info:
            result["width"] = video_info.get("width")
            result["height"] = video_info.get("height")
            result["fps"] = video_info.get("fps")
            result["pix_fmt"] = video_info.get("pix_fmt")
            result["vcodec"] = video_info.get("codec_name")
        audio_info = media_info.get("audio")
        if audio_info:
            result["asr"] = audio_info.get("sample_rate")
            result["ach"] = audio_info.get("channels")
            result["acodec"] = audio_info.get("codec_name")
        return result
    except Exception as e:
        logger.error(f"Error probing media params for {path}: {e}")
        return {}
async def get_audio_duration(file_path: str) -> float:
    """音声ファイルの長さ(秒)を返す。"""
    try:
        p = Path(file_path)
        st = p.stat()
        key = ("aud", str(p.resolve()), int(st.st_mtime), st.st_size)
        if key in _duration_memo:
            return _duration_memo[key]
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
        result = await run_ffmpeg_async(cmd)
        info = json.loads(result.stdout)
        duration = float(info["format"]["duration"])
        duration = round(duration, 2)
        _duration_memo[key] = duration
        return duration
    except Exception as e:
        logger.error(f"Failed to get audio duration for {file_path}: {e}")
        raise


async def get_media_duration(file_path: str) -> float:
    """動画/音声ファイルの長さ(秒)を返す。"""
    try:
        p = Path(file_path)
        st = p.stat()
        key = ("med", str(p.resolve()), int(st.st_mtime), st.st_size)
        if key in _duration_memo:
            return _duration_memo[key]
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
        result = await run_ffmpeg_async(cmd)
        info = json.loads(result.stdout)
        duration = float(info["format"]["duration"])
        duration = round(duration, 2)
        _duration_memo[key] = duration
        return duration
    except Exception as e:
        logger.error(f"Failed to get media duration for {file_path}: {e}")
        raise
