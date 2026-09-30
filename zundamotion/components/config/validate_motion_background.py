"""Validation for strict multi-keyframe background pan/zoom authoring."""

from __future__ import annotations

import math
from typing import Any

from ...exceptions import ValidationError


_EFFECT_TYPES = {"bg:pan_zoom", "bg:ken_burns"}
_EASINGS = {"linear", "ease_in", "ease_out", "ease_in_out"}


def validate_background_motion_effects(effects: Any, label: str) -> None:
    """Validate only explicitly keyed background pan/zoom effects.

    Legacy effects without a non-empty keyframes value remain on the existing
    compatibility path and are intentionally not hardened here.
    """

    if not isinstance(effects, list):
        return

    for index, effect in enumerate(effects):
        if not isinstance(effect, dict):
            continue
        effect_type = str(effect.get("type", "")).strip().lower()
        if effect_type not in _EFFECT_TYPES:
            continue

        raw_keyframes = effect.get("keyframes")
        if not raw_keyframes:
            continue

        effect_label = f"{label}[{index}]"
        _validate_strict_effect(effect, effect_label)


def _validate_strict_effect(effect: dict[str, Any], label: str) -> None:
    allowed = {
        "type",
        "zoom",
        "pan",
        "focus",
        "fps",
        "from",
        "to",
        "start",
        "duration",
        "easing",
        "keyframes",
    }
    unknown = sorted(set(effect) - allowed)
    if unknown:
        raise ValidationError(
            f"{label} contains unsupported properties for multi-keyframe "
            f"background motion: {', '.join(unknown)}."
        )

    start = effect.get("start", 0.0)
    _number_in_range(start, f"{label}.start", minimum=0.0)

    if "duration" not in effect:
        raise ValidationError(
            f"{label}.duration is required when keyframes are used."
        )
    duration = _number_in_range(
        effect.get("duration"),
        f"{label}.duration",
        minimum=0.0,
        exclusive_minimum=True,
    )

    easing = effect.get("easing", "linear")
    _validate_easing(easing, f"{label}.easing")

    if "fps" in effect:
        _number_in_range(
            effect.get("fps"),
            f"{label}.fps",
            minimum=1.0,
            maximum=120.0,
        )

    _validate_zoom(effect.get("zoom"), effect, f"{label}.zoom")

    pan_value = effect.get("pan")
    pan_label = f"{label}.pan"
    if pan_value is None and "focus" in effect:
        pan_value = effect.get("focus")
        pan_label = f"{label}.focus"
    if pan_value is not None:
        _validate_pan_range(pan_value, pan_label)

    keyframes = effect.get("keyframes")
    if not isinstance(keyframes, list) or not keyframes:
        raise ValidationError(f"{label}.keyframes must be a non-empty list.")

    previous_at = 0.0
    for frame_index, frame in enumerate(keyframes):
        frame_label = f"{label}.keyframes[{frame_index}]"
        if not isinstance(frame, dict):
            raise ValidationError(f"{frame_label} must be a dictionary.")

        unknown_frame = sorted(set(frame) - {"at", "zoom", "pan", "easing"})
        if unknown_frame:
            raise ValidationError(
                f"{frame_label} contains unsupported properties: "
                + ", ".join(unknown_frame)
                + "."
            )
        if "at" not in frame:
            raise ValidationError(f"{frame_label}.at is required.")

        at = _number_in_range(
            frame.get("at"),
            f"{frame_label}.at",
            minimum=0.0,
            exclusive_minimum=True,
        )
        if at >= duration:
            raise ValidationError(
                f"{frame_label}.at must satisfy 0 < at < effect.duration."
            )
        if frame_index > 0 and at <= previous_at:
            raise ValidationError(
                f"{label}.keyframes times must be strictly increasing."
            )
        previous_at = at

        if "zoom" not in frame and "pan" not in frame:
            raise ValidationError(
                f"{frame_label} must define zoom or pan."
            )
        if "zoom" in frame:
            _number_in_range(
                frame.get("zoom"),
                f"{frame_label}.zoom",
                minimum=1.0,
                maximum=4.0,
            )
        if "pan" in frame:
            _validate_keyframe_pan(frame.get("pan"), f"{frame_label}.pan")
        if "easing" in frame:
            _validate_easing(frame.get("easing"), f"{frame_label}.easing")


