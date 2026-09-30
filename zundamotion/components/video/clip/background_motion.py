"""Strict Motion Core lowering for background-local pan/zoom keyframes.

The legacy single-segment background effect remains owned by
clip.effects.resolve. This module is entered only when a non-empty
keyframes list explicitly requests the strict Motion Core path.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from ....exceptions import ValidationError
from .motion_track import build_motion_track, build_track_expression


_SUPPORTED_EASINGS = {"linear", "ease_in", "ease_out", "ease_in_out"}


def has_background_motion_keyframes(effect: Dict[str, Any]) -> bool:
    """Return whether the strict background Motion Core path is requested."""

    raw = effect.get("keyframes")
    return bool(raw)


def build_background_pan_zoom_motion_filter(
    effect: Dict[str, Any],
    *,
    input_label: str,
    width: int,
    height: int,
    index: int,
    id_prefix: str,
    output_fps: Optional[float],
) -> tuple[str, str]:
    """Build one strict multi-keyframe zoompan filter and output label."""

    start = _strict_number(
        effect.get("start", 0.0),
        "background pan/zoom start",
        minimum=0.0,
    )
    if "duration" not in effect:
        raise ValidationError(
            "Background pan/zoom duration is required when keyframes are used."
        )
    duration = _strict_number(
        effect.get("duration"),
        "background pan/zoom duration",
        minimum=0.0,
        exclusive_minimum=True,
    )
    easing = str(effect.get("easing", "linear")).strip().lower()
    if easing not in _SUPPORTED_EASINGS:
        raise ValidationError(
            "Background pan/zoom easing must be one of: "
            + ", ".join(sorted(_SUPPORTED_EASINGS))
            + "."
        )

    fps = _strict_fps(effect.get("fps"), output_fps)
    zoom_start, zoom_end = _strict_zoom_range(effect)
    pan_start_x, pan_start_y, pan_end_x, pan_end_y = _strict_pan_range(effect)
    waypoints = _flatten_waypoints(effect.get("keyframes"))

    time_variable = f"(on/{fps:.6f})"
    zoom_expr = _track_expression(
        property_name="zoom",
        start_value=zoom_start,
        final_value=zoom_end,
        waypoints=waypoints,
        start_time=start,
        duration=duration,
        default_easing=easing,
        time_variable=time_variable,
    )
    focus_x_expr = _track_expression(
        property_name="pan.x",
        start_value=pan_start_x,
        final_value=pan_end_x,
        waypoints=waypoints,
        start_time=start,
        duration=duration,
        default_easing=easing,
        time_variable=time_variable,
    )
    focus_y_expr = _track_expression(
        property_name="pan.y",
        start_value=pan_start_y,
        final_value=pan_end_y,
        waypoints=waypoints,
        start_time=start,
        duration=duration,
        default_easing=easing,
        time_variable=time_variable,
    )

    x_expr = f"(iw-iw/zoom)*({focus_x_expr})"
    y_expr = f"(ih-ih/zoom)*({focus_y_expr})"
    label = f"[{id_prefix}_pan_zoom_{index}]"
    filter_text = (
        f"{input_label}zoompan="
        f"z='{_escape_zoompan_expr(zoom_expr)}':"
        f"x='{_escape_zoompan_expr(x_expr)}':"
        f"y='{_escape_zoompan_expr(y_expr)}':"
        "d=1:"
        f"s={width}x{height}:"
        f"fps={fps:.3f}{label}"
    )
    return filter_text, label


def _track_expression(
    *,
    property_name: str,
    start_value: float,
    final_value: float,
    waypoints: List[Dict[str, Any]],
    start_time: float,
    duration: float,
    default_easing: str,
    time_variable: str,
) -> str:
    has_waypoint = any(property_name in frame for frame in waypoints)
    if not has_waypoint and abs(start_value - final_value) <= 1e-12:
        return f"{final_value:.6f}"

    track = build_motion_track(
        property_name=property_name,
        start_time=start_time,
        duration=duration,
        start_value=start_value,
        final_value=final_value,
        waypoints=waypoints,
        default_easing=default_easing,
    )
    return build_track_expression(
        track,
        lambda value: f"{value:.6f}",
        time_variable=time_variable,
    )


def _flatten_waypoints(raw: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw, list) or not raw:
        raise ValidationError(
            "Background pan/zoom keyframes must be a non-empty list."
        )

    resolved: List[Dict[str, Any]] = []
    for index, frame in enumerate(raw):
        if not isinstance(frame, dict):
            raise ValidationError(
                f"Background pan/zoom keyframes[{index}] must be a dictionary."
            )
        item: Dict[str, Any] = {"at": frame.get("at")}
        if "easing" in frame:
            item["easing"] = frame["easing"]
        if "zoom" in frame:
            item["zoom"] = _strict_number(
                frame["zoom"],
                f"background pan/zoom keyframes[{index}].zoom",
                minimum=1.0,
                maximum=4.0,
            )
        pan = frame.get("pan")
        if pan is not None:
            if not isinstance(pan, dict):
                raise ValidationError(
                    f"Background pan/zoom keyframes[{index}].pan must be a dictionary."
                )
            if "x" in pan:
                item["pan.x"] = _strict_number(
                    pan["x"],
                    f"background pan/zoom keyframes[{index}].pan.x",
                    minimum=0.0,
                    maximum=1.0,
                )
            if "y" in pan:
                item["pan.y"] = _strict_number(
                    pan["y"],
                    f"background pan/zoom keyframes[{index}].pan.y",
                    minimum=0.0,
                    maximum=1.0,
                )
        resolved.append(item)
    return resolved


def _strict_zoom_range(effect: Dict[str, Any]) -> tuple[float, float]:
    zoom_cfg = effect.get("zoom", {})
    if isinstance(zoom_cfg, dict):
        start_raw = zoom_cfg.get(
            "from",
            zoom_cfg.get("start", effect.get("from", 1.0)),
        )
        end_raw = zoom_cfg.get(
            "to",
            zoom_cfg.get("end", effect.get("to", start_raw)),
        )
    else:
        start_raw = 1.0
        end_raw = zoom_cfg if zoom_cfg is not None else 1.0
    return (
        _strict_number(
            start_raw,
            "background pan/zoom zoom.from",
            minimum=1.0,
            maximum=4.0,
        ),
        _strict_number(
            end_raw,
            "background pan/zoom zoom.to",
            minimum=1.0,
            maximum=4.0,
        ),
    )


def _strict_pan_range(effect: Dict[str, Any]) -> tuple[float, float, float, float]:
    pan_cfg = effect.get("pan", effect.get("focus", {}))
    if isinstance(pan_cfg, dict) and ("from" in pan_cfg or "to" in pan_cfg):
        start_x, start_y = _strict_focus(
            pan_cfg.get("from"),
            default_x=0.5,
            default_y=0.5,
            label="background pan/zoom pan.from",
        )
        end_x, end_y = _strict_focus(
            pan_cfg.get("to"),
            default_x=start_x,
            default_y=start_y,
            label="background pan/zoom pan.to",
        )
        return start_x, start_y, end_x, end_y

    start_x, start_y = _strict_focus(
        pan_cfg,
        default_x=0.5,
        default_y=0.5,
        label="background pan/zoom pan",
    )
    return start_x, start_y, start_x, start_y


def _strict_focus(
    value: Any,
    *,
    default_x: float,
    default_y: float,
    label: str,
) -> tuple[float, float]:
    if value is None:
        return default_x, default_y
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be a dictionary.")

    unknown = sorted(set(value) - {"x", "y", "horizontal", "vertical"})
    if unknown:
        raise ValidationError(
            f"{label} contains unsupported properties: {', '.join(unknown)}."
        )

    x_raw = value.get("x", value.get("horizontal", default_x))
    y_raw = value.get("y", value.get("vertical", default_y))
    return (
        _strict_number(
            x_raw,
            f"{label}.x",
            minimum=0.0,
            maximum=1.0,
        ),
        _strict_number(
            y_raw,
            f"{label}.y",
            minimum=0.0,
            maximum=1.0,
        ),
    )


def _strict_fps(raw_fps: Any, output_fps: Optional[float]) -> float:
    value = output_fps if raw_fps is None else raw_fps
    if value is None:
        value = 30.0
    return _strict_number(
        value,
        "background pan/zoom fps",
        minimum=1.0,
        maximum=120.0,
    )


def _strict_number(
    value: Any,
    label: str,
    *,
    minimum: Optional[float] = None,
    maximum: Optional[float] = None,
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

    if minimum is not None:
        if exclusive_minimum and result <= minimum:
            raise ValidationError(f"{label} must be greater than {minimum}.")
        if not exclusive_minimum and result < minimum:
            if maximum is not None:
                raise ValidationError(
                    f"{label} must be between {minimum} and {maximum}."
                )
            raise ValidationError(
                f"{label} must be greater than or equal to {minimum}."
            )
    if maximum is not None and result > maximum:
        if minimum is not None:
            raise ValidationError(
                f"{label} must be between {minimum} and {maximum}."
            )
        raise ValidationError(
            f"{label} must be less than or equal to {maximum}."
        )
    return result


def _escape_zoompan_expr(expr: str) -> str:
    return expr.replace(",", "\\,").replace(":", "\\:")
