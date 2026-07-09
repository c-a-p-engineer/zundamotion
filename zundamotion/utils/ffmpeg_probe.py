"""ffprobe を利用したメディア情報取得ヘルパー。"""

from __future__ import annotations

import asyncio
import inspect
import json
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional, TypedDict

from .ffmpeg_runner import run_ffmpeg_async
from .logger import logger

_media_info_memo: Dict[tuple, "MediaInfo"] = {}
_media_info_inflight: Dict[tuple, "asyncio.Task[MediaInfo]"] = {}
_duration_memo: Dict[tuple, float] = {}
_duration_inflight: Dict[tuple, "asyncio.Task[float]"] = {}
_image_info_memo: Dict[tuple, "ImageInfo"] = {}


def _resolve_probe_caller(caller: Optional[str]) -> str:
    if caller:
        return str(caller)
    for frame in inspect.stack()[2:]:
        module = inspect.getmodule(frame.frame)
        module_name = getattr(module, "__name__", "")
        if module_name.endswith(".ffmpeg_probe"):
            continue
        return str(frame.function)
    return "unknown"


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


class ImageInfo(TypedDict, total=False):
    """画像ファイルの基本情報。"""

    width: int
    height: int
    mode: str
    format: str


class MediaInfo(TypedDict, total=False):
    """動画/音声のメタ情報。"""

    video: Optional[VideoInfo]
    audio: Optional[AudioInfo]


class AssetMetadata(TypedDict, total=False):
    """素材メタデータの共通取得結果。"""

    path: str
    kind: str
    image: Optional[ImageInfo]
    video: Optional[VideoInfo]
    audio: Optional[AudioInfo]
    duration: Optional[float]


def _stat_key(path: Path) -> tuple[str, int, int]:
    st = path.stat()
    return (str(path.resolve()), int(st.st_mtime), st.st_size)


def clear_probe_caches() -> None:
    """同一プロセス内の ffprobe / 画像メタデータメモをクリアする。"""
    _media_info_memo.clear()
    _media_info_inflight.clear()
    _duration_memo.clear()
    _duration_inflight.clear()
    _image_info_memo.clear()


def _is_image_path(path: Path) -> bool:
    return path.suffix.lower() in {
        ".png",
        ".jpg",
        ".jpeg",
        ".bmp",
        ".webp",
        ".gif",
        ".tif",
        ".tiff",
    }


def get_image_info(file_path: str) -> ImageInfo:
    """画像サイズを Pillow で取得し、mtime/size キーでメモ化する。"""
    from PIL import Image

    p = Path(file_path)
    key = _stat_key(p)
    if key in _image_info_memo:
        return _image_info_memo[key]

    with Image.open(p) as image:
        info: ImageInfo = {
            "width": int(image.width),
            "height": int(image.height),
            "mode": str(image.mode),
            "format": str(image.format or ""),
        }
    _image_info_memo[key] = info
    return info


async def probe_asset(
    file_path: str,
    *,
    cache: bool = True,
    caller: Optional[str] = None,
) -> AssetMetadata:
    """素材の画像/動画/音声メタデータを共通形式で取得する。

    ``cache=False`` は同一プロセス内メモを一度消してから取得する。
    永続 cache は ``CacheManager`` 側で管理する。
    """
    if not cache:
        clear_probe_caches()

    p = Path(file_path)
    result: AssetMetadata = {"path": str(p), "image": None, "video": None, "audio": None}
    if _is_image_path(p):
        result["kind"] = "image"
        result["image"] = get_image_info(file_path)
        return result

    result["kind"] = "media"
    media_info = await get_media_info(file_path, caller=caller or "probe_asset")
    result["video"] = media_info.get("video")
    result["audio"] = media_info.get("audio")
    result["duration"] = await get_media_duration(file_path, caller=caller or "probe_asset")
    return result


async def get_media_info(file_path: str, caller: Optional[str] = None) -> MediaInfo:
    """動画/音声ファイルのメタ情報を取得する。"""
    try:
        resolved_caller = _resolve_probe_caller(caller)
        p = Path(file_path)
        key = _stat_key(p)
        if key in _media_info_memo:
            return _media_info_memo[key]
        existing = _media_info_inflight.get(key)
        if existing is not None:
            return await existing

        async def _probe() -> MediaInfo:
            cmd = [
                "ffprobe",
                "-v",
                "error",
                "-show_streams",
                "-of",
                "json",
                file_path,
            ]
            result = await run_ffmpeg_async(
                cmd,
                context={
                    "phase": "Probe",
                    "operation": "media_info",
                    "caller": resolved_caller,
                    "path": file_path,
                },
            )
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

        task = asyncio.create_task(_probe())
        _media_info_inflight[key] = task
        try:
            return await task
        finally:
            if _media_info_inflight.get(key) is task:
                _media_info_inflight.pop(key, None)
    except subprocess.CalledProcessError as e:
        logger.error(f"Error running ffprobe for {file_path}: {e.stderr}")
        raise
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.error(f"Error parsing ffprobe output for {file_path}: {e}")
        raise



async def probe_media_params_async(path: Path) -> Dict[str, Any]:
    """ffprobe で幅やFPSなど最小限の情報を取得する。"""
    try:
        media_info = await get_media_info(str(path), caller="probe_media_params_async")
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
async def get_audio_duration(file_path: str, caller: Optional[str] = None) -> float:
    """音声ファイルの長さ(秒)を返す。"""
    try:
        resolved_caller = _resolve_probe_caller(caller)
        p = Path(file_path)
        key = ("aud", *_stat_key(p))
        if key in _duration_memo:
            return _duration_memo[key]
        existing = _duration_inflight.get(key)
        if existing is not None:
            return await existing

        async def _probe() -> float:
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
            result = await run_ffmpeg_async(
                cmd,
                context={
                    "phase": "Probe",
                    "operation": "audio_duration",
                    "caller": resolved_caller,
                    "path": file_path,
                },
            )
            info = json.loads(result.stdout)
            duration = round(float(info["format"]["duration"]), 2)
            _duration_memo[key] = duration
            return duration

        task = asyncio.create_task(_probe())
        _duration_inflight[key] = task
        try:
            return await task
        finally:
            if _duration_inflight.get(key) is task:
                _duration_inflight.pop(key, None)
    except Exception as e:
        logger.error(f"Failed to get audio duration for {file_path}: {e}")
        raise


async def get_media_duration(file_path: str, caller: Optional[str] = None) -> float:
    """動画/音声ファイルの長さ(秒)を返す。"""
    try:
        resolved_caller = _resolve_probe_caller(caller)
        p = Path(file_path)
        key = ("med", *_stat_key(p))
        if key in _duration_memo:
            return _duration_memo[key]
        existing = _duration_inflight.get(key)
        if existing is not None:
            return await existing

        async def _probe() -> float:
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
            result = await run_ffmpeg_async(
                cmd,
                context={
                    "phase": "Probe",
                    "operation": "media_duration",
                    "caller": resolved_caller,
                    "path": file_path,
                },
            )
            info = json.loads(result.stdout)
            duration = round(float(info["format"]["duration"]), 2)
            _duration_memo[key] = duration
            return duration

        task = asyncio.create_task(_probe())
        _duration_inflight[key] = task
        try:
            return await task
        finally:
            if _duration_inflight.get(key) is task:
                _duration_inflight.pop(key, None)
    except Exception as e:
        logger.error(f"Failed to get media duration for {file_path}: {e}")
        raise
