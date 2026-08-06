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
from .ffmpeg_params import AudioParams

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
    duration: Optional[float]


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


def _parse_media_probe(payload: Dict[str, Any]) -> MediaInfo:
    media_info: MediaInfo = {"video": None, "audio": None, "duration": None}
    for stream in payload.get("streams", []):
        if stream.get("codec_type") == "video" and media_info["video"] is None:
            r_rate = stream.get("r_frame_rate", "0/0")
            try:
                num, den = map(int, r_rate.split("/"))
                fps = float(num) / float(den) if den else 0.0
            except Exception:
                fps = 0.0
            media_info["video"] = {
                "codec_name": stream.get("codec_name"),
                "width": int(stream.get("width", 0)),
                "height": int(stream.get("height", 0)),
                "pix_fmt": stream.get("pix_fmt"),
                "r_frame_rate": r_rate,
                "fps": fps,
            }
        elif stream.get("codec_type") == "audio" and media_info["audio"] is None:
            media_info["audio"] = {
                "codec_name": stream.get("codec_name"),
                "sample_rate": (
                    int(stream.get("sample_rate", 0))
                    if stream.get("sample_rate")
                    else 0
                ),
                "channels": (
                    int(stream.get("channels", 0)) if stream.get("channels") else 0
                ),
                "channel_layout": stream.get("channel_layout"),
            }

    raw_duration = (payload.get("format") or {}).get("duration")
    if raw_duration not in {None, "", "N/A"}:
        media_info["duration"] = round(float(raw_duration), 2)
    return media_info


def _memoize_probe(key: tuple[str, int, int], media_info: MediaInfo) -> None:
    _media_info_memo[key] = media_info
    duration = media_info.get("duration")
    if duration is not None:
        normalized = float(duration)
        _duration_memo[("med", *key)] = normalized
        _duration_memo[("aud", *key)] = normalized


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

    path = Path(file_path)
    result: AssetMetadata = {
        "path": str(path),
        "image": None,
        "video": None,
        "audio": None,
    }
    if _is_image_path(path):
        result["kind"] = "image"
        result["image"] = get_image_info(file_path)
        return result

    result["kind"] = "media"
    media_info = await get_media_info(file_path, caller=caller or "probe_asset")
    result["video"] = media_info.get("video")
    result["audio"] = media_info.get("audio")
    duration = media_info.get("duration")
    if duration is None:
        duration = await get_media_duration(file_path, caller=caller or "probe_asset")
    result["duration"] = duration
    return result


async def get_media_info(file_path: str, caller: Optional[str] = None) -> MediaInfo:
    """動画/音声のstream情報とformat durationを1回のffprobeで取得する。"""
    try:
        resolved_caller = _resolve_probe_caller(caller)
        path = Path(file_path)
        key = _stat_key(path)
        if key in _media_info_memo:
            return _media_info_memo[key]
        existing = _media_info_inflight.get(key)
        if existing is not None:
            return await existing

        async def _probe() -> MediaInfo:
            command = [
                "ffprobe",
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                file_path,
            ]
            completed = await run_ffmpeg_async(
                command,
                context={
                    "phase": "Probe",
                    "operation": "media_info",
                    "caller": resolved_caller,
                    "path": file_path,
                    "includes_duration": True,
                },
            )
            media_info = _parse_media_probe(json.loads(completed.stdout))
            _memoize_probe(key, media_info)
            return media_info

        task = asyncio.create_task(_probe())
        _media_info_inflight[key] = task
        try:
            return await task
        finally:
            if _media_info_inflight.get(key) is task:
                _media_info_inflight.pop(key, None)
    except subprocess.CalledProcessError as exc:
        logger.error("Error running ffprobe for %s: %s", file_path, exc.stderr)
        raise
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        logger.error("Error parsing ffprobe output for %s: %s", file_path, exc)
        raise


async def probe_media_params_async(path: Path) -> Dict[str, Any]:
    """ffprobe で幅やFPSなど最小限の情報を取得する。"""
    try:
        media_info = await get_media_info(
            str(path), caller="probe_media_params_async"
        )
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
    except Exception as exc:
        logger.error("Error probing media params for %s: %s", path, exc)
        return {}


async def _probe_duration_only(
    file_path: str,
    *,
    caller: str,
    operation: str,
) -> float:
    completed = await run_ffmpeg_async(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            file_path,
        ],
        context={
            "phase": "Probe",
            "operation": operation,
            "caller": caller,
            "path": file_path,
            "reason": "combined_probe_missing_duration",
        },
    )
    payload = json.loads(completed.stdout)
    return round(float(payload["format"]["duration"]), 2)


