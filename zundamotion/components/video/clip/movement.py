from __future__ import annotations

import math
from typing import Any, Dict, Tuple

from ....exceptions import ValidationError
from ....utils.ffmpeg_ops import calculate_overlay_position
from .motion_track import (
    SUPPORTED_MOTION_EASINGS,
    MotionTrack,
    build_motion_track,
    build_track_expression,
    track_max_value,
)


SUPPORTED_MOVE_EASINGS = set(SUPPORTED_MOTION_EASINGS)


def build_move_expressions(
    *,
    move_config: Any,
    anchor: str,
    from_position: Dict[str, Any] | None,
    to_position: Dict[str, Any],
    to_x_expr: str,
    to_y_expr: str,
    time_base: float = 0.0,
) -> Tuple[str, str, bool]:
    """Build FFmpeg overlay x/y expressions for character movement."""

    if not _has_multi_keyframes(move_config):
        return _build_legacy_move_expressions(
            move_config=move_config,
            anchor=anchor,
            from_position=from_position,
            to_position=to_position,
            to_x_expr=to_x_expr,
            to_y_expr=to_y_expr,
            time_base=time_base,
        )

    if not isinstance(move_config, dict) or move_config.get("enabled") is False:
        return to_x_expr, to_y_expr, False

    keyframes = _keyframes(move_config)
    has_position_waypoint = any(
        "x" in frame or "y" in frame for frame in keyframes
    )
    raw_from = move_config.get("from", from_position)
    if not isinstance(raw_from, dict):
        if not has_position_waypoint:
            return to_x_expr, to_y_expr, False
        raise ValidationError(
            "Character move.from is required when no previous character position is available."
        )

    has_position_start = any(axis in raw_from for axis in ("x", "y"))
    if not has_position_start and not has_position_waypoint:
        return to_x_expr, to_y_expr, False

    start = _required_finite_float(move_config.get("start", 0.0), "move.start")
    if start < 0.0:
        raise ValidationError("Character move.start must be greater than or equal to 0.")
    duration = _required_finite_float(
        move_config.get("duration", 0.3),
        "move.duration",
    )
    if duration <= 0.0:
        raise ValidationError("Character move.duration must be greater than 0.")
    easing = _resolve_easing(move_config.get("easing", "linear"))

    for axis in ("x", "y"):
        if any(axis in frame for frame in keyframes) and axis not in raw_from:
            raise ValidationError(
                f"Character move.from.{axis} is required when {axis} keyframes are used "
                "without a previous character position."
            )

    resolved_from = dict(to_position)
    resolved_from.update(
        {axis: raw_from[axis] for axis in ("x", "y") if axis in raw_from}
    )
    absolute_start = start + time_base

    x_expr, x_dynamic = _build_position_axis_expression(
        axis="x",
        anchor=anchor,
        start_value=resolved_from.get("x", 0),
        final_value=to_position.get("x", 0),
        keyframes=keyframes,
        start_time=absolute_start,
        duration=duration,
        default_easing=easing,
        static_expression=to_x_expr,
    )
    y_expr, y_dynamic = _build_position_axis_expression(
        axis="y",
        anchor=anchor,
        start_value=resolved_from.get("y", 0),
        final_value=to_position.get("y", 0),
        keyframes=keyframes,
        start_time=absolute_start,
        duration=duration,
        default_easing=easing,
        static_expression=to_y_expr,
    )
    return x_expr, y_expr, x_dynamic or y_dynamic


