"""Cache-aware media normalization with hardware-encoder fallback."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from .ffmpeg_audio import has_audio_stream
from .ffmpeg_background import (
    BACKGROUND_FIT_STRETCH,
    DEFAULT_BACKGROUND_ANCHOR,
    DEFAULT_BACKGROUND_FILL_COLOR,
    _sanitize_anchor,
    _to_expr,
    build_background_fit_steps,
    compose_background_filter_expression,
)
from .ffmpeg_capabilities import (
    _threading_flags,
    get_ffmpeg_version,
    get_hw_encoder_kind_for_video_params,
)
from .ffmpeg_params import AudioParams, VideoParams
from .ffmpeg_probe import get_media_info
from .ffmpeg_runner import run_ffmpeg_async as _run_ffmpeg_async
from .logger import logger


@dataclass(frozen=True)
class NormalizeContext:
    fit_mode: str
    fill_color: str
    anchor: str
    offset_x: str
    offset_y: str
    position: Dict[str, str]
    scale_flags: str


def _normalize_context(
    fit_mode: str, fill_color: str, anchor: str,
    position: Optional[Dict[str, Any]], scale_flags: str,
) -> NormalizeContext:
    raw = position or {}
    offset_x, offset_y = _to_expr(raw.get("x", "0")), _to_expr(raw.get("y", "0"))
    return NormalizeContext(
        fit_mode=(fit_mode or BACKGROUND_FIT_STRETCH).lower(),
        fill_color=fill_color or DEFAULT_BACKGROUND_FILL_COLOR,
        anchor=_sanitize_anchor(anchor), offset_x=offset_x, offset_y=offset_y,
        position={"x": offset_x, "y": offset_y}, scale_flags=scale_flags,
    )


def _target_spec(
    video_params: VideoParams, audio_params: AudioParams, ctx: NormalizeContext
) -> Dict[str, Any]:
    return {
        "video": {
            "width": int(video_params.width), "height": int(video_params.height),
            "fps": int(video_params.fps), "pix_fmt": video_params.pix_fmt,
            "codec": "h264", "background_fit": ctx.fit_mode,
            "background_fill_color": ctx.fill_color, "background_anchor": ctx.anchor,
            "background_position": ctx.position,
        },
        "audio": {
            "sr": int(audio_params.sample_rate), "ch": int(audio_params.channels),
            "codec": audio_params.codec,
        },
    }


def _meta_path(path: Path) -> Path:
    return path.with_name(path.stem + ".meta.json")


def _matches_existing_normalized(
    input_path: Path, target_spec: Dict[str, Any]
) -> bool:
    try:
        if not input_path.is_file() or input_path.suffix.lower() != ".mp4":
            return False
        meta = _meta_path(input_path)
        if not meta.exists():
            return False
        with meta.open("r", encoding="utf-8") as stream:
            return json.load(stream).get("target_spec") == target_spec
    except Exception as exc:
        logger.debug("Skip pre-check for already-normalized input due to error: %s", exc)
        return False


async def _cache_key_data(
    input_path: Path, video_params: VideoParams, audio_params: AudioParams,
    ffmpeg_path: str, ctx: NormalizeContext,
) -> Dict[str, Any]:
    stat = input_path.stat()
    return {
        "input_path": str(input_path.resolve()),
        "file_size": stat.st_size,
        "file_mtime": stat.st_mtime,
        "video_params": video_params.__dict__,
        "audio_params": audio_params.__dict__,
        "ffmpeg_version": await get_ffmpeg_version(ffmpeg_path),
        "background_fit": ctx.fit_mode,
        "background_fill_color": ctx.fill_color,
        "background_anchor": ctx.anchor,
        "background_position": ctx.position,
        "scale_flags": ctx.scale_flags,
    }


def _copy_decisions(
    info: Dict[str, Any], has_audio: bool,
    video_params: VideoParams, audio_params: AudioParams, ctx: NormalizeContext,
) -> tuple[bool, bool]:
    video = info.get("video")
    can_video = False
    if video:
        parameters_match = (
            video.get("width") == video_params.width
            and video.get("height") == video_params.height
            and video.get("fps") == video_params.fps
            and video.get("pix_fmt") == video_params.pix_fmt
            and video.get("codec_name") in ["h264", "hevc"]
        )
        requires_fit = (
            ctx.fit_mode != BACKGROUND_FIT_STRETCH
            or ctx.offset_x != "0" or ctx.offset_y != "0"
        )
        can_video = parameters_match and not requires_fit
    audio = info.get("audio")
    can_audio = bool(
        has_audio and audio
        and audio.get("sample_rate") == audio_params.sample_rate
        and audio.get("channels") == audio_params.channels
        and audio.get("codec_name") == audio_params.codec
    )
    return can_video, can_audio


def _video_filter(video_params: VideoParams, ctx: NormalizeContext) -> str:
    steps = build_background_fit_steps(
        width=int(video_params.width), height=int(video_params.height),
        fit_mode=ctx.fit_mode, fill_color=ctx.fill_color, anchor=ctx.anchor,
        offset_x=ctx.offset_x, offset_y=ctx.offset_y, scale_flags=ctx.scale_flags,
    )
    core = compose_background_filter_expression(
        steps=steps, apply_fps=True, fps=int(video_params.fps)
    )
    return f"{core},setpts=PTS-STARTPTS"


async def _build_normalize_command(
    *, input_path: Path, output_path: Path,
    video_params: VideoParams, audio_params: AudioParams,
    ffmpeg_path: str, ctx: NormalizeContext,
    has_audio: bool, can_copy_video: bool, can_copy_audio: bool,
    disable_hwenc: bool,
) -> List[str]:
    cmd: List[str] = [ffmpeg_path, "-y", *_threading_flags(ffmpeg_path), "-i", str(input_path)]
    audio_filter = f"aresample={audio_params.sample_rate},asetpts=PTS-STARTPTS"
    if can_copy_video and can_copy_audio:
        cmd.extend(["-c", "copy"])
        logger.info("Using -c copy for both video and audio for %s", input_path)
    elif can_copy_video:
        cmd.extend(["-c:v", "copy"])
        if has_audio:
            cmd.extend(["-af", audio_filter])
            cmd.extend(audio_params.to_ffmpeg_opts())
        else:
            cmd.append("-an")
        logger.info("Using -c:v copy for video for %s", input_path)
    elif can_copy_audio:
        cmd.extend(["-c:a", "copy", "-af", audio_filter, "-vf", _video_filter(video_params, ctx)])
        hw_kind = None if disable_hwenc else await get_hw_encoder_kind_for_video_params(ffmpeg_path)
        cmd.extend(video_params.to_ffmpeg_opts(hw_kind))
        logger.info("Using -c:a copy for audio for %s", input_path)
    else:
        cmd.extend(["-vf", _video_filter(video_params, ctx)])
        if has_audio:
            cmd.extend(["-af", audio_filter])
        else:
            cmd.append("-an")
        hw_kind = None if disable_hwenc else await get_hw_encoder_kind_for_video_params(ffmpeg_path)
        cmd.extend(video_params.to_ffmpeg_opts(hw_kind))
        if has_audio:
            cmd.extend(audio_params.to_ffmpeg_opts())
        logger.info("Re-encoding video and/or audio for %s", input_path)
    cmd.append(str(output_path))
    return cmd


def _write_normalize_meta(path: Path, target_spec: Dict[str, Any]) -> None:
    try:
        with _meta_path(path).open("w", encoding="utf-8") as stream:
            json.dump({"target_spec": target_spec}, stream, ensure_ascii=False)
    except Exception as exc:
        logger.debug("Failed to write normalization meta: %s", exc)


def _hardware_failure(exc: subprocess.CalledProcessError) -> bool:
    message = (exc.stderr or "") + "\n" + (exc.stdout or "")
    rc = getattr(exc, "returncode", None)
    return (
        "exit status 234" in message or "exit code 234" in message or rc == 234
        or "h264_nvenc" in message or "nvenc" in message.lower()
        or "No NVENC capable devices found" in message
        or "h264_qsv" in message or "_qsv" in message.lower()
        or "MFX session" in message or "Could not open encoder" in message
        or "Error while opening encoder" in message
    )


async def _execute_normalize(
    *, input_path: Path, output_path: Path,
    video_params: VideoParams, audio_params: AudioParams,
    ffmpeg_path: str, ctx: NormalizeContext,
    has_audio: bool, copy_video: bool, copy_audio: bool,
    target_spec: Dict[str, Any],
) -> Path:
    cmd = await _build_normalize_command(
        input_path=input_path, output_path=output_path, video_params=video_params,
        audio_params=audio_params, ffmpeg_path=ffmpeg_path, ctx=ctx,
        has_audio=has_audio, can_copy_video=copy_video, can_copy_audio=copy_audio,
        disable_hwenc=False,
    )
    try:
        await _run_ffmpeg_async(cmd)
    except subprocess.CalledProcessError as exc:
        if not _hardware_failure(exc):
            logger.error("Error normalizing media %s: %s", input_path, exc)
            logger.error("FFmpeg stdout:\n%s", exc.stdout)
            logger.error("FFmpeg stderr:\n%s", exc.stderr)
            raise
        logger.warning("Hardware encoder failed during normalization. Falling back to libx264 and retrying once.")
        previous = os.environ.get("DISABLE_HWENC")
        os.environ["DISABLE_HWENC"] = "1"
        try:
            cpu_cmd = await _build_normalize_command(
                input_path=input_path, output_path=output_path, video_params=video_params,
                audio_params=audio_params, ffmpeg_path=ffmpeg_path, ctx=ctx,
                has_audio=has_audio, can_copy_video=copy_video, can_copy_audio=copy_audio,
                disable_hwenc=True,
            )
            await _run_ffmpeg_async(cpu_cmd)
        finally:
            if previous is None:
                os.environ.pop("DISABLE_HWENC", None)
            else:
                os.environ["DISABLE_HWENC"] = previous
    _write_normalize_meta(output_path, target_spec)
    return output_path


async def normalize_media(
    input_path: Path, video_params: VideoParams, audio_params: AudioParams,
    cache_manager: Any, ffmpeg_path: str = "ffmpeg", *,
    fit_mode: str = BACKGROUND_FIT_STRETCH,
    fill_color: str = DEFAULT_BACKGROUND_FILL_COLOR,
    anchor: str = DEFAULT_BACKGROUND_ANCHOR,
    position: Optional[Dict[str, Any]] = None,
    scale_flags: str = "lanczos",
) -> Path:
    """Normalize media using the historical cache key and fallback contract."""
    ctx = _normalize_context(fit_mode, fill_color, anchor, position, scale_flags)
    target = _target_spec(video_params, audio_params, ctx)
    if _matches_existing_normalized(input_path, target):
        logger.info("[Cache] Skipping re-normalization for cached normalized file: %s", input_path)
        return input_path
    key_data = await _cache_key_data(
        input_path, video_params, audio_params, ffmpeg_path, ctx
    )
    cached = cache_manager.get_cache_path(key_data, "normalized", "mp4")
    if not cache_manager.no_cache and not cache_manager.cache_refresh and cached.exists():
        logger.info("[Cache] Normalized hit: %s", cached)
        return cached

    async def creator(output_path: Path) -> Path:
        info = await get_media_info(str(input_path))
        has_audio = await has_audio_stream(str(input_path))
        copy_video, copy_audio = _copy_decisions(
            info, has_audio, video_params, audio_params, ctx
        )
        return await _execute_normalize(
            input_path=input_path, output_path=output_path,
            video_params=video_params, audio_params=audio_params,
            ffmpeg_path=ffmpeg_path, ctx=ctx, has_audio=has_audio,
            copy_video=copy_video, copy_audio=copy_audio, target_spec=target,
        )

    logger.info("[Cache] Normalized miss: %s -> generating...", input_path)
    return await cache_manager.get_or_create(
        key_data=key_data, file_name="normalized", extension="mp4", creator_func=creator
    )
