"""Foreground overlay configuration validation."""

from pathlib import Path
from typing import Any, Dict

from ...exceptions import ValidationError
from ...utils.filter_presets import VIDEO_FILTER_PRESETS


def _validate_fg_overlays(container: Dict[str, Any], container_id: str) -> None:
    overlays = container.get("fg_overlays")
    if overlays is None:
        return
    if not isinstance(overlays, list):
        raise ValidationError(f"Foreground overlays for {container_id} must be a list.")
    for index, overlay in enumerate(overlays):
        _validate_fg_overlay(overlay, container_id, index)


def _validate_fg_overlay(overlay: Any, container_id: str, index: int) -> None:
    if not isinstance(overlay, dict):
        raise ValidationError(
            f"Foreground overlay at {container_id}, index {index} must be a dictionary."
        )
    overlay_id = overlay.get("id", f"fg_{index}")
    _validate_source(overlay, overlay_id, container_id)
    _validate_filter(overlay, overlay_id, container_id)
    _validate_mode(overlay, overlay_id, container_id)
    _validate_placement(overlay, overlay_id, container_id)
    _validate_timing(overlay, overlay_id, container_id)
    _validate_effects(overlay.get("effects"), overlay_id, container_id)


def _validate_source(overlay: Dict[str, Any], overlay_id: str, container_id: str) -> None:
    source = overlay.get("src")
    if not source or not isinstance(source, str):
        raise ValidationError(
            f"Foreground overlay '{overlay_id}' in {container_id} must have a string 'src' path."
        )
    if not Path(source).is_file():
        raise ValidationError(
            f"Foreground overlay '{overlay_id}' source file '{source}' not found for {container_id}."
        )


def _validate_filter(overlay: Dict[str, Any], overlay_id: str, container_id: str) -> None:
    video_filter = overlay.get("filter")
    if video_filter is None:
        return
    if not isinstance(video_filter, str):
        raise ValidationError(
            f"Foreground overlay '{overlay_id}' in {container_id} filter must be a string."
        )
    if video_filter.strip().lower() not in VIDEO_FILTER_PRESETS:
        raise ValidationError(
            f"Foreground overlay '{overlay_id}' in {container_id} has invalid filter '{video_filter}'."
        )


def _validate_mode(overlay: Dict[str, Any], overlay_id: str, container_id: str) -> None:
    mode = overlay.get("mode")
    if mode not in {"overlay", "blend", "chroma", "alpha"}:
        raise ValidationError(
            f"Foreground overlay '{overlay_id}' in {container_id} has invalid mode '{mode}'."
        )
    if mode == "blend" and overlay.get("blend_mode") not in {
        "screen",
        "add",
        "multiply",
        "lighten",
    }:
        raise ValidationError(
            f"Foreground overlay '{overlay_id}' in {container_id} requires a valid 'blend_mode'."
        )
    if mode == "chroma":
        _validate_chroma(overlay.get("chroma"), overlay_id, container_id)


def _validate_chroma(chroma: Any, overlay_id: str, container_id: str) -> None:
    if not isinstance(chroma, dict):
        raise ValidationError(
            f"Foreground overlay '{overlay_id}' in {container_id} must have a 'chroma' dictionary."
        )
    key_color = chroma.get("key_color")
    if not isinstance(key_color, str) or not key_color.startswith("#"):
        raise ValidationError(
            f"Foreground overlay '{overlay_id}' in {container_id} has invalid chroma key_color '{key_color}'."
        )
    for key, default in (("similarity", 0.1), ("blend", 0.0)):
        value = chroma.get(key, default)
        if not isinstance(value, (int, float)) or not (0.0 <= value <= 1.0):
            raise ValidationError(
                f"Foreground overlay '{overlay_id}' in {container_id} chroma {key} must be between 0.0 and 1.0."
            )