def build_scale_expression(
    *,
    move_config: Any,
    to_scale: float,
    time_base: float = 0.0,
) -> Tuple[str, bool]:
    """Build a per-frame FFmpeg scale multiplier for a character move."""

    static_expr = f"{float(to_scale):.6f}"
    if not _has_multi_keyframes(move_config):
        return _build_legacy_scale_expression(
            move_config=move_config,
            to_scale=to_scale,
            time_base=time_base,
        )

    if not isinstance(move_config, dict) or move_config.get("enabled") is False:
        return static_expr, False

    keyframes = _keyframes(move_config)
    raw_from = move_config.get("from")
    has_scale_waypoint = any("scale" in frame for frame in keyframes)
    has_scale_start = isinstance(raw_from, dict) and "scale" in raw_from
    if not has_scale_waypoint and not has_scale_start:
        return static_expr, False
    if has_scale_waypoint and not has_scale_start:
        raise ValidationError(
            "Character move.from.scale is required when scale keyframes are used "
            "without a previous character scale."
        )

    start = _required_finite_float(move_config.get("start", 0.0), "move.start")
    if start < 0.0:
        raise ValidationError("Character move.start must be greater than or equal to 0.")
    duration = _required_finite_float(
        move_config.get("duration", 0.3),
        "move.duration",
    )
    if duration <= 0.0:
        raise ValidationError("Character move.duration must be greater than 0.")
    easing = _resolve_easing(move_config.get("easing", "linear"))
    from_scale = _required_positive_float(
        raw_from.get("scale") if isinstance(raw_from, dict) else None,
        "move.from.scale",
    )
    final_scale = _required_positive_float(to_scale, "character scale")
    track = build_motion_track(
        property_name="scale",
        start_time=start + time_base,
        duration=duration,
        start_value=from_scale,
        final_value=final_scale,
        waypoints=keyframes,
        default_easing=easing,
    )
    return build_track_expression(track, lambda value: f"{value:.6f}"), True


def has_scale_transition(move_config: Any) -> bool:
    """Return whether move configuration animates character scale."""

    if not isinstance(move_config, dict) or move_config.get("enabled") is False:
        return False
    raw_from = move_config.get("from")
    if isinstance(raw_from, dict) and "scale" in raw_from:
        return True
    return any("scale" in frame for frame in _keyframes(move_config))


def build_dynamic_scale_filter(
    *,
    scale_expr: str,
    move_config: Any,
    to_scale: float,
    source_width: int,
    source_height: int,
    anchor: str,
    scale_flags: str,
) -> str:
    """Scale inside a fixed transparent canvas so overlay dimensions stay stable."""

    if source_width <= 0 or source_height <= 0:
        raise ValidationError(
            "Character source dimensions are required for animated scaling."
        )

    max_scale = _max_scale_for_move(move_config, to_scale)
    canvas_width = max(1, math.ceil(source_width * max_scale))
    canvas_height = max(1, math.ceil(source_height * max_scale))
    pad_x, pad_y = _anchor_padding(anchor)
    escaped_scale_expr = scale_expr.replace(",", "\\,")
    return (
        f"format=rgba,scale=w='iw*({escaped_scale_expr})':h='ih*({escaped_scale_expr})':"
        f"eval=frame:flags={scale_flags},"
        f"pad=w={canvas_width}:h={canvas_height}:x='{pad_x}':y='{pad_y}':"
        "color=black@0:eval=frame"
    )


