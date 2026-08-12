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
from .clip_image_input import append_looped_image_input

if TYPE_CHECKING:
    from .renderer import VideoRenderer

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}


def _to_offset_expr(value: Any) -> str:
    if isinstance(value, (int, float)):
        return str(value)
    return "0" if value is None else str(value)


def _media_speed(value: Any) -> float:
    try:
        speed = float(value)
    except Exception:
        speed = 1.0
    return max(0.25, min(4.0, speed))


@dataclass(frozen=True)
class BackgroundInputSettings:
    fit: str
    fill_color: str
    anchor: str
    offset_x: str
    offset_y: str

    @property
    def position(self) -> Dict[str, str]:
        return {"x": self.offset_x, "y": self.offset_y}

    @property
    def requires_cpu_fit(self) -> bool:
        return self.fit != BACKGROUND_FIT_STRETCH or self.offset_x != "0" or self.offset_y != "0"


@dataclass(frozen=True)
class InsertInput:
    ffmpeg_index: int = -1
    audio_index: int = -1
    is_image: bool = False
    speed: float = 1.0
    path: Optional[Path] = None


@dataclass
class ClipInputCollection:
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


def _background_settings(renderer: "VideoRenderer", config: Dict[str, Any]) -> BackgroundInputSettings:
    video_defaults = renderer.config.get("video", {}) or {}
    bg_defaults = renderer.config.get("background", {}) or {}
    fit = str(config.get("fit", video_defaults.get("background_fit", BACKGROUND_FIT_STRETCH))).lower()
    fill = str(config.get("fill_color", bg_defaults.get("fill_color", DEFAULT_BACKGROUND_FILL_COLOR)) or DEFAULT_BACKGROUND_FILL_COLOR)
    anchor = str(config.get("anchor", bg_defaults.get("anchor", DEFAULT_BACKGROUND_ANCHOR)) or DEFAULT_BACKGROUND_ANCHOR)
    position = config.get("position")
    if not isinstance(position, dict):
        position = bg_defaults.get("position")
    if not isinstance(position, dict):
        position = {}
    return BackgroundInputSettings(
        fit=fit,
        fill_color=fill,
        anchor=anchor,
        offset_x=_to_offset_expr(position.get("x")),
        offset_y=_to_offset_expr(position.get("y")),
    )


async def _normalize_background(
    renderer: "VideoRenderer", path: Path, settings: BackgroundInputSettings
) -> Path:
    key_data = {
        "input_path": str(path.resolve()),
        "video_params": renderer.video_params.__dict__,
        "audio_params": renderer.audio_params.__dict__,
    }

    async def creator(temp_output_path: Path) -> Path:
        return await normalize_media(
            input_path=path, video_params=renderer.video_params,
            audio_params=renderer.audio_params, cache_manager=renderer.cache_manager,
            ffmpeg_path=renderer.ffmpeg_path, fit_mode=settings.fit,
            fill_color=settings.fill_color, anchor=settings.anchor,
            position=settings.position, scale_flags=renderer.scale_flags,
        )

    result = await renderer.cache_manager.get_or_create(
        key_data=key_data, file_name="normalized_bg", extension="mp4", creator_func=creator
    )
    if result is None:
        raise PipelineError(f"Failed to normalize background video: {path}")
    return result


async def _append_background_input(
    renderer: "VideoRenderer", config: Dict[str, Any], cmd: List[str], duration: float
) -> tuple[Path, BackgroundInputSettings]:
    path_value = config.get("path")
    if not path_value:
        raise ValueError("Background path is missing.")
    path = Path(path_value)
    settings = _background_settings(renderer, config)
    if config.get("type") != "video":
        append_looped_image_input(
            cmd, path, duration=duration, fps=renderer.video_params.fps
        )
        return path, settings
    try:
        normalized_hint = bool(config.get("normalized", False))
        temp_scene_bg = path.parent.resolve() == renderer.temp_dir.resolve() and path.name.startswith("scene_bg_")
        if not (normalized_hint or temp_scene_bg):
            try:
                path = await _normalize_background(renderer, path, settings)
            except Exception as exc:
                print(f"[Warning] Could not inspect/normalize BG video {path.name}: {exc}. Using as-is.")
        cmd.extend(["-ss", str(config.get("start_time", 0.0)), "-i", str(path)])
    except Exception as exc:
        logger.warning("Failed to process background video: %s. Falling back to image loop.", exc)
        append_looped_image_input(
            cmd, path, duration=duration, fps=renderer.video_params.fps
        )
    return path, settings


def _append_speech_input(audio_path: Path, cmd: List[str], layers: List[Dict[str, Any]]) -> int:
    cmd.extend(["-i", str(audio_path)])
    index = len(layers)
    layers.append({"type": "audio", "index": index})
    return index


