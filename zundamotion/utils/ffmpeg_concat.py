"""DTS-safe FFmpeg concat helpers."""

from __future__ import annotations

import asyncio
import hashlib
import os
import subprocess
import time
from typing import Any, Dict, List, Optional

from .ffmpeg_capabilities import get_ffmpeg_version
from .ffmpeg_hw import get_profile_flags
from .ffmpeg_params import AudioParams
from .ffmpeg_probe import MediaInfo, get_media_duration, get_media_info
from .ffmpeg_runner import run_ffmpeg_async as _run_ffmpeg_async
from .logger import logger


class TimestampWarningError(RuntimeError):
    """Raised when FFmpeg reports unsafe DTS ordering during concat."""


def _contains_dts_warning(stderr: str) -> bool:
    normalized = str(stderr or "").lower()
    return (
        "non-monotonic dts" in normalized
        or "non monotonically increasing dts" in normalized
    )


async def compare_media_params(file_paths: List[str]) -> bool:
    if not file_paths:
        return True
    try:
        infos = await asyncio.gather(
            *(get_media_info(path, caller="compare_media_params") for path in file_paths)
        )
    except Exception as exc:
        logger.error("Error gathering media info: %s", exc)
        return False
    base: Optional[MediaInfo] = infos[0] if infos else None
    if base is None:
        logger.warning("Base media info is None, cannot compare")
        return False
    return all(_media_info_matches(base, info, file_paths[0], path) for info, path in zip(infos[1:], file_paths[1:]))


def _media_info_matches(base: MediaInfo, current: MediaInfo, base_path: str, path: str) -> bool:
    base_video, video = base.get("video"), current.get("video")
    if bool(base_video) != bool(video):
        logger.warning("Video stream presence mismatch between %s and %s", base_path, path)
        return False
    if base_video and video:
        keys = ("codec_name", "width", "height", "pix_fmt", "r_frame_rate")
        if any(base_video.get(key) != video.get(key) for key in keys):
            logger.warning("Video parameters mismatch between %s and %s", base_path, path)
            return False
    base_audio, audio = base.get("audio"), current.get("audio")
    if bool(base_audio) != bool(audio):
        logger.warning("Audio stream presence mismatch between %s and %s", base_path, path)
        return False
    if base_audio and audio:
        keys = ("codec_name", "sample_rate", "channels", "channel_layout")
        if any(base_audio.get(key) != audio.get(key) for key in keys):
            logger.warning("Audio parameters mismatch between %s and %s", base_path, path)
            return False
    return True


def _concat_list_path(input_paths: List[str], output_path: str, prefix: str) -> str:
    try:
        digest = hashlib.sha256("\n".join(input_paths).encode("utf-8")).hexdigest()[:16]
    except Exception:
        digest = "ffconcat"
    out_dir = os.path.dirname(os.path.abspath(output_path)) or "."
    path = os.path.join(out_dir, f".{prefix}_{digest}.txt")
    with open(path, "w", encoding="utf-8") as stream:
        for item in input_paths:
            stream.write(f"file '{os.path.abspath(item)}'\n")
    return path