def _build_legacy_move_expressions(
    *,
    move_config: Any,
    anchor: str,
    from_position: Dict[str, Any] | None,
    to_position: Dict[str, Any],
    to_x_expr: str,
    to_y_expr: str,
    time_base: float,
) -> Tuple[str, str, bool]:
    """Preserve the existing single-segment move expression byte-for-byte."""

    if not isinstance(move_config, dict):
        return to_x_expr, to_y_expr, False
    if move_config.get("enabled") is False:
        return to_x_expr, to_y_expr, False

    duration = _to_float(move_config.get("duration", 0.3), 0.3)
    if duration <= 0.0:
        return to_x_expr, to_y_expr, False

    start = max(0.0, _to_float(move_config.get("start", 0.0), 0.0)) + time_base
    easing = str(move_config.get("easing", "linear")).strip().lower()
    if easing not in SUPPORTED_MOVE_EASINGS:
        raise ValidationError(
            "Character move.easing must be one of: "
            + ", ".join(sorted(SUPPORTED_MOVE_EASINGS))
        )

    raw_from = move_config.get("from", from_position)
    if not isinstance(raw_from, dict):
        raise ValidationError(
            "Character move.from is required when no previous character position is available."
        )
    if not any(axis in raw_from for axis in ("x", "y")):
        if "scale" in raw_from or "rotate" in raw_from or "opacity" in raw_from:
            return to_x_expr, to_y_expr, False
        raise ValidationError(
            "Character move.from must define x, y, scale, rotate, or opacity when no previous "
            "character state is available."
        )

    resolved_from = dict(to_position)
    resolved_from.update(
        {axis: raw_from[axis] for axis in ("x", "y") if axis in raw_from}
    )
    from_x_expr, from_y_expr = calculate_overlay_position(
        "W",
        "H",
        "w",
        "h",
        anchor,
        str(resolved_from.get("x", "0")),
        str(resolved_from.get("y", "0")),
    )
    progress_expr = _build_progress_expr(start, duration, easing)
    x_expr = f"({from_x_expr})+(({to_x_expr})-({from_x_expr}))*({progress_expr})"
    y_expr = f"({from_y_expr})+(({to_y_expr})-({from_y_expr}))*({progress_expr})"
    return x_expr, y_expr, True


def _build_legacy_scale_expression(
    *,
    move_config: Any,
    to_scale: float,
    time_base: float,
) -> Tuple[str, bool]:
    """Preserve the existing single-segment scale expression."""

    static_expr = f"{float(to_scale):.6f}"
    if not isinstance(move_config, dict) or move_config.get("enabled") is False:
        return static_expr, False

    raw_from = move_config.get("from")
    if not isinstance(raw_from, dict) or "scale" not in raw_from:
        return static_expr, False

    duration = _to_float(move_config.get("duration", 0.3), 0.3)
    if duration <= 0.0:
        return static_expr, False

    from_scale = _required_positive_float(raw_from.get("scale"), "move.from.scale")
    final_scale = _required_positive_float(to_scale, "character scale")
    start = max(0.0, _to_float(move_config.get("start", 0.0), 0.0)) + time_base
    easing = _resolve_easing(move_config.get("easing", "linear"))

    progress_expr = _build_progress_expr(start, duration, easing)
    scale_expr = (
        f"({from_scale:.6f})+(({final_scale:.6f})-({from_scale:.6f}))"
        f"*({progress_expr})"
    )
    return scale_expr, True


def _build_position_axis_expression(
    *,
    axis: str,
    anchor: str,
    start_value: Any,
    final_value: Any,
    keyframes: list[Dict[str, Any]],
    start_time: float,
    duration: float,
    default_easing: str,
    static_expression: str,
) -> Tuple[str, bool]:
    has_waypoint = any(axis in frame for frame in keyframes)
    if not has_waypoint:
        try:
            if abs(float(start_value) - float(final_value)) <= 1e-12:
                return static_expression, False
        except Exception:
            pass

    track = build_motion_track(
        property_name=axis,
        start_time=start_time,
        duration=duration,
        start_value=start_value,
        final_value=final_value,
        waypoints=keyframes,
        default_easing=default_easing,
    )
    formatter = lambda value: _position_axis_value_expression(anchor, axis, value)
    return build_track_expression(track, formatter), True


def _position_axis_value_expression(anchor: str, axis: str, value: float) -> str:
    x_value = value if axis == "x" else 0.0
    y_value = value if axis == "y" else 0.0
    x_expr, y_expr = calculate_overlay_position(
        "W",
        "H",
        "w",
        "h",
        anchor,
        f"{x_value:.12g}",
        f"{y_value:.12g}",
    )
    return x_expr if axis == "x" else y_expr


def resolve_max_scale(move_config: Any, to_scale: float) -> float:
    """Return the maximum scale needed by one character motion."""

    return _max_scale_for_move(move_config, to_scale)