async def _append_insert_input(
    renderer: "VideoRenderer", config: Optional[Dict[str, Any]],
    cmd: List[str], layers: List[Dict[str, Any]], duration: float,
) -> InsertInput:
    if not config:
        return InsertInput()
    path = Path(config["path"])
    speed = _media_speed(config.get("speed", 1.0))
    is_image = path.suffix.lower() in _IMAGE_SUFFIXES
    if is_image:
        append_looped_image_input(
            cmd, path.resolve(), duration=duration, fps=renderer.video_params.fps
        )
    else:
        try:
            if not bool(config.get("normalized", False)):
                path = await normalize_media(
                    input_path=path, video_params=renderer.video_params,
                    audio_params=renderer.audio_params, cache_manager=renderer.cache_manager,
                    ffmpeg_path=renderer.ffmpeg_path,
                )
        except Exception as exc:
            logger.warning("Could not inspect/normalize insert video %s: %s. Using as-is.", path.name, exc)
        cmd.extend(["-i", str(path)])
    ffmpeg_index = len(layers)
    layers.append({"type": "video", "index": ffmpeg_index})
    audio_index = ffmpeg_index if not is_image and await has_audio_stream(str(path)) else -1
    return InsertInput(ffmpeg_index, audio_index, is_image, speed, path)


def _append_overlay_inputs(
    overlays: Optional[List[Dict[str, Any]]], cmd: List[str],
    layers: List[Dict[str, Any]], *, audio: bool,
    duration: float, fps: float,
) -> List[Dict[str, Any]]:
    collected: List[Dict[str, Any]] = []
    for overlay in overlays or []:
        if not isinstance(overlay, dict):
            continue
        path_value = overlay.get("path") if audio else (overlay.get("path") or overlay.get("src"))
        if not path_value:
            continue
        path = Path(str(path_value))
        if audio:
            cmd.extend(["-i", str(path)])
        else:
            append_looped_image_input(
                cmd, path.resolve(), duration=duration, fps=fps
            )
        index = len(layers)
        layers.append({"type": "audio" if audio else "video", "index": index})
        entry = dict(overlay)
        entry["_ff_idx"] = index
        collected.append(entry)
    return collected


async def collect_clip_inputs(
    *, renderer: "VideoRenderer", audio_path: Path,
    duration: float,
    background_config: Dict[str, Any], characters_config: List[Dict[str, Any]],
    insert_config: Optional[Dict[str, Any]] = None,
    image_layer_overlays: Optional[List[Dict[str, Any]]] = None,
    extra_audio_overlays: Optional[List[Dict[str, Any]]] = None,
) -> ClipInputCollection:
    """Resolve inputs in legacy FFmpeg index order."""
    cmd = [renderer.ffmpeg_path, "-y", "-hide_banner", "-loglevel", "warning", *get_profile_flags()]
    cmd.extend(renderer.ffmpeg_thread_flags())
    layers: List[Dict[str, Any]] = []
    bg_path, bg = await _append_background_input(
        renderer, background_config, cmd, duration
    )
    layers.append({"type": "video", "index": len(layers)})
    speech_index = _append_speech_input(audio_path, cmd, layers)
    insert = await _append_insert_input(
        renderer, insert_config, cmd, layers, duration
    )
    images = _append_overlay_inputs(
        image_layer_overlays, cmd, layers, audio=False,
        duration=duration, fps=renderer.video_params.fps,
    )
    audio_overlays = _append_overlay_inputs(
        extra_audio_overlays, cmd, layers, audio=True,
        duration=duration, fps=renderer.video_params.fps,
    )
    chars = await collect_character_inputs(
        renderer=renderer, characters_config=characters_config, cmd=cmd,
        input_layers=layers, duration=duration,
    )
    return ClipInputCollection(
        cmd=cmd, input_layers=layers, background_path=bg_path,
        background_fit=bg.fit, fill_color=bg.fill_color, background_anchor=bg.anchor,
        offset_x_expr=bg.offset_x, offset_y_expr=bg.offset_y, position_exprs=bg.position,
        requires_cpu_fit=bg.requires_cpu_fit, speech_audio_index=speech_index,
        insert_ffmpeg_index=insert.ffmpeg_index, insert_audio_index=insert.audio_index,
        insert_is_image=insert.is_image, insert_speed=insert.speed, insert_path=insert.path,
        image_layer_inputs=images, extra_audio_inputs=audio_overlays,
        character_indices=chars.indices, char_effective_scale=chars.effective_scales,
        any_character_visible=chars.any_visible, char_metadata=chars.metadata,
    )