async def concat_videos_copy(
    input_paths: List[str], output_path: str, ffmpeg_path: str = "ffmpeg",
    movflags_faststart: bool = False, context: Optional[Dict[str, Any]] = None,
):
    if not input_paths:
        logger.warning("No input paths provided for concat_videos_copy.")
        return None
    list_path = _concat_list_path(input_paths, output_path, "ffconcat")
    total_bytes = sum(os.path.getsize(path) for path in input_paths if os.path.exists(path))
    cmd = [
        ffmpeg_path, "-y", *get_profile_flags(), "-f", "concat", "-safe", "0",
        "-i", list_path, "-c", "copy",
    ]
    if movflags_faststart:
        cmd.extend(["-movflags", "+faststart"])
    cmd.append(output_path)
    started = time.time()
    try:
        process = await _run_ffmpeg_async(cmd, context=context)
        elapsed = time.time() - started
        size_mb = total_bytes / (1024 * 1024) if total_bytes else 0.0
        throughput = size_mb / elapsed if elapsed > 0 else 0.0
        logger.info(
            "[ConcatCopy] inputs=%d, size=%.1fMB, time=%.2fs, throughput=%.1fMB/s -> %s",
            len(input_paths), size_mb, elapsed, throughput, output_path,
        )
        if _contains_dts_warning(process.stderr):
            raise TimestampWarningError(
                f"Unsafe DTS ordering detected while concatenating {output_path}"
            )
        return process
    except subprocess.CalledProcessError as exc:
        logger.error("Error concatenating videos with -c copy: %s", exc)
        logger.error("FFmpeg stdout:\n%s", exc.stdout)
        logger.error("FFmpeg stderr:\n%s", exc.stderr)
        raise
    finally:
        if os.path.exists(list_path):
            os.remove(list_path)


def _final_audio_params(audio_params: AudioParams) -> AudioParams:
    return AudioParams(
        sample_rate=audio_params.sample_rate,
        channels=audio_params.channels,
        codec="aac",
        bitrate_kbps=audio_params.bitrate_kbps,
    )


async def _add_silent_audio_if_needed(
    input_paths: List[str], output_path: str, audio_params: AudioParams,
    ffmpeg_path: str, context: Dict[str, Any], infos: List[Dict[str, Any]],
) -> tuple[List[str], List[str], List[Dict[str, Any]]]:
    flags = [bool(info.get("audio")) for info in infos]
    if not (any(flags) and not all(flags)):
        return list(input_paths), [], infos
    final_audio = _final_audio_params(audio_params)
    layout = "mono" if final_audio.channels == 1 else "stereo" if final_audio.channels == 2 else f"{final_audio.channels}c"
    prepared = list(input_paths)
    temporary: List[str] = []
    try:
        for index, (path, has_audio) in enumerate(zip(input_paths, flags)):
            if has_audio:
                continue
            duration = await get_media_duration(path, caller="concat_silent_audio")
            digest = hashlib.sha256(path.encode("utf-8")).hexdigest()[:12]
            normalized = os.path.join(
                os.path.dirname(os.path.abspath(output_path)) or ".",
                f".concat_silent_{index}_{digest}.mp4",
            )
            cmd = [
                ffmpeg_path, "-y", *get_profile_flags(), "-i", path,
                "-f", "lavfi", "-t", f"{duration:.6f}", "-i",
                f"anullsrc=r={final_audio.sample_rate}:cl={layout}",
                "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
                *final_audio.to_ffmpeg_opts(), "-shortest", "-t", f"{duration:.6f}",
                "-avoid_negative_ts", "make_zero", normalized,
            ]
            await _run_ffmpeg_async(cmd, context={**context, "operation": "concat_add_silent_audio", "output_path": normalized})
            prepared[index] = normalized
            temporary.append(normalized)
        refreshed = await asyncio.gather(
            *(get_media_info(path, caller="concat_silent_audio_safety") for path in prepared)
        )
        return prepared, temporary, refreshed
    except Exception:
        for path in temporary:
            if os.path.exists(path):
                os.remove(path)
        raise


def _copy_safety(infos: List[Dict[str, Any]], count: int) -> tuple[bool, str]:
    if count <= 1:
        return True, "copy_failed"
    codecs = {
        str((info.get("audio") or {}).get("codec_name") or "").lower()
        for info in infos
    }
    safe = not bool(codecs & {"aac", "mp3"})
    return safe, "copy_failed" if safe else "lossy_audio_encoder_delay"


