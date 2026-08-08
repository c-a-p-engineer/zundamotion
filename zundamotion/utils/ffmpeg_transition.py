"""FFmpeg transition planning, boundary encoding, and local concat helpers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from .ffmpeg_audio import has_audio_stream
from .ffmpeg_capabilities import _threading_flags, get_hw_encoder_kind_for_video_params
from .ffmpeg_concat import concat_videos_safe
from .ffmpeg_hw import get_profile_flags
from .ffmpeg_params import AudioParams, VideoParams
from .ffmpeg_probe import get_media_duration, get_media_info
from .ffmpeg_runner import run_ffmpeg_async as _run_ffmpeg_async
from .logger import logger


async def _copy_segment(
    input_path: str, output_path: str, *, start: float, duration: float,
    ffmpeg_path: str = "ffmpeg", context: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    if duration <= 0.02:
        return None
    cmd = [
        ffmpeg_path, "-y", *get_profile_flags(), "-ss", f"{max(0.0, start):.3f}",
        "-i", input_path, "-t", f"{max(0.0, duration):.3f}",
        "-map", "0", "-c", "copy", "-avoid_negative_ts", "make_zero", output_path,
    ]
    await _run_ffmpeg_async(cmd, context=context)
    return output_path


async def _encode_segment(
    input_path: str, output_path: str, *, start: float, duration: float,
    video_params: VideoParams, audio_params: AudioParams,
    ffmpeg_path: str = "ffmpeg", hw_encoder: str = "auto",
    context: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    if duration <= 0.02:
        return None
    has_audio = await has_audio_stream(input_path)
    hw_kind = await get_hw_encoder_kind_for_video_params(ffmpeg_path, hw_encoder)
    cmd = [
        ffmpeg_path, "-y", *get_profile_flags(), *_threading_flags(ffmpeg_path),
        "-i", input_path, "-ss", f"{max(0.0, start):.3f}",
        "-t", f"{max(0.0, duration):.3f}", "-map", "0:v:0",
    ]
    if has_audio:
        cmd.extend(["-map", "0:a:0"])
    cmd.extend([
        "-vf",
        f"fps={int(video_params.fps)},scale={int(video_params.width)}:{int(video_params.height)},"
        f"format={video_params.pix_fmt},setpts=PTS-STARTPTS",
    ])
    if has_audio:
        cmd.extend(["-af", f"aresample={int(audio_params.sample_rate)},asetpts=PTS-STARTPTS"])
    else:
        cmd.append("-an")
    cmd.extend(video_params.to_ffmpeg_opts(hw_kind))
    if has_audio:
        cmd.extend(audio_params.to_ffmpeg_opts())
    cmd.append(output_path)
    await _run_ffmpeg_async(cmd, context=context)
    return output_path


async def _create_freeze_tail(
    input_path: str, output_path: str, *, source_duration: float,
    freeze_duration: float, video_params: VideoParams, audio_params: AudioParams,
    ffmpeg_path: str = "ffmpeg", hw_encoder: str = "auto",
    source_time: Optional[float] = None, context: Optional[Dict[str, Any]] = None,
) -> str:
    freeze_duration = max(0.02, float(freeze_duration))
    if source_time is None:
        info = await get_media_info(input_path, caller="transition_freeze_tail")
        video_duration = float((info.get("video") or {}).get("duration") or source_duration)
        margin = max(0.10, 2.0 / max(1, int(video_params.fps)))
        start = max(0.0, video_duration - margin)
    else:
        start = max(0.0, float(source_time))
    hw_kind = await get_hw_encoder_kind_for_video_params(ffmpeg_path, hw_encoder)
    cmd = [
        ffmpeg_path, "-y", *get_profile_flags(), *_threading_flags(ffmpeg_path),
        "-ss", f"{start:.3f}", "-i", input_path, "-f", "lavfi",
        "-t", f"{freeze_duration:.3f}", "-i",
        f"anullsrc=channel_layout=stereo:sample_rate={int(audio_params.sample_rate)}",
        "-filter_complex",
        "[0:v]trim=start=0,setpts=PTS-STARTPTS,"
        f"fps={int(video_params.fps)},scale={int(video_params.width)}:{int(video_params.height)},"
        f"format={video_params.pix_fmt},tpad=stop_mode=clone:stop_duration={freeze_duration:.3f}[v]",
        "-map", "[v]", "-map", "1:a", "-t", f"{freeze_duration:.3f}",
        *video_params.to_ffmpeg_opts(hw_kind), *audio_params.to_ffmpeg_opts(), output_path,
    ]
    await _run_ffmpeg_async(cmd, context=context)
    return output_path


def _transition_paths(output_path: str) -> Dict[str, str]:
    out_dir = os.path.dirname(os.path.abspath(output_path)) or "."
    stem = Path(output_path).stem
    return {
        name: os.path.join(out_dir, f"{stem}_{name}.mp4")
        for name in ("prefix", "tail1", "head2", "boundary", "suffix")
    }


async def _prepare_transition_heads(
    *, input1: str, input2: str, paths: Dict[str, str],
    dur1: float, second_head: float, offset: float, wait_padding: float,
    consume_next_head: bool, video_params: VideoParams, audio_params: AudioParams,
    ffmpeg_path: str, hw_encoder: str, context: Dict[str, Any],
) -> tuple[List[str], float]:
    parts: List[str] = []
    if wait_padding > 0:
        prefix = await _copy_segment(
            input1, paths["prefix"], start=0.0, duration=dur1, ffmpeg_path=ffmpeg_path,
            context={**context, "operation": "transition_prefix_copy"},
        )
        if prefix:
            parts.append(prefix)
        await _create_freeze_tail(
            input1, paths["tail1"], source_duration=dur1, freeze_duration=wait_padding,
            video_params=video_params, audio_params=audio_params, ffmpeg_path=ffmpeg_path,
            hw_encoder=hw_encoder, context={**context, "operation": "transition_freeze_tail"},
        )
        await _encode_segment(
            input2, paths["head2"], start=0.0, duration=max(0.02, second_head),
            video_params=video_params, audio_params=audio_params, ffmpeg_path=ffmpeg_path,
            hw_encoder=hw_encoder, context={**context, "operation": "transition_head_encode"},
        )
        return parts, second_head if consume_next_head else 0.0
    prefix = await _copy_segment(
        input1, paths["prefix"], start=0.0, duration=offset, ffmpeg_path=ffmpeg_path,
        context={**context, "operation": "transition_prefix_copy"},
    )
    if prefix:
        parts.append(prefix)
    await _copy_segment(
        input1, paths["tail1"], start=offset, duration=max(0.02, dur1 - offset),
        ffmpeg_path=ffmpeg_path, context={**context, "operation": "transition_tail_copy"},
    )
    await _copy_segment(
        input2, paths["head2"], start=0.0, duration=max(0.02, second_head),
        ffmpeg_path=ffmpeg_path, context={**context, "operation": "transition_head_copy"},
    )
    return parts, second_head


async def _prepare_transition_suffix(
    *, input2: str, path: str, start: float, dur2: float,
    consume_next_head: bool, video_params: VideoParams, audio_params: AudioParams,
    ffmpeg_path: str, hw_encoder: str, context: Dict[str, Any],
) -> tuple[Optional[str], bool]:
    if consume_next_head and start > 0:
        result = await _encode_segment(
            input2, path, start=start, duration=max(0.0, dur2 - start),
            video_params=video_params, audio_params=audio_params,
            ffmpeg_path=ffmpeg_path, hw_encoder=hw_encoder,
            context={**context, "operation": "transition_suffix_encode"},
        )
        return result, bool(result)
    result = await _copy_segment(
        input2, path, start=start, duration=max(0.0, dur2 - start),
        ffmpeg_path=ffmpeg_path, context={**context, "operation": "transition_suffix_copy"},
    )
    return result, False


def _transition_note(wait_padding: float, consume_next_head: bool, suffix_reencoded: bool) -> str:
    if wait_padding > 0 and consume_next_head and suffix_reencoded:
        return " (freeze-before-transition, consume-next-head, reencoded-next-suffix)"
    if wait_padding > 0 and consume_next_head:
        return " (freeze-before-transition, consume-next-head)"
    return " (freeze-before-transition)" if wait_padding > 0 else ""


async def apply_transition_local(
    input_video1_path: str, input_video2_path: str, output_path: str,
    transition_type: str, duration: float, offset: float,
    video_params: VideoParams, audio_params: AudioParams,
    ffmpeg_path: str = "ffmpeg", wait_padding: float = 0.0,
    hw_encoder: str = "auto", consume_next_head: bool = False,
    context: Optional[Dict[str, Any]] = None,
) -> None:
    resolved = dict(context or {})
    dur1 = float(await get_media_duration(input_video1_path, caller="transition_input_probe"))
    dur2 = float(await get_media_duration(input_video2_path, caller="transition_input_probe"))
    offset = max(0.0, min(float(offset), dur1))
    duration = max(0.001, float(duration))
    wait_padding = max(0.0, float(wait_padding))
    second_head = min(dur2, duration)
    paths = _transition_paths(output_path)
    parts, suffix_start = await _prepare_transition_heads(
        input1=input_video1_path, input2=input_video2_path, paths=paths,
        dur1=dur1, second_head=second_head, offset=offset, wait_padding=wait_padding,
        consume_next_head=consume_next_head, video_params=video_params,
        audio_params=audio_params, ffmpeg_path=ffmpeg_path, hw_encoder=hw_encoder,
        context=resolved,
    )
    await apply_transition(
        paths["tail1"], paths["head2"], paths["boundary"], transition_type,
        min(duration, second_head), 0.0, video_params, audio_params,
        ffmpeg_path=ffmpeg_path, wait_padding=wait_padding,
        hw_encoder=hw_encoder, context={**resolved, "operation": "transition_boundary"},
    )
    parts.append(paths["boundary"])
    suffix, suffix_reencoded = await _prepare_transition_suffix(
        input2=input_video2_path, path=paths["suffix"], start=suffix_start, dur2=dur2,
        consume_next_head=consume_next_head, video_params=video_params,
        audio_params=audio_params, ffmpeg_path=ffmpeg_path, hw_encoder=hw_encoder,
        context=resolved,
    )
    if suffix:
        parts.append(suffix)
    try:
        mode = await concat_videos_safe(
            parts, output_path, audio_params, ffmpeg_path, movflags_faststart=True,
            context={**resolved, "operation": "transition_parts_concat"},
        )
        logger.info(
            "Applied local '%s' transition: concat=%s parts=%d, re-encoded boundary %.2fs%s -> %s",
            transition_type, mode, len(parts), duration + wait_padding,
            _transition_note(wait_padding, consume_next_head, suffix_reencoded), output_path,
        )
    except Exception as exc:
        logger.warning("Local transition concat failed (%s). Falling back to full transition encode.", exc)
        await apply_transition(
            input_video1_path, input_video2_path, output_path, transition_type,
            duration, offset, video_params, audio_params, ffmpeg_path=ffmpeg_path,
            wait_padding=wait_padding, hw_encoder=hw_encoder,
            context={**resolved, "operation": "transition_full_fallback"},
        )


def _audio_filter_parts(
    *, has_a1: bool, has_a2: bool, audio_params: AudioParams,
    wait_padding: float, xfade_offset: float, duration: float,
) -> tuple[List[str], Optional[str]]:
    channels = max(1, int(audio_params.channels))
    layout = "stereo" if channels == 2 else f"{channels}c"
    common = f"aresample=async=1:first_pts=0,aformat=sample_fmts=fltp:sample_rates={audio_params.sample_rate}:channel_layouts={layout}"
    if has_a1 and has_a2:
        return [
            f"[0:a]{common},apad=pad_dur={wait_padding:.3f}[a0pad]",
            f"[1:a]{common}[a1]",
            f"[a0pad][a1]acrossfade=d={duration}:c1=tri:c2=tri[a]",
        ], "[a]"
    if has_a1:
        return [
            f"[0:a]{common},apad=pad_dur={wait_padding:.3f},"
            f"afade=t=out:st={xfade_offset:.3f}:d={duration}[a]"
        ], "[a]"
    if has_a2:
        delay_ms = int(round(xfade_offset * 1000))
        return [
            f"[1:a]{common},adelay={delay_ms}:all=1,apad=pad_dur={wait_padding:.3f},"
            f"afade=t=in:st=0:d={duration}[a]"
        ], "[a]"
    return [], None


async def apply_transition(
    input_video1_path: str, input_video2_path: str, output_path: str,
    transition_type: str, duration: float, offset: float,
    video_params: VideoParams, audio_params: AudioParams,
    ffmpeg_path: str = "ffmpeg", wait_padding: float = 0.0,
    hw_encoder: str = "auto", context: Optional[Dict[str, Any]] = None,
):
    has_a1 = await has_audio_stream(input_video1_path)
    has_a2 = await has_audio_stream(input_video2_path)
    hw_kind = await get_hw_encoder_kind_for_video_params(ffmpeg_path, hw_encoder)
    wait_padding = max(0.0, wait_padding)
    xfade_offset = max(0.0, offset + wait_padding)
    cmd = [
        ffmpeg_path, "-y", *get_profile_flags(), *_threading_flags(ffmpeg_path),
        "-i", input_video1_path, "-i", input_video2_path,
    ]
    video_input = "0:v"
    parts: List[str] = []
    if wait_padding > 0:
        parts.append(f"[0:v]tpad=stop_mode=clone:stop_duration={wait_padding:.3f}[v0pad]")
        video_input = "v0pad"
    parts.append(
        f"[{video_input}][1:v]xfade=transition={transition_type}:duration={duration}:"
        f"offset={xfade_offset:.3f}[v]"
    )
    audio_parts, audio_label = _audio_filter_parts(
        has_a1=has_a1, has_a2=has_a2, audio_params=audio_params,
        wait_padding=wait_padding, xfade_offset=xfade_offset, duration=duration,
    )
    parts.extend(audio_parts)
    cmd.extend(["-filter_complex", ";".join(parts), "-map", "[v]"])
    if audio_label:
        cmd.extend(["-map", audio_label])
    cmd.extend(video_params.to_ffmpeg_opts(hw_kind))
    cmd.extend(audio_params.to_ffmpeg_opts())
    cmd.append(output_path)
    process = await _run_ffmpeg_async(
        cmd,
        context={**dict(context or {}), "input_paths": [input_video1_path, input_video2_path], "output_path": output_path},
    )
    logger.debug("FFmpeg stdout:\n%s", process.stdout)
    logger.debug("FFmpeg stderr:\n%s", process.stderr)
    logger.info(
        "Applied '%s' transition (wait_padding=%.2fs) with audio crossfade: %s + %s -> %s",
        transition_type, wait_padding, input_video1_path, input_video2_path, output_path,
    )
