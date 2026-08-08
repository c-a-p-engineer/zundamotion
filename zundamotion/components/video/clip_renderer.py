"""Public clip-render entry point with compatibility helper exports."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING, Union

from .clip_audio_graph import _atempo_chain
from .clip_input_collection import _media_speed
from .clip_pipeline import ClipRenderRequest, run_clip_pipeline

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

    return await run_clip_pipeline(
        renderer,
        ClipRenderRequest(
            audio_path=audio_path,
            duration=duration,
            background_config=background_config,
            characters_config=characters_config,
            output_filename=output_filename,
            subtitle_text=subtitle_text,
            subtitle_line_config=subtitle_line_config,
            insert_config=insert_config,
            image_layer_overlays=image_layer_overlays,
            extra_audio_overlays=extra_audio_overlays,
            background_effects=background_effects,
            screen_effects=screen_effects,
            subtitle_png_path=subtitle_png_path,
            face_anim=face_anim,
            force_cpu=_force_cpu,
            audio_delay=audio_delay,
        ),
    )
