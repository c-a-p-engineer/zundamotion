"""Build FFmpeg input/filter/map arguments for subtitle full-burn execution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from ...utils.logger import logger


@dataclass(frozen=True)
class SubtitleBurnCommand:
    argv: List[str]
    mode: str
    base_duration: Optional[float]


async def _append_ass_graph(
    renderer: Any,
    *,
    base_video: Path,
    subtitles: List[Dict[str, Any]],
    filter_parts: List[str],
) -> str:
    ass_path = renderer._build_ass_subtitle_file(
        f"{base_video.stem}_subtitle_only", subtitles
    )
    logger.info("[SubtitleOverlay] Using ASS/libass mode for %s subtitle(s)", len(subtitles))
    filter_parts.append(f"[0:v]{renderer._build_ass_filter(ass_path)}[with_subtitle_ass]")
    return "[with_subtitle_ass]"


async def _append_png_graph(
    renderer: Any,
    *,
    subtitles: List[Dict[str, Any]],
    cmd: List[str],
    filter_parts: List[str],
) -> str:
    use_cuda = renderer._should_use_cuda_for_subtitles(subtitles)
    previous = "[0:v]"
    png_inputs: List[str] = []
    for index, subtitle in enumerate(subtitles, start=1):
        extra_input, snippet = await renderer.subtitle_gen.build_subtitle_overlay(
            subtitle["text"],
            subtitle["duration"],
            subtitle.get("line_config", {}),
            in_label=previous.strip("[]"),
            index=index,
            allow_cuda=use_cuda,
        )
        for key, value in extra_input.items():
            cmd.extend([key, value])
            if key == "-i":
                png_inputs.append(str(value))
        start = float(subtitle["start"])
        end = start + float(subtitle["duration"])
        snippet = snippet.replace(
            f"between(t,0,{subtitle['duration']})", f"between(t,{start},{end})"
        )
        filter_parts.append(snippet)
        previous = f"[with_subtitle_{index}]"
    _log_png_graph(png_inputs, filter_parts, cmd, subtitles)
    return previous


def _log_png_graph(
    png_inputs: List[str],
    filter_parts: List[str],
    cmd: List[str],
    subtitles: List[Dict[str, Any]],
) -> None:
    filter_complex = ";".join(filter_parts)
    unique = len(set(png_inputs))
    count = len(png_inputs)
    logger.info(
        "[SubtitleInput] unique_png=%d ffmpeg_inputs=%d duplicated=%d duplicate_reason=%s",
        unique,
        count,
        max(0, count - unique),
        "same_png_referenced_by_multiple_subtitles" if count > unique else "none",
    )
    logger.info(
        "[FilterGraph] target=subtitle_burn inputs=%d overlays=%d len=%d enable_expr=%d subtitles=%d",
        1 + count,
        filter_complex.count("overlay"),
        len(filter_complex),
        filter_complex.count("enable="),
        len(subtitles),
    )


async def build_subtitle_burn_command(
    renderer: Any,
    *,
    base_video: Path,
    subtitles: List[Dict[str, Any]],
    output_path: Path,
    base_duration: Optional[float],
    video_only: bool = False,
    segment_workers: Optional[int] = None,
) -> SubtitleBurnCommand:
    """Build the full subtitle-burn argv while preserving legacy ordering."""
    mode = renderer._subtitle_render_mode(subtitles)
    cmd: List[str] = [renderer.ffmpeg_path, "-y", "-nostdin", "-i", str(base_video)]
    parts: List[str] = []
    if mode == "ass":
        previous = await _append_ass_graph(
            renderer, base_video=base_video, subtitles=subtitles, filter_parts=parts
        )
    else:
        previous = await _append_png_graph(
            renderer, subtitles=subtitles, cmd=cmd, filter_parts=parts
        )
    if segment_workers is None:
        cmd.extend(renderer._single_job_thread_flags())
    else:
        cmd.extend(renderer._subtitle_segment_thread_flags(segment_workers))
    cmd.extend(["-filter_complex", ";".join(parts), "-map", previous])
    cmd.append("-an") if video_only else cmd.extend(["-map", "0:a?"])
    cmd.extend(renderer._subtitle_burn_video_opts(mode))
    if not video_only:
        cmd.extend(["-c:a", "copy"])
    if base_duration and base_duration > 0:
        cmd.extend(["-t", f"{base_duration:.3f}"])
    cmd.append(str(output_path))
    return SubtitleBurnCommand(cmd, mode, base_duration)
