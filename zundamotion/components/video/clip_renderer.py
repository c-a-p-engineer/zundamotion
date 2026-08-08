"""Clip render orchestration.

Input collection, backend policy, filter planning, FFmpeg argv construction, and
execution live in dedicated modules so this public entry point only coordinates
the stages.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING, Union

from ...utils.logger import logger
from .clip_audio_graph import append_clip_audio_graph, _atempo_chain
from .clip_command import build_clip_command
from .clip_executor import execute_clip_command
from .clip_filter_policy import resolve_clip_filter_policy
from .clip_input_collection import collect_clip_inputs, _media_speed
from .clip_video_graph import build_clip_video_graph

if TYPE_CHECKING:
    from .renderer import VideoRenderer


async def render_clip(
    renderer: "VideoRenderer",
    audio_path: Path,
    duration: float,
    background_config: Dict[str, Any],
    characters_config: List[Dict[str, Any]],
    output_filename: str,
    subtitle_text: Optional[str] = None,
    subtitle_line_config: Optional[Dict[str, Any]] = None,
    insert_config: Optional[Dict[str, Any]] = None,
    image_layer_overlays: Optional[List[Dict[str, Any]]] = None,
    extra_audio_overlays: Optional[List[Dict[str, Any]]] = None,
    background_effects: Optional[List[Any]] = None,
    screen_effects: Optional[List[Any]] = None,
    subtitle_png_path: Optional[Path] = None,
    face_anim: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]] = None,
    _force_cpu: bool = False,
    audio_delay: float = 0.0,
) -> Optional[Path]:
    """Render one clip while preserving the historical public call contract."""

    output_path = renderer.temp_dir / f"{output_filename}.mp4"
    started_at = time.time()
    logger.info("[Video] Rendering clip -> %s", output_path.name)

    inputs = await collect_clip_inputs(
        renderer=renderer,
        audio_path=audio_path,
        background_config=background_config,
        characters_config=characters_config,
        insert_config=insert_config,
        image_layer_overlays=image_layer_overlays,
        extra_audio_overlays=extra_audio_overlays,
    )
    policy = resolve_clip_filter_policy(
        renderer=renderer,
        inputs=inputs,
        background_config=background_config,
        insert_config=insert_config,
        subtitle_text=subtitle_text,
        background_effects=background_effects,
        force_cpu=_force_cpu,
    )
    video_graph = await build_clip_video_graph(
        renderer=renderer,
        inputs=inputs,
        duration=duration,
        background_config=background_config,
        characters_config=characters_config,
        subtitle_text=subtitle_text,
        subtitle_line_config=subtitle_line_config,
        insert_config=insert_config,
        screen_effects=screen_effects,
        subtitle_png_path=subtitle_png_path,
        face_anim=face_anim,
        audio_delay=audio_delay,
        policy=policy,
        force_cpu=_force_cpu,
    )
    audio_map = await append_clip_audio_graph(
        renderer=renderer,
        inputs=inputs,
        audio_path=audio_path,
        duration=duration,
        insert_config=insert_config,
        audio_delay=audio_delay,
        parts=video_graph.filter_complex_parts,
    )
    cmd = build_clip_command(
        renderer=renderer,
        input_command=inputs.cmd,
        filter_complex_parts=video_graph.filter_complex_parts,
        audio_map=audio_map,
        duration=duration,
        output_path=output_path,
        force_cpu=_force_cpu,
    )
    retry_kwargs = {
        "audio_path": audio_path,
        "duration": duration,
        "background_config": background_config,
        "characters_config": characters_config,
        "output_filename": output_filename,
        "subtitle_text": subtitle_text,
        "subtitle_line_config": subtitle_line_config,
        "insert_config": insert_config,
        "image_layer_overlays": image_layer_overlays,
        "extra_audio_overlays": extra_audio_overlays,
        "background_effects": background_effects,
        "screen_effects": screen_effects,
        "subtitle_png_path": video_graph.subtitle_png_path,
        "face_anim": face_anim,
        "audio_delay": audio_delay,
    }
    return await execute_clip_command(
        renderer=renderer,
        cmd=cmd,
        output_filename=output_filename,
        output_path=output_path,
        started_at=started_at,
        force_cpu=_force_cpu,
        retry_kwargs=retry_kwargs,
    )
