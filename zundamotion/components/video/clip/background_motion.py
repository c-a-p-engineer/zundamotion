"""Strict MotionTrack lowering for background-local pan/zoom keyframes."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping

from ....exceptions import ValidationError
from .motion_track import build_motion_track, build_track_expression


@dataclass(frozen=True)
class BackgroundPanZoomExpressions:
    """Resolved zoompan expressions for the strict multi-keyframe path."""

    zoom: str
    pan_x: str
    pan_y: str
    fps: float


def has_background_motion_keyframes(effect: Any) -> bool:
    """Return whether the strict background Motion Core path is requested."""

    if not isinstance(effect, Mapping):
        return False
    keyframes = effect.get("keyframes")
    return isinstance(keyframes, list) and bool(keyframes)


def build_background_pan_zoom_expressions(
    effect: Mapping[str, Any],
    *,
    output_fps: float,
) -> BackgroundPanZoomExpressions:
    """Resolve strict background pan/zoom authoring to zoompan expressions."""

    start = _finite_float(effect.get("start", 0.0), "background motion start")
    if start < 0.0:
        raise ValidationError(
            "Background motion start must be greater than or equal to 0."
        )

    if "duration" not in effect:
        raise ValidationError(
            "Background motion duration is required when keyframes are used."
        )
    duration = _finite_float(effect.get("duration"), "background motion duration")
    if duration <= 0.0:
        raise ValidationError("Background motion duration must be greater than 0.")

    easing = str(effect.get("easing", "linear")).strip().lower()
    if easing not in {"linear", "ease_in", "ease_out", "ease_in_out"}:
        raise ValidationError(
            "Background motion easing must be one of: "
            "ease_in, ease_in_out, ease_out, linear"
        )

    fps = _finite_float(effect.get("fps", output_fps), "background motion fps")
    if not 1.0 <= fps <= 120.0:
        raise ValidationError("Background motion fps must be between 1 and 120.")

    zoom_start, zoom_final = _strict_zoom_range(effect)
    pan_start_x, pan_start_y, pan_final_x, pan_final_y = _strict_pan_range(effect)
    waypoints = _flatten_waypoints(effect.get("keyframes"))
    time_variable = f"(on/{fps:.6f})"

    zoom = _property_expression(
        property_name="zoom",
        start_value=zoom_start,
        final_value=zoom_final,
        waypoints=waypoints,
        start_time=start,
        duration=duration,
        easing=easing,
        time_variable=time_variable,
    )
    pan_x = _property_expression(
        property_name="pan_x",
        start_value=pan_start_x,
        final_value=pan_final_x,
        waypoints=waypoints,
        start_time=start,
        duration=duration,
        easing=easing,
        time_variable=time_variable,
    )
    pan_y = _property_expression(
        property_name="pan_y",
        start_value=pan_start_y,
        final_value=pan_final_y,
        waypoints=waypoints,
        start_time=start,
        duration=duration,
        easing=easing,
        time_variable=time_variable,
    )
    return BackgroundPanZoomExpressions(
        zoom=zoom,
        pan_x=pan_x,
        pan_y=pan_y,
        fps=fps,
    )


def _property_expression(
    *,
    property_name: str,
    start_value: float,
    final_value: float,
    waypoints: list[Mapping[str, Any]],
    start_time: float,
    duration: float,
    easing: str,
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
        default_easing=easing,
    )
    return build_track_expression(
        track,
        lambda value: f"{value:.6f}",
        time_variable=time_variable,
    )


def _strict_zoom_range(effect: Mapping[str, Any]) -> tuple[float, float]:
    zoom = effect.get("zoom")
    if isinstance(zoom, Mapping):
        start_raw = zoom.get("from", zoom.get("start", 1.0))
        final_raw = zoom.get("to", zoom.get("end", start_raw))
    elif zoom is None:
        start_raw = final_raw = 1.0
    else:
        start_raw = 1.0
        final_raw = zoom
    return (
        _zoom_value(start_raw, "background zoom start"),
        _zoom_value(final_raw, "background zoom final"),
    )


def _strict_pan_range(
    effect: Mapping[str, Any],
) -> tuple[float, float, float, float]:
    pan = effect.get("pan", {})
    if not isinstance(pan, Mapping):
        raise ValidationError("Background pan must be a dictionary.")

    if "from" in pan or "to" in pan:
        start_x, start_y = _strict_focus(pan.get("from"), 0.5, 0.5, "background pan.from")
        final_x, final_y = _strict_focus(
            pan.get("to"),
            start_x,
            start_y,
            "background pan.to",
        )
        return start_x, start_y, final_x, final_y

    static_x, static_y = _strict_focus(pan, 0.5, 0.5, "background pan")
    return static_x, static_y, static_x, static_y


def _strict_focus(
    value: Any,
    default_x: float,
    default_y: float,
    label: str,
) -> tuple[float, float]:
    if value is None:
        return default_x, default_y
    if not isinstance(value, Mapping):
        raise ValidationError(f"{label} must be a dictionary.")
    x = _focus_value(value.get("x", default_x), f"{label}.x")
    y = _focus_value(value.get("y", default_y), f"{label}.y")
    return x, y


def _flatten_waypoints(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    flattened: list[Mapping[str, Any]] = []
    for frame in value:
        if not isinstance(frame, Mapping):
            continue
        item: dict[str, Any] = {}
        if "at" in frame:
            item["at"] = frame["at"]
        if "easing" in frame:
            item["easing"] = frame["easing"]
        if "zoom" in frame:
            item["zoom"] = _zoom_value(
                frame["zoom"],
                "background keyframe zoom",
            )
        pan = frame.get("pan")
        if isinstance(pan, Mapping):
            if "x" in pan:
                item["pan_x"] = _focus_value(
                    pan["x"],
                    "background keyframe pan.x",
                )
            if "y" in pan:
                item["pan_y"] = _focus_value(
                    pan["y"],
                    "background keyframe pan.y",
                )
        flattened.append(item)
    return flattened


def _zoom_value(value: Any, label: str) -> float:
    result = _finite_float(value, label)
    if not 1.0 <= result <= 4.0:
        raise ValidationError(f"{label} must be between 1.0 and 4.0.")
    return result


def _focus_value(value: Any, label: str) -> float:
    result = _finite_float(value, label)
    if not 0.0 <= result <= 1.0:
        raise ValidationError(f"{label} must be between 0.0 and 1.0.")
    return result


def _finite_float(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise ValidationError(f"{label} must be a finite number.")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{label} must be a finite number.") from exc
    if not math.isfinite(result):
        raise ValidationError(f"{label} must be a finite number.")
    return result
