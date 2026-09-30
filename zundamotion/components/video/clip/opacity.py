"""Character opacity Motion Core helpers.

Opacity owns scalar track lowering and alpha-plane FFmpeg filter snippets.
It does not own character persistence or lifecycle fade timing.
"""

from __future__ import annotations

import math
from typing import Any, Mapping

from ....exceptions import ValidationError
from .motion_track import build_motion_track, build_track_expression


_EPSILON = 1e-12


def opacity_requested(character_config: Mapping[str, Any]) -> bool:
    """Return whether a character explicitly requests opacity handling."""

    if "opacity" in character_config:
        return True

    move = character_config.get("move")
    if not isinstance(move, Mapping) or move.get("enabled") is False:
        return False
    raw_from = move.get("from")
    if isinstance(raw_from, Mapping) and "opacity" in raw_from:
        return True
    keyframes = move.get("keyframes")
    return isinstance(keyframes, list) and any(
        isinstance(frame, Mapping) and "opacity" in frame for frame in keyframes
    )


def build_opacity_expression(
    *,
    move_config: Any,
    to_opacity: Any,
    time_base: float = 0.0,
) -> tuple[str, bool]:
    """Build a static or MotionTrack-backed alpha multiplier expression."""

    final_opacity = _opacity_value(to_opacity, "character opacity")
    static_expr = f"{final_opacity:.6f}"

    if not isinstance(move_config, Mapping) or move_config.get("enabled") is False:
        return static_expr, True

    raw_from = move_config.get("from")
    keyframes = _keyframes(move_config)
    has_waypoint = any("opacity" in frame for frame in keyframes)
    has_start = isinstance(raw_from, Mapping) and "opacity" in raw_from
    if not has_waypoint and not has_start:
        return static_expr, True
    if not has_start:
        raise ValidationError(
            "Character move.from.opacity is required when opacity keyframes are used."
        )

    start = _finite_float(move_config.get("start", 0.0), "move.start")
    if start < 0.0:
        raise ValidationError(
            "Character move.start must be greater than or equal to 0."
        )
    duration = _finite_float(move_config.get("duration", 0.3), "move.duration")
    if duration <= 0.0:
        raise ValidationError("Character move.duration must be greater than 0.")

    track = build_motion_track(
        property_name="opacity",
        start_time=start + float(time_base),
        duration=duration,
        start_value=_opacity_value(raw_from["opacity"], "move.from.opacity"),
        final_value=final_opacity,
        waypoints=keyframes,
        default_easing=str(move_config.get("easing", "linear")),
    )
    for index, frame in enumerate(track.keyframes):
        _opacity_value(frame.value, f"resolved opacity keyframe {index}")
    return (
        build_track_expression(
            track,
            lambda value: f"{value:.6f}",
            time_variable="T",
        ),
        True,
    )


def build_alpha_multiplier_filter_parts(
    *,
    input_label: str,
    output_label: str,
    opacity_expr: str,
    prefix: str,
) -> list[str]:
    """Split RGBA, multiply only alpha per frame, then merge it back."""

    escaped = str(opacity_expr).replace(",", "\\,")
    color_label = f"[{prefix}_color]"
    alpha_input_label = f"[{prefix}_alpha_in]"
    alpha_output_label = f"[{prefix}_alpha]"
    return [
        f"{input_label}split{color_label}{alpha_input_label}",
        (
            f"{alpha_input_label}alphaextract,"
            f"geq=lum='lum(X\\,Y)*({escaped})'{alpha_output_label}"
        ),
        f"{color_label}{alpha_output_label}alphamerge{output_label}",
    ]


def _keyframes(move_config: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw = move_config.get("keyframes")
    if not isinstance(raw, list):
        return []
    return [frame for frame in raw if isinstance(frame, Mapping)]


def _opacity_value(value: Any, label: str) -> float:
    result = _finite_float(value, label)
    if not 0.0 <= result <= 1.0:
        raise ValidationError(f"Character {label} must be between 0.0 and 1.0.")
    return result


def _finite_float(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise ValidationError(f"Character {label} must be a finite number.")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"Character {label} must be a finite number.") from exc
    if not math.isfinite(result):
        raise ValidationError(f"Character {label} must be a finite number.")
    return result
