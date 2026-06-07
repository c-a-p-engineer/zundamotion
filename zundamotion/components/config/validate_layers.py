"""Image layer configuration validation."""

from pathlib import Path
from typing import Any, Dict

from ...exceptions import ValidationError
from .validate_common import ANCHOR_CHOICES, IMAGE_LAYER_TRANSITION_TYPES


def _validate_image_layer_transition(
    transition: Dict[str, Any], container_id: str, label: str
) -> None:
    if not isinstance(transition, dict):
        raise ValidationError(
            f"Image layer transition '{label}' for {container_id} must be a dictionary."
        )
    transition_type = transition.get("type")
    if (
        not isinstance(transition_type, str)
        or transition_type not in IMAGE_LAYER_TRANSITION_TYPES
    ):
        raise ValidationError(
            f"Image layer transition '{label}' for {container_id} must be one of {sorted(IMAGE_LAYER_TRANSITION_TYPES)}."
        )
    if transition_type != "none":
        duration = transition.get("duration")
        if not isinstance(duration, (int, float)) or duration <= 0:
            raise ValidationError(
                f"Image layer transition '{label}' for {container_id} must have a positive 'duration'."
            )


def _validate_image_layers(line: Dict[str, Any], container_id: str) -> None:
    image_layers = line.get("image_layers")
    if image_layers is None:
        return
    if not isinstance(image_layers, list):
        raise ValidationError(f"Image layers for {container_id} must be a list.")
    for index, entry in enumerate(image_layers):
        _validate_image_layer_entry(entry, container_id, index)


def _validate_image_layer_entry(entry: Any, container_id: str, index: int) -> None:
    if not isinstance(entry, dict):
        raise ValidationError(
            f"Image layer entry at {container_id}, index {index} must be a dictionary."
        )
    if "show" in entry:
        _validate_show(entry.get("show"), container_id, index)
        return
    if "hide" in entry:
        _validate_hide(entry.get("hide"), container_id, index)
        return
    raise ValidationError(
        f"Image layer entry at {container_id}, index {index} must contain 'show' or 'hide'."
    )


def _validate_show(show: Any, container_id: str, index: int) -> None:
    if not isinstance(show, dict):
        raise ValidationError(
            f"Image layer show at {container_id}, index {index} must be a dictionary."
        )
    layer_id = show.get("id")
    if not isinstance(layer_id, str) or not layer_id:
        raise ValidationError(
            f"Image layer show at {container_id}, index {index} requires a string 'id'."
        )
    _validate_show_source(show, layer_id, container_id)
    _validate_show_placement(show, layer_id, container_id)
    _validate_show_runtime(show, layer_id, container_id)
    _validate_show_transition(show.get("transition"), layer_id, container_id)


def _validate_show_source(show: Dict[str, Any], layer_id: str, container_id: str) -> None:
    path = show.get("path")
    if not isinstance(path, str) or not path:
        raise ValidationError(
            f"Image layer '{layer_id}' show in {container_id} requires a string 'path'."
        )
    if not Path(path).is_file():
        raise ValidationError(
            f"Image layer '{layer_id}' show path '{path}' not found for {container_id}."
        )


def _validate_show_placement(show: Dict[str, Any], layer_id: str, container_id: str) -> None:
    anchor = show.get("anchor")
    if anchor is not None and (
        not isinstance(anchor, str) or anchor not in ANCHOR_CHOICES
    ):
        raise ValidationError(
            f"Image layer '{layer_id}' show anchor for {container_id} must be one of {sorted(ANCHOR_CHOICES)}."
        )
    position = show.get("position")
    if position is not None:
        if not isinstance(position, dict):
            raise ValidationError(
                f"Image layer '{layer_id}' show position for {container_id} must be a dictionary."
            )
        for axis in ("x", "y"):
            value = position.get(axis)
            if value is not None and not isinstance(value, (int, float, str)):
                raise ValidationError(
                    f"Image layer '{layer_id}' show position '{axis}' for {container_id} must be a number or string."
                )
    _validate_show_scale(show.get("scale"), layer_id, container_id)