def _log_transition_concat(
    context: Dict[str, Any], mode: str, reason: str, infos: List[Dict[str, Any]]
) -> None:
    if not str(context.get("operation", "")).startswith("transition_parts_concat"):
        return
    video = sorted({str((info.get("video") or {}).get("codec_name") or "none") for info in infos})
    audio = sorted({str((info.get("audio") or {}).get("codec_name") or "none") for info in infos})
    logger.info(
        "[TransitionConcat] from_scene=%s to_scene=%s mode=%s reason=%s video_codec=%s audio_codec=%s dts_warnings=0",
        context.get("from_scene", context.get("scene_id", "unknown")),
        context.get("to_scene", "unknown"), mode, reason,
        ",".join(video) or "unknown", ",".join(audio) or "none",
    )


async def _concat_audio_reencode(
    paths: List[str], output_path: str, audio_params: AudioParams,
    ffmpeg_path: str, movflags_faststart: bool, context: Dict[str, Any],
    reason: str, infos: List[Dict[str, Any]],
) -> str:
    list_path = _concat_list_path(paths, output_path, "ffconcat_audio")
    final_audio = _final_audio_params(audio_params)
    cmd = [
        ffmpeg_path, "-y", *get_profile_flags(), "-fflags", "+genpts",
        "-f", "concat", "-safe", "0", "-i", list_path,
        "-map", "0:v:0", "-map", "0:a:0", "-c:v", "copy",
        "-af", f"aresample={final_audio.sample_rate}:async=1:first_pts=0,asetpts=PTS-STARTPTS",
        *final_audio.to_ffmpeg_opts(), "-avoid_negative_ts", "make_zero",
    ]
    if movflags_faststart:
        cmd.extend(["-movflags", "+faststart"])
    cmd.append(output_path)
    try:
        process = await _run_ffmpeg_async(
            cmd,
            context={**context, "operation": f"{context.get('operation', 'concat')}_audio_reencode"},
        )
        if _contains_dts_warning(process.stderr):
            raise TimestampWarningError(f"DTS warning remained after audio re-encode: {output_path}")
        logger.info(
            "[ConcatPath] mode=audio_reencode codec=%s sample_rate=%s channels=%s output=%s dts_warnings=0",
            final_audio.codec, final_audio.sample_rate, final_audio.channels, output_path,
        )
        _log_transition_concat(context, "audio_reencode", reason, infos)
        return "audio_reencode"
    finally:
        if os.path.exists(list_path):
            os.remove(list_path)


async def concat_videos_safe(
    input_paths: List[str], output_path: str, audio_params: AudioParams,
    ffmpeg_path: str = "ffmpeg", movflags_faststart: bool = False,
    context: Optional[Dict[str, Any]] = None,
) -> str:
    resolved_context = dict(context or {})
    infos: List[Dict[str, Any]] = []
    if len(input_paths) > 1:
        infos = list(await asyncio.gather(
            *(get_media_info(path, caller="concat_copy_safety") for path in input_paths)
        ))
    prepared, temporary, infos = await _add_silent_audio_if_needed(
        input_paths, output_path, audio_params, ffmpeg_path, resolved_context, infos
    ) if infos else (list(input_paths), [], infos)
    copy_safe, reason = _copy_safety(infos, len(input_paths))
    try:
        if copy_safe:
            try:
                await concat_videos_copy(
                    prepared, output_path, ffmpeg_path,
                    movflags_faststart=movflags_faststart, context=resolved_context,
                )
                logger.info("[ConcatPath] mode=copy reason=safe_inputs output=%s dts_warnings=0", output_path)
                _log_transition_concat(resolved_context, "copy", "safe_inputs", infos)
                return "copy"
            except Exception as exc:
                reason = type(exc).__name__
        log = logger.info if reason == "lossy_audio_encoder_delay" else logger.warning
        log("[ConcatPath] mode=audio_reencode reason=%s output=%s", reason, output_path)
        return await _concat_audio_reencode(
            prepared, output_path, audio_params, ffmpeg_path,
            movflags_faststart, resolved_context, reason, infos,
        )
    finally:
        for path in temporary:
            if os.path.exists(path):
                os.remove(path)
