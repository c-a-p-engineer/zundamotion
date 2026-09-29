"""Character rotation Motion Core helpers.

Rotation owns degree-to-radian lowering and pivot-safe fixed-canvas geometry.
It does not execute FFmpeg or own character persistence.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping, Sequence

from ....exceptions import ValidationError
from .motion_track import build_motion_track, build_track_expression
from .movement import resolve_max_scale


_ROTATION_MARGIN_PX = 2
_EPSILON = 1e-12


@dataclass(frozen=True)
class RotationCanvas:
    """Fixed transparent canvas keeping the character anchor at its center."""

    width: int
    height: int
    pad_x: int
    pad_y: int
    correction_x: float
    correction_y: float


def rotation_requested(character_config: Mapping[str, Any]) -> bool:
    """Return whether a character requests static or animated rotation."""

    if "rotate" in character_config:
        try:
            if abs(float(character_config.get("rotate", 0.0))) > _EPSILON:
                return True
        except (TypeError, ValueError):
            return True

    move = character_config.get("move")
    if not isinstance(move, Mapping) or move.get("enabled") is False:
        return False
    raw_from = move.get("from")
    if isinstance(raw_from, Mapping) and "rotate" in raw_from:
        return True
    keyframes = move.get("keyframes")
    return isinstance(keyframes, list) and any(
        isinstance(frame, Mapping) and "rotate" in frame for frame in keyframes
    )


def build_rotate_expression(
    *,
    move_config: Any,
    to_rotate: Any,
    time_base: float = 0.0,
) -> tuple[str, bool]:
    """Build a fixed/static or MotionTrack-backed FFmpeg radian expression."""

    final_degrees = _finite_float(to_rotate, "character rotate")
    static_expr = _radian_value(final_degrees)

    if not isinstance(move_config, Mapping) or move_config.get("enabled") is False:
        return static_expr, abs(final_degrees) > _EPSILON

    raw_from = move_config.get("from")
    keyframes = _keyframes(move_config)
    has_waypoint = any("rotate" in frame for frame in keyframes)
    has_start = isinstance(raw_from, Mapping) and "rotate" in raw_from
    if not has_waypoint and not has_start:
        return static_expr, abs(final_degrees) > _EPSILON
    if not has_start:
        raise ValidationError(
            "Character move.from.rotate is required when rotate keyframes are used."
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
        property_name="rotate",
        start_time=start + float(time_base),
        duration=duration,
        start_value=raw_from["rotate"],
        final_value=final_degrees,
        waypoints=keyframes,
        default_easing=str(move_config.get("easing", "linear")),
    )
    return build_track_expression(track, _radian_value), True


def build_rotation_canvas(
    *,
    source_width: int,
    source_height: int,
    move_config: Any,
    to_scale: float,
    anchor: str,
) -> RotationCanvas:
    """Resolve a fixed canvas that can rotate the largest scaled source safely."""

    if source_width <= 0 or source_height <= 0:
        raise ValidationError(
            "Character source dimensions are required for animated rotation."
        )

    max_scale = resolve_max_scale(move_config, to_scale)
    scaled_width = max(1, math.ceil(source_width * max_scale))
    scaled_height = max(1, math.ceil(source_height * max_scale))
    ratio_x, ratio_y = _anchor_ratios(anchor)
    pivot_x = scaled_width * ratio_x
    pivot_y = scaled_height * ratio_y

    corners = (
        (0.0, 0.0),
        (float(scaled_width), 0.0),
        (0.0, float(scaled_height)),
        (float(scaled_width), float(scaled_height)),
    )
    radius = max(
        math.hypot(corner_x - pivot_x, corner_y - pivot_y)
        for corner_x, corner_y in corners
    )
    minimum_size = max(
        1,
        int(math.ceil(radius * 2.0)) + (_ROTATION_MARGIN_PX * 2),
    )
    width = _center_compatible_size(minimum_size, pivot_x)
    height = _center_compatible_size(minimum_size, pivot_y)
    pad_x = int(round(width / 2.0 - pivot_x))
    pad_y = int(round(height / 2.0 - pivot_y))

    return RotationCanvas(
        width=width,
        height=height,
        pad_x=pad_x,
        pad_y=pad_y,
        correction_x=(ratio_x - 0.5) * width,
        correction_y=(ratio_y - 0.5) * height,
    )


def build_rotation_filter(angle_expr: str, canvas: RotationCanvas) -> str:
    """Return fixed-size pad + rotate filters with transparent fill."""

    escaped_angle = str(angle_expr).replace(",", "\\,")
    return (
        f"pad=w={canvas.width}:h={canvas.height}:"
        f"x={canvas.pad_x}:y={canvas.pad_y}:color=black@0,"
        f"rotate=angle='{escaped_angle}':ow=iw:oh=ih:"
        "fillcolor=0x00000000"
    )


def correct_rotation_position(expression: str, correction: float) -> str:
    """Correct overlay position so the rotation-canvas center is the world anchor."""

    if abs(correction) <= _EPSILON:
        return expression
    return f"({expression})+({correction:.6f})"


def _keyframes(move_config: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw = move_config.get("keyframes")
    if not isinstance(raw, list):
        return []
    return [frame for frame in raw if isinstance(frame, Mapping)]


def _anchor_ratios(anchor: str) -> tuple[float, float]:
    normalized = str(anchor).lower()
    horizontal = {
        "left": 0.0,
        "center": 0.5,
        "right": 1.0,
    }
    vertical = {
        "top": 0.0,
        "middle": 0.5,
        "bottom": 1.0,
    }
    try:
        y_name, x_name = normalized.split("_", 1)
    except ValueError:
        return 0.0, 0.0
    return horizontal.get(x_name, 0.0), vertical.get(y_name, 0.0)


def _center_compatible_size(minimum_size: int, pivot: float) -> int:
    size = max(1, int(minimum_size))
    fractional = abs(pivot - round(pivot))
    requires_odd = abs(fractional - 0.5) < 1e-9
    if requires_odd and size % 2 == 0:
        size += 1
    elif not requires_odd and size % 2 == 1:
        size += 1
    return size


def _radian_value(degrees: float) -> str:
    return f"{math.radians(float(degrees)):.9f}"


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