def _validate_show_scale(scale: Any, layer_id: str, container_id: str) -> None:
    if scale is None:
        return
    if isinstance(scale, (int, float)):
        if float(scale) <= 0:
            raise ValidationError(
                f"Image layer '{layer_id}' show scale for {container_id} must be positive."
            )
        return
    if not isinstance(scale, dict):
        raise ValidationError(
            f"Image layer '{layer_id}' show scale for {container_id} must be a number or dictionary."
        )
    for dimension in ("w", "h"):
        value = scale.get(dimension)
        if value is not None and (not isinstance(value, (int, float)) or value <= 0):
            raise ValidationError(
                f"Image layer '{layer_id}' show scale '{dimension}' for {container_id} must be a positive number."
            )
    keep_aspect = scale.get("keep_aspect")
    if keep_aspect is not None and not isinstance(keep_aspect, bool):
        raise ValidationError(
            f"Image layer '{layer_id}' show scale 'keep_aspect' for {container_id} must be a boolean."
        )


def _validate_show_runtime(show: Dict[str, Any], layer_id: str, container_id: str) -> None:
    opacity = show.get("opacity")
    if opacity is not None and (
        not isinstance(opacity, (int, float)) or not (0.0 <= opacity <= 1.0)
    ):
        raise ValidationError(
            f"Image layer '{layer_id}' show opacity for {container_id} must be between 0.0 and 1.0."
        )
    opaque = show.get("opaque")
    if opaque is not None and not isinstance(opaque, bool):
        raise ValidationError(
            f"Image layer '{layer_id}' show opaque for {container_id} must be a boolean."
        )
    fps = show.get("fps")
    if fps is not None and (not isinstance(fps, int) or fps <= 0):
        raise ValidationError(
            f"Image layer '{layer_id}' show fps for {container_id} must be a positive integer."
        )
    _validate_show_effects(show.get("effects"), layer_id, container_id)


def _validate_show_effects(effects: Any, layer_id: str, container_id: str) -> None:
    if effects is None:
        return
    if not isinstance(effects, list):
        raise ValidationError(
            f"Image layer '{layer_id}' show effects for {container_id} must be a list."
        )
    for index, effect in enumerate(effects):
        if isinstance(effect, str):
            continue
        if not isinstance(effect, dict):
            raise ValidationError(
                f"Image layer '{layer_id}' show effects[{index}] for {container_id} must be a string or dictionary."
            )
        if not isinstance(effect.get("type"), str) or not effect.get("type"):
            raise ValidationError(
                f"Image layer '{layer_id}' show effects[{index}] for {container_id} requires a string 'type'."
            )


def _validate_show_transition(transition: Any, layer_id: str, container_id: str) -> None:
    if transition is None:
        return
    if not isinstance(transition, dict):
        raise ValidationError(
            f"Image layer '{layer_id}' show transition for {container_id} must be a dictionary."
        )
    for label in ("in", "out"):
        if transition.get(label) is not None:
            _validate_image_layer_transition(transition[label], container_id, label)


def _validate_hide(hide: Any, container_id: str, index: int) -> None:
    if not isinstance(hide, dict):
        raise ValidationError(
            f"Image layer hide at {container_id}, index {index} must be a dictionary."
        )
    layer_id = hide.get("id")
    if not isinstance(layer_id, str) or not layer_id:
        raise ValidationError(
            f"Image layer hide at {container_id}, index {index} requires a string 'id'."
        )
    transition = hide.get("transition")
    if transition is None:
        return
    if not isinstance(transition, dict):
        raise ValidationError(
            f"Image layer '{layer_id}' hide transition for {container_id} must be a dictionary."
        )
    if transition.get("out") is not None:
        _validate_image_layer_transition(transition["out"], container_id, "out")
