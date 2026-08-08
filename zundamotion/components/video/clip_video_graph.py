"""Coordinate video filter-graph stages for one clip."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING, Union

from .clip.characters import build_character_overlays
from .clip.effects import resolve_screen_effects
from .clip.face import apply_face_overlays
from .clip_background_graph import build_background_graph
from .clip_filter_policy import ClipFilterPolicy
from .clip_input_collection import ClipInputCollection
from .clip_overlay_graph import (
    append_image_layer_overlays,
    append_insert_overlay,
    append_overlay_chain,
)
from .clip_subtitle_graph import append_subtitle_overlay

if TYPE_CHECKING:
    from .renderer import VideoRenderer


@dataclass
class ClipVideoGraph:
    filter_complex_parts: List[str]
    subtitle_png_path: Optional[Path]


@dataclass(frozen=True)
class ClipVideoGraphRequest:
    duration: float
    background_config: Dict[str, Any]
    characters_config: List[Dict[str, Any]]
    subtitle_text: Optional[str]
    subtitle_line_config: Optional[Dict[str, Any]]
    insert_config: Optional[Dict[str, Any]]
    screen_effects: Optional[List[Any]]
    subtitle_png_path: Optional[Path]
    face_anim: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]]
    audio_delay: float
    force_cpu: bool


def _face_entries(value: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]]) -> List[Dict[str, Any]]:
    if isinstance(value, list):
        return [entry for entry in value if isinstance(entry, dict)]
    return [value] if isinstance(value, dict) else []


async def _append_faces(
    renderer: "VideoRenderer", inputs: ClipInputCollection,
    request: ClipVideoGraphRequest, placement: Any, parts: List[str],
    streams: List[str], filters: List[str],
) -> None:
    for entry in _face_entries(request.face_anim):
        await apply_face_overlays(
            renderer=renderer, face_anim=entry,
            subtitle_line_config=request.subtitle_line_config,
            char_overlay_placement=placement, duration=request.duration,
            cmd=inputs.cmd, input_layers=inputs.input_layers,
            filter_complex_parts=parts, overlay_streams=streams,
            overlay_filters=filters, audio_delay=request.audio_delay,
        )


def _append_screen_effects(
    renderer: "VideoRenderer", request: ClipVideoGraphRequest,
    current: str, parts: List[str],
) -> str:
    snippet = resolve_screen_effects(
        effects=request.screen_effects, input_label=current,
        duration=request.duration, width=renderer.video_params.width,
        height=renderer.video_params.height, id_prefix="screen",
    )
    if not snippet:
        return current
    parts.extend(snippet.filter_chain)
    return snippet.output_label


def _append_final_video(
    renderer: "VideoRenderer", policy: ClipFilterPolicy,
    subtitle_snippet: Any, current: str, parts: List[str],
) -> None:
    used_cuda = policy.use_cuda_filters or (
        isinstance(subtitle_snippet, str) and "overlay_cuda" in subtitle_snippet
    )
    if used_cuda and renderer.hw_kind == "nvenc":
        parts.append(f"{current}null[final_v]")
    else:
        parts.append(f"{current}setpts=PTS-STARTPTS,format=yuv420p[final_v]")


async def build_clip_video_graph(
    renderer: "VideoRenderer", inputs: ClipInputCollection,
    request: ClipVideoGraphRequest, policy: ClipFilterPolicy,
) -> ClipVideoGraph:
    parts: List[str] = []
    bg_label, uploaded_label = build_background_graph(
        renderer=renderer, inputs=inputs, background_config=request.background_config,
        duration=request.duration, policy=policy, force_cpu=request.force_cpu, parts=parts,
    )
    current = uploaded_label or bg_label
    streams: List[str] = []
    filters: List[str] = []
    append_insert_overlay(
        renderer=renderer, inputs=inputs, insert_config=request.insert_config,
        policy=policy, force_cpu=request.force_cpu, parts=parts,
        streams=streams, filters=filters,
    )
    append_image_layer_overlays(
        renderer=renderer, inputs=inputs, duration=request.duration,
        parts=parts, streams=streams, filters=filters,
    )
    placement = build_character_overlays(
        renderer=renderer, characters_config=request.characters_config,
        duration=request.duration, character_indices=inputs.character_indices,
        char_effective_scale=inputs.char_effective_scale, filter_complex_parts=parts,
        overlay_streams=streams, overlay_filters=filters,
        use_cuda_filters=policy.use_cuda_filters, use_opencl=policy.use_opencl_overlays,
        metadata=inputs.char_metadata,
    )
    await _append_faces(renderer, inputs, request, placement, parts, streams, filters)
    current = append_overlay_chain(
        renderer=renderer, background_label=bg_label, current_label=current,
        streams=streams, filters=filters, force_cpu=request.force_cpu, parts=parts,
    )
    current, subtitle_png, subtitle_snippet = await append_subtitle_overlay(
        renderer=renderer, inputs=inputs, subtitle_text=request.subtitle_text,
        subtitle_line_config=request.subtitle_line_config,
        subtitle_png_path=request.subtitle_png_path, duration=request.duration,
        current_video_stream=current, policy=policy, force_cpu=request.force_cpu, parts=parts,
    )
    current = _append_screen_effects(renderer, request, current, parts)
    _append_final_video(renderer, policy, subtitle_snippet, current, parts)
    return ClipVideoGraph(parts, subtitle_png)