async def _get_duration(
    file_path: str,
    *,
    kind: str,
    caller: Optional[str],
) -> float:
    resolved_caller = _resolve_probe_caller(caller)
    path = Path(file_path)
    stat_key = _stat_key(path)
    duration_key = (kind, *stat_key)
    if duration_key in _duration_memo:
        return _duration_memo[duration_key]
    existing = _duration_inflight.get(duration_key)
    if existing is not None:
        return await existing

    async def _resolve() -> float:
        media_info = await get_media_info(file_path, caller=resolved_caller)
        duration = media_info.get("duration")
        if duration is None:
            operation = "audio_duration" if kind == "aud" else "media_duration"
            duration = await _probe_duration_only(
                file_path,
                caller=resolved_caller,
                operation=operation,
            )
        normalized = float(duration)
        _duration_memo[("med", *stat_key)] = normalized
        _duration_memo[("aud", *stat_key)] = normalized
        return normalized

    task = asyncio.create_task(_resolve())
    _duration_inflight[duration_key] = task
    try:
        return await task
    finally:
        if _duration_inflight.get(duration_key) is task:
            _duration_inflight.pop(duration_key, None)


async def get_audio_duration(file_path: str, caller: Optional[str] = None) -> float:
    """音声ファイルの長さ(秒)を返す。"""
    try:
        return await _get_duration(file_path, kind="aud", caller=caller)
    except Exception as exc:
        logger.error("Failed to get audio duration for %s: %s", file_path, exc)
        raise


async def get_media_duration(file_path: str, caller: Optional[str] = None) -> float:
    """動画/音声ファイルの長さ(秒)を返す。"""
    try:
        return await _get_duration(file_path, kind="med", caller=caller)
    except Exception as exc:
        logger.error("Failed to get media duration for %s: %s", file_path, exc)
        raise


async def validate_final_media(
    file_path: str,
    audio_params: AudioParams,
    *,
    start_tolerance: float = 0.1,
    duration_tolerance: float = 0.1,
) -> Dict[str, Any]:
    """Validate final MP4 stream format and practical A/V synchronization."""
    result = await run_ffmpeg_async(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration,start_time:stream=codec_type,codec_name,sample_rate,channels,start_time,duration",
            "-of",
            "json",
            file_path,
        ],
        context={
            "phase": "FinalizeValidation",
            "operation": "validate_final_media",
            "path": file_path,
        },
    )
    payload = json.loads(result.stdout)
    streams = payload.get("streams") or []
    video = next(
        (item for item in streams if item.get("codec_type") == "video"), None
    )
    audio = next(
        (item for item in streams if item.get("codec_type") == "audio"), None
    )
    if video is None or audio is None:
        raise ValueError(f"Final media must contain video and audio streams: {file_path}")
    if str(audio.get("codec_name") or "").lower() != "aac":
        raise ValueError(f"Final MP4 audio must be AAC: {audio.get('codec_name')}")
    if int(audio.get("sample_rate") or 0) != int(audio_params.sample_rate):
        raise ValueError(f"Unexpected final sample rate: {audio.get('sample_rate')}")
    if int(audio.get("channels") or 0) != int(audio_params.channels):
        raise ValueError(f"Unexpected final channel count: {audio.get('channels')}")

    format_duration = float((payload.get("format") or {}).get("duration") or 0.0)
    if format_duration <= 0.0:
        raise ValueError(f"Final media duration must be positive: {file_path}")
    video_start = float(video.get("start_time") or 0.0)
    audio_start = float(audio.get("start_time") or 0.0)
    if abs(video_start - audio_start) > float(start_tolerance):
        raise ValueError(
            f"A/V start mismatch {abs(video_start - audio_start):.6f}s exceeds {start_tolerance:.6f}s"
        )
    video_duration = float(video.get("duration") or format_duration)
    audio_duration = float(audio.get("duration") or format_duration)
    duration_delta = abs(video_duration - audio_duration)
    if duration_delta > float(duration_tolerance):
        raise ValueError(
            f"A/V duration mismatch {duration_delta:.6f}s exceeds {duration_tolerance:.6f}s"
        )
    summary = {
        "audio_codec": "aac",
        "sample_rate": int(audio_params.sample_rate),
        "channels": int(audio_params.channels),
        "duration": format_duration,
        "video_start": video_start,
        "audio_start": audio_start,
        "duration_delta": duration_delta,
    }
    logger.info(
        "[FinalMedia] codec=%s sample_rate=%s channels=%s start_delta=%.6f duration_delta=%.6f path=%s",
        summary["audio_codec"],
        summary["sample_rate"],
        summary["channels"],
        abs(video_start - audio_start),
        duration_delta,
        file_path,
    )
    return summary
