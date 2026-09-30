"""Strict validation for opt-in background pan/zoom Motion Core."""

from __future__ import annotations

import math
from typing import Any, Dict

from ...exceptions import ValidationError


EASINGS = {"linear", "ease_in", "ease_out", "ease_in_out"}
BACKGROUND_MOTION_TYPES = {"bg:pan_zoom", "bg:ken_burns"}


def validate_background_motion_effects(effects: Any, label: str) -> None:
    """Validate only recognized effects that opt into non-empty keyframes."""

    if not isinstance(effects, list):
        return

    for index, effect in enumerate(effects):
        if not isinstance(effect, dict):
            continue
        effect_type = str(effect.get("type", "")).strip().lower()
        if effect_type not in BACKGROUND_MOTION_TYPES:
            continue

        keyframes = effect.get("keyframes")
        if keyframes is None or keyframes == []:
            # Legacy path stays permissive and keeps existing clamp/fallback semantics.
            continue

        _validate_pan_zoom_motion(effect, f"{label}[{index}]")


def _validate_pan_zoom_motion(effect: Dict[str, Any], label: str) -> None:
    allowed = {
        "type",
        "zoom",
        "pan",
        "start",
        "duration",
        "easing",
        "keyframes",
        "fps",
    }
    unknown = sorted(set(effect) - allowed)
    if unknown:
        raise ValidationError(
            f"{label} contains unsupported properties for multi-keyframe motion: "
            + ", ".join(unknown)
            + "."
        )

    start = effect.get("start", 0.0)
    if not _is_finite_number(start) or float(start) < 0.0:
        raise ValidationError(
            f"{label}.start must be a finite number greater than or equal to 0."
        )

    if "duration" not in effect:
        raise ValidationError(
            f"{label}.duration is required when keyframes are used."
        )
    duration = effect.get("duration")
    if not _is_finite_number(duration) or float(duration) <= 0.0:
        raise ValidationError(
            f"{label}.duration must be a finite number greater than 0."
        )
    resolved_duration = float(duration)

    easing = effect.get("easing", "linear")
    if easing not in EASINGS:
        raise ValidationError(
            f"{label}.easing must be one of linear, ease_in, ease_out, ease_in_out."
        )

    fps = effect.get("fps")
    if fps is not None:
        if not _is_finite_number(fps) or not 1.0 <= float(fps) <= 120.0:
            raise ValidationError(
                f"{label}.fps must be a finite number between 1 and 120."
            )

    _validate_zoom_config(effect.get("zoom"), f"{label}.zoom")
    _validate_pan_config(effect.get("pan"), f"{label}.pan")

    keyframes = effect.get("keyframes")
    if not isinstance(keyframes, list):
        raise ValidationError(f"{label}.keyframes must be a list.")
    if not keyframes:
        return

    previous_at = 0.0
    for index, frame in enumerate(keyframes):
        frame_label = f"{label}.keyframes[{index}]"
        if not isinstance(frame, dict):
            raise ValidationError(f"{frame_label} must be a dictionary.")

        unknown_frame = sorted(set(frame) - {"at", "zoom", "pan", "easing"})
        if unknown_frame:
            raise ValidationError(
                f"{frame_label} contains unsupported properties: "
                + ", ".join(unknown_frame)
                + "."
            )

        if "at" not in frame or not _is_finite_number(frame.get("at")):
            raise ValidationError(f"{frame_label}.at must be a finite number.")
        at = float(frame["at"])
        if not 0.0 < at < resolved_duration:
            raise ValidationError(
                f"{frame_label}.at must be greater than 0 and less than {label}.duration."
            )
        if index > 0 and at <= previous_at:
            raise ValidationError(
                f"{label}.keyframes times must be strictly increasing."
            )
        previous_at = at

        has_property = False
        if "zoom" in frame:
            _validate_zoom_value(frame["zoom"], f"{frame_label}.zoom")
            has_property = True

        if "pan" in frame:
            pan = frame["pan"]
            if not isinstance(pan, dict):
                raise ValidationError(f"{frame_label}.pan must be a dictionary.")
            unknown_pan = sorted(set(pan) - {"x", "y"})
            if unknown_pan:
                raise ValidationError(
                    f"{frame_label}.pan contains unsupported properties: "
                    + ", ".join(unknown_pan)
                    + "."
                )
            if not any(axis in pan for axis in ("x", "y")):
                raise ValidationError(f"{frame_label}.pan must define x or y.")
            for axis in ("x", "y"):
                if axis in pan:
                    _validate_focus_value(pan[axis], f"{frame_label}.pan.{axis}")
            has_property = True

        if not has_property:
            raise ValidationError(f"{frame_label} must define zoom or pan.")

        frame_easing = frame.get("easing")
        if frame_easing is not None and frame_easing not in EASINGS:
            raise ValidationError(
                f"{frame_label}.easing must be one of "
                "linear, ease_in, ease_out, ease_in_out."
            )


def _validate_zoom_config(value: Any, label: str) -> None:
    if value is None:
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
                _validate_zoom_value(value[key], f"{label}.{key}")
        return
    _validate_zoom_value(value, label)


def _validate_pan_config(value: Any, label: str) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be a dictionary.")

    if "from" in value or "to" in value:
        unknown = sorted(set(value) - {"from", "to"})
        if unknown:
            raise ValidationError(
                f"{label} contains unsupported properties: "
                + ", ".join(unknown)
                + "."
            )
        for key in ("from", "to"):
            if key in value:
                _validate_focus_mapping(value[key], f"{label}.{key}")
        return

    _validate_focus_mapping(value, label, allow_empty=True)


def _validate_focus_mapping(
    value: Any,
    label: str,
    *,
    allow_empty: bool = False,
) -> None:
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be a dictionary.")
    unknown = sorted(set(value) - {"x", "y"})
    if unknown:
        raise ValidationError(
            f"{label} contains unsupported properties: "
            + ", ".join(unknown)
            + "."
        )
    if not value and allow_empty:
        return
    if not any(axis in value for axis in ("x", "y")):
        raise ValidationError(f"{label} must define x or y.")
    for axis in ("x", "y"):
        if axis in value:
            _validate_focus_value(value[axis], f"{label}.{axis}")


def _validate_focus_value(value: Any, label: str) -> None:
    if not _is_finite_number(value):
        raise ValidationError(f"{label} must be a finite number.")
    if not 0.0 <= float(value) <= 1.0:
        raise ValidationError(f"{label} must be between 0.0 and 1.0.")


def _validate_zoom_value(value: Any, label: str) -> None:
    if not _is_finite_number(value):
        raise ValidationError(f"{label} must be a finite number.")
    if not 1.0 <= float(value) <= 4.0:
        raise ValidationError(f"{label} must be between 1.0 and 4.0.")


def _is_finite_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if not isinstance(value, (int, float)):
        return False
    return math.isfinite(float(value))
