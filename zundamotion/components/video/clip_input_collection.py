"""Collect FFmpeg inputs for one rendered clip without building filter graphs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from ...exceptions import PipelineError
from ...utils.ffmpeg_audio import has_audio_stream
from ...utils.ffmpeg_hw import get_profile_flags
from ...utils.ffmpeg_ops import (
    BACKGROUND_FIT_STRETCH,
    DEFAULT_BACKGROUND_ANCHOR,
    DEFAULT_BACKGROUND_FILL_COLOR,
    normalize_media,
)
from ...utils.logger import logger
from .clip.characters import collect_character_inputs

if TYPE_CHECKING:
    from .renderer import VideoRenderer


_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}


def _to_offset_expr(value: Any) -> str:
    if isinstance(value, (int, float)):
        return str(value)
    if value is None:
        return "0"
    return str(value)


def _media_speed(value: Any) -> float:
    try:
        speed = float(value)
    except Exception:
        speed = 1.0
    return max(0.25, min(4.0, speed))


@dataclass
class ClipInputCollection:
    """Resolved input arguments and indices consumed by later clip stages."""

    cmd: List[str]
    input_layers: List[Dict[str, Any]]
    background_path: Path
    background_fit: str
    fill_color: str
    background_anchor: str
    offset_x_expr: str
    offset_y_expr: str
    position_exprs: Dict[str, str]
    requires_cpu_fit: bool
    speech_audio_index: int
    insert_ffmpeg_index: int
    insert_audio_index: int
    insert_is_image: bool
    insert_speed: float
    insert_path: Optional[Path]
    image_layer_inputs: List[Dict[str, Any]]
    extra_audio_inputs: List[Dict[str, Any]]
    character_indices: List[int]
    char_effective_scale: List[float]
    any_character_visible: bool
    char_metadata: List[Dict[str, Any]]


async def collect_clip_inputs(
    *,
    renderer: "VideoRenderer",
    audio_path: Path,
    background_config: Dict[str, Any],
    characters_config: List[Dict[str, Any]],
    insert_config: Optional[Dict[str, Any]] = None,
    image_layer_overlays: Optional[List[Dict[str, Any]]] = None,
    extra_audio_overlays: Optional[List[Dict[str, Any]]] = None,
) -> ClipInputCollection:
    """Resolve and append every clip input while preserving legacy input ordering."""

    cmd: List[str] = [
        renderer.ffmpeg_path,
        "-y",
        "-hide_banner",
        "-loglevel",
        "warning",
        *get_profile_flags(),
    ]
    cmd.extend(renderer.ffmpeg_thread_flags())
    input_layers: List[Dict[str, Any]] = []

    bg_path_str = background_config.get("path")
    if not bg_path_str:
        raise ValueError("Background path is missing.")
    bg_path = Path(bg_path_str)

    video_defaults = renderer.config.get("video", {}) or {}
    background_defaults = renderer.config.get("background", {}) or {}
    background_fit = str(
        background_config.get(
            "fit",
            video_defaults.get("background_fit", BACKGROUND_FIT_STRETCH),
        )
    ).lower()
    fill_color = str(
        background_config.get(
            "fill_color",
            background_defaults.get("fill_color", DEFAULT_BACKGROUND_FILL_COLOR),
        )
        or DEFAULT_BACKGROUND_FILL_COLOR
    )
    background_anchor = str(
        background_config.get(
            "anchor",
            background_defaults.get("anchor", DEFAULT_BACKGROUND_ANCHOR),
        )
        or DEFAULT_BACKGROUND_ANCHOR
    )
    raw_position = background_config.get("position")
    if not isinstance(raw_position, dict):
        raw_position = background_defaults.get("position")
        if not isinstance(raw_position, dict):
            raw_position = {}
    offset_x_expr = _to_offset_expr(raw_position.get("x"))
    offset_y_expr = _to_offset_expr(raw_position.get("y"))
    position_exprs = {"x": offset_x_expr, "y": offset_y_expr}
    requires_cpu_fit = (
        background_fit != BACKGROUND_FIT_STRETCH
        or offset_x_expr != "0"
        or offset_y_expr != "0"
    )

    if background_config.get("type") == "video":
        try:
            normalized_hint = bool(background_config.get("normalized", False))
            is_temp_scene_bg = (
                bg_path.parent.resolve() == renderer.temp_dir.resolve()
                and bg_path.name.startswith("scene_bg_")
            )
            should_skip_normalize = normalized_hint or is_temp_scene_bg
            if not should_skip_normalize:
                try:
                    key_data = {
                        "input_path": str(bg_path.resolve()),
                        "video_params": renderer.video_params.__dict__,
                        "audio_params": renderer.audio_params.__dict__,
                    }

                    async def _normalize_bg_creator(temp_output_path: Path) -> Path:
                        return await normalize_media(
                            input_path=bg_path,
                            video_params=renderer.video_params,
                            audio_params=renderer.audio_params,
                            cache_manager=renderer.cache_manager,
                            ffmpeg_path=renderer.ffmpeg_path,
                            fit_mode=background_fit,
                            fill_color=fill_color,
                            anchor=background_anchor,
                            position=position_exprs,
                            scale_flags=renderer.scale_flags,
                        )

                    bg_path_result = await renderer.cache_manager.get_or_create(
                        key_data=key_data,
                        file_name="normalized_bg",
                        extension="mp4",
                        creator_func=_normalize_bg_creator,
                    )
                    if bg_path_result is None:
                        raise PipelineError(
                            f"Failed to normalize background video: {bg_path}"
                        )
                    bg_path = bg_path_result
                except Exception as exc:
                    print(
                        f"[Warning] Could not inspect/normalize BG video {bg_path.name}: {exc}. Using as-is."
                    )
            cmd.extend(
                [
                    "-ss",
                    str(background_config.get("start_time", 0.0)),
                    "-i",
                    str(bg_path),
                ]
            )
        except Exception as exc:
            logger.warning(
                "Failed to process background video: %s. Falling back to image loop.",
                exc,
            )
            cmd.extend(["-loop", "1", "-i", str(bg_path)])
    else:
        cmd.extend(["-loop", "1", "-i", str(bg_path)])
    input_layers.append({"type": "video", "index": len(input_layers)})

    cmd.extend(["-i", str(audio_path)])
    speech_audio_index = len(input_layers)
    input_layers.append({"type": "audio", "index": speech_audio_index})

    insert_ffmpeg_index = -1
    insert_audio_index = -1
    insert_is_image = False
    insert_speed = 1.0
    insert_path: Optional[Path] = None
    if insert_config:
        insert_path = Path(insert_config["path"])
        insert_speed = _media_speed(insert_config.get("speed", 1.0))
        insert_is_image = insert_path.suffix.lower() in _IMAGE_SUFFIXES
        if not insert_is_image:
            try:
                if not bool(insert_config.get("normalized", False)):
                    insert_path = await normalize_media(
                        input_path=insert_path,
                        video_params=renderer.video_params,
                        audio_params=renderer.audio_params,
                        cache_manager=renderer.cache_manager,
                        ffmpeg_path=renderer.ffmpeg_path,
                    )
            except Exception as exc:
                logger.warning(
                    "Could not inspect/normalize insert video %s: %s. Using as-is.",
                    insert_path.name,
                    exc,
                )
            cmd.extend(["-i", str(insert_path)])
        else:
            cmd.extend(["-loop", "1", "-i", str(insert_path.resolve())])
        insert_ffmpeg_index = len(input_layers)
        input_layers.append({"type": "video", "index": insert_ffmpeg_index})
        if not insert_is_image and await has_audio_stream(str(insert_path)):
            insert_audio_index = insert_ffmpeg_index

    image_layer_inputs: List[Dict[str, Any]] = []
    for overlay in image_layer_overlays or []:
        if not isinstance(overlay, dict):
            continue
        path_str = overlay.get("path") or overlay.get("src")
        if not path_str:
            continue
        image_path = Path(path_str)
        cmd.extend(["-loop", "1", "-i", str(image_path.resolve())])
        ff_idx = len(input_layers)
        input_layers.append({"type": "video", "index": ff_idx})
        entry = dict(overlay)
        entry["_ff_idx"] = ff_idx
        image_layer_inputs.append(entry)

    extra_audio_inputs: List[Dict[str, Any]] = []
    for overlay in extra_audio_overlays or []:
        if not isinstance(overlay, dict):
            continue
        path_str = overlay.get("path")
        if not path_str:
            continue
        audio_overlay_path = Path(str(path_str))
        cmd.extend(["-i", str(audio_overlay_path)])
        ff_idx = len(input_layers)
        input_layers.append({"type": "audio", "index": ff_idx})
        entry = dict(overlay)
        entry["_ff_idx"] = ff_idx
        extra_audio_inputs.append(entry)

    char_inputs = await collect_character_inputs(
        renderer=renderer,
        characters_config=characters_config,
        cmd=cmd,
        input_layers=input_layers,
    )

    return ClipInputCollection(
        cmd=cmd,
        input_layers=input_layers,
        background_path=bg_path,
        background_fit=background_fit,
        fill_color=fill_color,
        background_anchor=background_anchor,
        offset_x_expr=offset_x_expr,
        offset_y_expr=offset_y_expr,
        position_exprs=position_exprs,
        requires_cpu_fit=requires_cpu_fit,
        speech_audio_index=speech_audio_index,
        insert_ffmpeg_index=insert_ffmpeg_index,
        insert_audio_index=insert_audio_index,
        insert_is_image=insert_is_image,
        insert_speed=insert_speed,
        insert_path=insert_path,
        image_layer_inputs=image_layer_inputs,
        extra_audio_inputs=extra_audio_inputs,
        character_indices=char_inputs.indices,
        char_effective_scale=char_inputs.effective_scales,
        any_character_visible=char_inputs.any_visible,
        char_metadata=char_inputs.metadata,
    )