def _validate_zoom(value: Any, effect: dict[str, Any], label: str) -> None:
    if value is None:
        for alias, alias_label in (("from", "from"), ("to", "to")):
            if alias in effect:
                _number_in_range(
                    effect.get(alias),
                    f"{label}.{alias_label}",
                    minimum=1.0,
                    maximum=4.0,
                )
        return

    if isinstance(value, dict):
        unknown = sorted(set(value) - {"from", "start", "to", "end"})
        if unknown:
            raise ValidationError(
                f"{label} contains unsupported properties: "
                + ", ".join(unknown)
                + "."
            )
        for key in ("from", "start", "to", "end"):
            if key in value:
                _number_in_range(
                    value.get(key),
                    f"{label}.{key}",
                    minimum=1.0,
                    maximum=4.0,
                )
        return

    _number_in_range(value, label, minimum=1.0, maximum=4.0)


def _validate_pan_range(value: Any, label: str) -> None:
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be a dictionary.")

    ranged = "from" in value or "to" in value
    allowed = {"from", "to"} if ranged else {"x", "y", "horizontal", "vertical"}
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValidationError(
            f"{label} contains unsupported properties: "
            + ", ".join(unknown)
            + "."
        )

    if ranged:
        for key in ("from", "to"):
            if key in value:
                _validate_focus(value.get(key), f"{label}.{key}")
        return
    _validate_focus(value, label)


def _validate_focus(value: Any, label: str) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be a dictionary.")

    unknown = sorted(set(value) - {"x", "y", "horizontal", "vertical"})
    if unknown:
        raise ValidationError(
            f"{label} contains unsupported properties: "
            + ", ".join(unknown)
            + "."
        )
    for key in ("x", "horizontal"):
        if key in value:
            _number_in_range(
                value.get(key),
                f"{label}.x",
                minimum=0.0,
                maximum=1.0,
            )
            break
    for key in ("y", "vertical"):
        if key in value:
            _number_in_range(
                value.get(key),
                f"{label}.y",
                minimum=0.0,
                maximum=1.0,
            )
            break


def _validate_keyframe_pan(value: Any, label: str) -> None:
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be a dictionary.")

    unknown = sorted(set(value) - {"x", "y"})
    if unknown:
        raise ValidationError(
            f"{label} contains unsupported properties: "
            + ", ".join(unknown)
            + "."
        )
    if not value:
        raise ValidationError(f"{label} must define x or y.")
    for axis in ("x", "y"):
        if axis in value:
            _number_in_range(
                value.get(axis),
                f"{label}.{axis}",
                minimum=0.0,
                maximum=1.0,
            )


def _validate_easing(value: Any, label: str) -> None:
    if value not in _EASINGS:
        raise ValidationError(
            f"{label} must be one of linear, ease_in, ease_out, ease_in_out."
        )


def _number_in_range(
    value: Any,
    label: str,
    *,
    minimum: float,
    maximum: float | None = None,
    exclusive_minimum: bool = False,
) -> float:
    if isinstance(value, bool):
        raise ValidationError(f"{label} must be a finite number.")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{label} must be a finite number.") from exc
    if not math.isfinite(result):
        raise ValidationError(f"{label} must be a finite number.")

    if exclusive_minimum:
        if result <= minimum:
            raise ValidationError(f"{label} must be greater than {minimum}.")
    elif result < minimum:
        if maximum is not None:
            raise ValidationError(
                f"{label} must be between {minimum} and {maximum}."
            )
        raise ValidationError(
            f"{label} must be greater than or equal to {minimum}."
        )

    if maximum is not None and result > maximum:
        raise ValidationError(
            f"{label} must be between {minimum} and {maximum}."
        )
    return result