def _validate_placement(overlay: Dict[str, Any], overlay_id: str, container_id: str) -> None:
    opacity = overlay.get("opacity")
    if opacity is not None and (
        not isinstance(opacity, (int, float)) or not (0.0 <= opacity <= 1.0)
    ):
        raise ValidationError(
            f"Foreground overlay '{overlay_id}' in {container_id} opacity must be between 0.0 and 1.0."
        )
    position = overlay.get("position", {})
    if not isinstance(position, dict):
        raise ValidationError(
            f"Foreground overlay '{overlay_id}' in {container_id} position must be a dictionary."
        )
    for axis in ("x", "y"):
        if not isinstance(position.get(axis, 0), (int, float)):
            raise ValidationError(
                f"Foreground overlay '{overlay_id}' in {container_id} position '{axis}' must be a number."
            )
    _validate_scale(overlay.get("scale", {}), overlay_id, container_id)


def _validate_scale(scale: Any, overlay_id: str, container_id: str) -> None:
    if isinstance(scale, (int, float)):
        if float(scale) <= 0:
            raise ValidationError(
                f"Foreground overlay '{overlay_id}' in {container_id} scale must be a positive number."
            )
        return
    if not isinstance(scale, dict):
        raise ValidationError(
            f"Foreground overlay '{overlay_id}' in {container_id} scale must be a dictionary or number."
        )
    for dimension in ("w", "h"):
        value = scale.get(dimension)
        if value is not None and (not isinstance(value, (int, float)) or value <= 0):
            raise ValidationError(
                f"Foreground overlay '{overlay_id}' in {container_id} scale '{dimension}' must be a positive number."
            )
    keep_aspect = scale.get("keep_aspect")
    if keep_aspect is not None and not isinstance(keep_aspect, bool):
        raise ValidationError(
            f"Foreground overlay '{overlay_id}' in {container_id} scale 'keep_aspect' must be a boolean."
        )


def _validate_timing(overlay: Dict[str, Any], overlay_id: str, container_id: str) -> None:
    timing = overlay.get("timing", {})
    if not isinstance(timing, dict):
        raise ValidationError(
            f"Foreground overlay '{overlay_id}' in {container_id} timing must be a dictionary."
        )
    start = timing.get("start", 0.0)
    if not isinstance(start, (int, float)) or start < 0:
        raise ValidationError(
            f"Foreground overlay '{overlay_id}' in {container_id} timing start must be non-negative."
        )
    duration = timing.get("duration")
    if duration is not None and (
        not isinstance(duration, (int, float)) or duration <= 0
    ):
        raise ValidationError(
            f"Foreground overlay '{overlay_id}' in {container_id} timing duration must be positive."
        )
    for key in ("loop",):
        value = timing.get(key)
        if value is not None and not isinstance(value, bool):
            raise ValidationError(
                f"Foreground overlay '{overlay_id}' in {container_id} timing {key} must be a boolean."
            )
    _validate_runtime_flags(overlay, overlay_id, container_id)


def _validate_runtime_flags(overlay: Dict[str, Any], overlay_id: str, container_id: str) -> None:
    fps = overlay.get("fps")
    if fps is not None and (not isinstance(fps, int) or fps <= 0):
        raise ValidationError(
            f"Foreground overlay '{overlay_id}' in {container_id} fps must be a positive integer."
        )
    preserve_color = overlay.get("preserve_color")
    if preserve_color is not None and not isinstance(preserve_color, bool):
        raise ValidationError(
            f"Foreground overlay '{overlay_id}' in {container_id} preserve_color must be a boolean."
        )


def _validate_effects(effects: Any, overlay_id: str, container_id: str) -> None:
    if effects is None:
        return
    if not isinstance(effects, list):
        raise ValidationError(
            f"Foreground overlay '{overlay_id}' in {container_id} effects must be a list."
        )
    for index, effect in enumerate(effects):
        if isinstance(effect, str):
            continue
        if not isinstance(effect, dict):
            raise ValidationError(
                f"Foreground overlay '{overlay_id}' in {container_id} effects[{index}] must be a string or dictionary."
            )
        if not isinstance(effect.get("type"), str) or not effect.get("type"):
            raise ValidationError(
                f"Foreground overlay '{overlay_id}' in {container_id} effects[{index}] requires a string 'type'."
            )
