"""Coordinate the extracted clip render stages."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING, Union

from ...utils.logger import logger
from .clip_audio_graph import append_clip_audio_graph
from .clip_command import build_clip_command
from .clip_executor import execute_clip_command
from .clip_filter_policy import resolve_clip_filter_policy
from .clip_input_collection import collect_clip_inputs
from .clip_video_graph import ClipVideoGraphRequest, build_clip_video_graph

if TYPE_CHECKING:
    from .renderer import VideoRenderer


@dataclass
class ClipRenderRequest:
    audio_path: Path
    duration: float
    background_config: Dict[str, Any]
    characters_config: List[Dict[str, Any]]
    output_filename: str
    subtitle_text: Optional[str] = None
    subtitle_line_config: Optional[Dict[str, Any]] = None
    insert_config: Optional[Dict[str, Any]] = None
    image_layer_overlays: Optional[List[Dict[str, Any]]] = None
    extra_audio_overlays: Optional[List[Dict[str, Any]]] = None
    background_effects: Optional[List[Any]] = None
    screen_effects: Optional[List[Any]] = None
    subtitle_png_path: Optional[Path] = None
    face_anim: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]] = None
    force_cpu: bool = False
    audio_delay: float = 0.0

    def retry_kwargs(self, subtitle_png_path: Optional[Path]) -> Dict[str, Any]:
        return {
            "audio_path": self.audio_path, "duration": self.duration,
            "background_config": self.background_config,
            "characters_config": self.characters_config,
            "output_filename": self.output_filename, "subtitle_text": self.subtitle_text,
            "subtitle_line_config": self.subtitle_line_config, "insert_config": self.insert_config,
            "image_layer_overlays": self.image_layer_overlays,
            "extra_audio_overlays": self.extra_audio_overlays,
            "background_effects": self.background_effects, "screen_effects": self.screen_effects,
            "subtitle_png_path": subtitle_png_path, "face_anim": self.face_anim,
            "audio_delay": self.audio_delay,
        }

    def video_graph_request(self) -> ClipVideoGraphRequest:
        return ClipVideoGraphRequest(
            duration=self.duration, background_config=self.background_config,
            characters_config=self.characters_config, subtitle_text=self.subtitle_text,
            subtitle_line_config=self.subtitle_line_config, insert_config=self.insert_config,
            screen_effects=self.screen_effects, subtitle_png_path=self.subtitle_png_path,
            face_anim=self.face_anim, audio_delay=self.audio_delay, force_cpu=self.force_cpu,
        )


async def run_clip_pipeline(
    renderer: "VideoRenderer", request: ClipRenderRequest,
) -> Optional[Path]:
    output_path = renderer.temp_dir / f"{request.output_filename}.mp4"
    started_at = time.time()
    logger.info("[Video] Rendering clip -> %s", output_path.name)
    inputs = await collect_clip_inputs(
        renderer=renderer, audio_path=request.audio_path,
        duration=request.duration,
        background_config=request.background_config,
        characters_config=request.characters_config, insert_config=request.insert_config,
        image_layer_overlays=request.image_layer_overlays,
        extra_audio_overlays=request.extra_audio_overlays,
    )
    policy = resolve_clip_filter_policy(
        renderer=renderer, inputs=inputs, background_config=request.background_config,
        insert_config=request.insert_config, subtitle_text=request.subtitle_text,
        background_effects=request.background_effects, force_cpu=request.force_cpu,
    )
    graph = await build_clip_video_graph(renderer, inputs, request.video_graph_request(), policy)
    audio_map = await append_clip_audio_graph(
        renderer=renderer, inputs=inputs, audio_path=request.audio_path,
        duration=request.duration, insert_config=request.insert_config,
        audio_delay=request.audio_delay, parts=graph.filter_complex_parts,
    )
    cmd = build_clip_command(
        renderer=renderer, input_command=inputs.cmd,
        filter_complex_parts=graph.filter_complex_parts, audio_map=audio_map,
        duration=request.duration, output_path=output_path, force_cpu=request.force_cpu,
    )
    return await execute_clip_command(
        renderer=renderer, cmd=cmd, output_filename=request.output_filename,
        output_path=output_path, started_at=started_at, force_cpu=request.force_cpu,
        retry_kwargs=request.retry_kwargs(graph.subtitle_png_path),
    )