def _max_scale_for_move(move_config: Any, to_scale: float) -> float:
    final_scale = _required_positive_float(to_scale, "character scale")
    if not isinstance(move_config, dict):
        return final_scale

    keyframes = _keyframes(move_config)
    raw_from = move_config.get("from")
    if not keyframes:
        if isinstance(raw_from, dict) and "scale" in raw_from:
            return max(
                _required_positive_float(raw_from.get("scale"), "move.from.scale"),
                final_scale,
            )
        return final_scale

    if any("scale" in frame for frame in keyframes):
        if not isinstance(raw_from, dict) or "scale" not in raw_from:
            raise ValidationError(
                "Character move.from.scale is required when scale keyframes are used "
                "without a previous character scale."
            )
        from_scale = _required_positive_float(
            raw_from.get("scale"),
            "move.from.scale",
        )
    elif isinstance(raw_from, dict) and "scale" in raw_from:
        from_scale = _required_positive_float(
            raw_from.get("scale"),
            "move.from.scale",
        )
    else:
        from_scale = final_scale

    track = build_motion_track(
        property_name="scale",
        start_time=_required_finite_float(move_config.get("start", 0.0), "move.start"),
        duration=_required_finite_float(
            move_config.get("duration", 0.3),
            "move.duration",
        ),
        start_value=from_scale,
        final_value=final_scale,
        waypoints=keyframes,
        default_easing=_resolve_easing(move_config.get("easing", "linear")),
    )
    return track_max_value(track)


def _keyframes(move_config: Any) -> list[Dict[str, Any]]:
    if not isinstance(move_config, dict):
        return []
    raw = move_config.get("keyframes")
    if not isinstance(raw, list):
        return []
    return [frame for frame in raw if isinstance(frame, dict)]


def _has_multi_keyframes(move_config: Any) -> bool:
    if not isinstance(move_config, dict):
        return False
    keyframes = move_config.get("keyframes")
    return isinstance(keyframes, list) and bool(keyframes)


def _anchor_padding(anchor: str) -> Tuple[str, str]:
    normalized = str(anchor).lower()
    if normalized.endswith("_right"):
        pad_x = "ow-iw"
    elif normalized.endswith("_center"):
        pad_x = "(ow-iw)/2"
    else:
        pad_x = "0"

    if normalized.startswith("bottom_"):
        pad_y = "oh-ih"
    elif normalized.startswith("middle_"):
        pad_y = "(oh-ih)/2"
    else:
        pad_y = "0"
    return pad_x, pad_y


def _to_float(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except Exception:
        return fallback


def _required_finite_float(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise ValidationError(f"Character {label} must be a finite number.")
    try:
        result = float(value)
    except Exception as exc:
        raise ValidationError(f"Character {label} must be a finite number.") from exc
    if not math.isfinite(result):
        raise ValidationError(f"Character {label} must be a finite number.")
    return result


def _required_positive_float(value: Any, label: str) -> float:
    result = _required_finite_float(value, label)
    if result <= 0.0:
        raise ValidationError(f"Character {label} must be greater than 0.")
    return result


def _resolve_easing(value: Any) -> str:
    easing = str(value).strip().lower()
    if easing not in SUPPORTED_MOVE_EASINGS:
        raise ValidationError(
            "Character move.easing must be one of: "
            + ", ".join(sorted(SUPPORTED_MOVE_EASINGS))
        )
    return easing


def _build_progress_expr(start: float, duration: float, easing: str) -> str:
    end = start + duration
    p = f"((t-{start:.6f})/{duration:.6f})"
    if easing == "linear":
        eased = p
    elif easing == "ease_in":
        eased = f"({p})*({p})"
    elif easing == "ease_out":
        eased = f"1-(1-({p}))*(1-({p}))"
    else:
        eased = f"if(lt({p},0.5),2*({p})*({p}),1-2*(1-({p}))*(1-({p})))"
    return f"if(lt(t,{start:.6f}),0,if(gt(t,{end:.6f}),1,{eased}))"
