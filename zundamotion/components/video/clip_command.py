"""Assemble the final FFmpeg argv for one clip."""

from __future__ import annotations

from pathlib import Path
from typing import List, TYPE_CHECKING

if TYPE_CHECKING:
    from .renderer import VideoRenderer


def build_clip_command(
    *,
    renderer: "VideoRenderer",
    input_command: List[str],
    filter_complex_parts: List[str],
    audio_map: str,
    duration: float,
    output_path: Path,
    force_cpu: bool,
) -> List[str]:
    """Return FFmpeg argv without executing it."""

    cmd = list(input_command)
    cmd.extend(["-filter_complex", ";".join(filter_complex_parts)])
    cmd.extend(["-map", "[final_v]", "-map", audio_map])
    cmd.extend(["-t", str(duration)])
    cmd.extend(
        renderer.video_params.to_ffmpeg_opts(
            None if force_cpu else renderer.hw_kind
        )
    )
    cmd.extend(renderer.audio_params.to_ffmpeg_opts())
    cmd.extend(["-shortest", str(output_path)])
    return cmd
