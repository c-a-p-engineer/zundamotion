"""Bounded world-viewport camera Motion Core helpers.

The first camera slice applies one view transform to the already-composited
W x H world frame. It intentionally does not create an overscanned world.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping

from ....exceptions import ValidationError
from .motion_track import (
    build_motion_track,
    build_track_expression,
    track_changes_value,
)


_EPSILON = 1e-12


@dataclass(frozen=True)
class CameraExpressions:
    focus_x: str
    focus_y: str
    zoom: str
    active: bool


def camera_requested(camera_config: Any) -> bool:
    """Return whether the config can produce a non-neutral camera view."""

    if not isinstance(camera_config, Mapping):
        return False
    zoom_values: list[float] = []
    try:
        if "zoom" in camera_config:
            zoom_values.append(float(camera_config["zoom"]))
        move = camera_config.get("move")
        if isinstance(move, Mapping) and move.get("enabled") is not False:
            raw_from = move.get("from")
            if isinstance(raw_from, Mapping) and "zoom" in raw_from:
                zoom_values.append(float(raw_from["zoom"]))
            keyframes = move.get("keyframes")
            if isinstance(keyframes, list):
                for frame in keyframes:
                    if isinstance(frame, Mapping) and "zoom" in frame:
                        zoom_values.append(float(frame["zoom"]))
    except (TypeError, ValueError):
        # Invalid values should take the conservative CPU path until validation reports them.
        return True
    return any(abs(value - 1.0) > _EPSILON for value in zoom_values)


def build_camera_expressions(
    camera_config: Any,
    *,
    fps: float,
    time_base: float = 0.0,
) -> CameraExpressions:
    """Resolve camera authoring into zoompan-compatible expressions."""

    if camera_config is None:
        return CameraExpressions("0.500000", "0.500000", "1.000000", False)
    if not isinstance(camera_config, Mapping):
        raise ValidationError("Camera must be a dictionary.")

    final_focus = _focus_mapping(camera_config.get("focus"), "camera.focus")
    final_x = _focus_value(final_focus.get("x"), "camera.focus.x")
    final_y = _focus_value(final_focus.get("y"), "camera.focus.y")
    final_zoom = _zoom_value(camera_config.get("zoom"), "camera.zoom")

    move = camera_config.get("move")
    if not isinstance(move, Mapping) or move.get("enabled") is False:
        return CameraExpressions(
            f"{final_x:.6f}",
            f"{final_y:.6f}",
            f"{final_zoom:.6f}",
            abs(final_zoom - 1.0) > _EPSILON,
        )

    start = _finite_float(move.get("start", 0.0), "camera.move.start")
    if start < 0.0:
        raise ValidationError("Camera move.start must be greater than or equal to 0.")
    duration = _finite_float(move.get("duration", 0.3), "camera.move.duration")
    if duration <= 0.0:
        raise ValidationError("Camera move.duration must be greater than 0.")
    easing = str(move.get("easing", "linear"))

    raw_from = move.get("from")
    from_map = raw_from if isinstance(raw_from, Mapping) else {}
    from_focus_raw = from_map.get("focus")
    from_focus = (
        _focus_mapping(from_focus_raw, "camera.move.from.focus")
        if from_focus_raw is not None
        else {}
    )
    waypoints = _flatten_waypoints(move.get("keyframes"))
    time_variable = f"(on/{max(float(fps), 1.0):.6f})"
    absolute_start = start + float(time_base)

    x_expr, _ = _property_expression(
        property_name="focus_x",
        start_value=from_focus.get("x"),
        final_value=final_x,
        waypoints=waypoints,
        start_time=absolute_start,
        duration=duration,
        easing=easing,
        value_parser=_focus_value,
        constant=lambda value: f"{value:.6f}",
        time_variable=time_variable,
    )
    y_expr, _ = _property_expression(
        property_name="focus_y",
        start_value=from_focus.get("y"),
        final_value=final_y,
        waypoints=waypoints,
        start_time=absolute_start,
        duration=duration,
        easing=easing,
        value_parser=_focus_value,
        constant=lambda value: f"{value:.6f}",
        time_variable=time_variable,
    )
    zoom_expr, zoom_track = _property_expression(
        property_name="zoom",
        start_value=from_map.get("zoom"),
        final_value=final_zoom,
        waypoints=waypoints,
        start_time=absolute_start,
        duration=duration,
        easing=easing,
        value_parser=_zoom_value,
        constant=lambda value: f"{value:.6f}",
        time_variable=time_variable,
    )

    active = abs(final_zoom - 1.0) > _EPSILON
    if zoom_track is not None:
        active = active or abs(zoom_track.keyframes[0].value - 1.0) > _EPSILON
        active = active or track_changes_value(zoom_track)
        active = active or any(
            abs(frame.value - 1.0) > _EPSILON for frame in zoom_track.keyframes
        )
    return CameraExpressions(x_expr, y_expr, zoom_expr, active)


def append_camera_transform(
    *,
    camera_config: Any,
    input_label: str,
    width: int,
    height: int,
    fps: float,
    parts: list[str],
    output_label: str = "[camera_view]",
) -> str:
    """Append one bounded-world camera filter and return the resulting label."""

    expressions = build_camera_expressions(camera_config, fps=fps)
    if not expressions.active:
        return input_label

    zoom = _escape_zoompan(expressions.zoom)
    focus_x = _escape_zoompan(expressions.focus_x)
    focus_y = _escape_zoompan(expressions.focus_y)
    parts.append(
        f"{input_label}zoompan="
        f"z='{zoom}':"
        f"x='(iw-iw/zoom)*({focus_x})':"
        f"y='(ih-ih/zoom)*({focus_y})':"
        "d=1:"
        f"s={int(width)}x{int(height)}:"
        f"fps={max(float(fps), 1.0):.3f}{output_label}"
    )
    return output_label


def _property_expression(
    *,
    property_name: str,
    start_value: Any,
    final_value: float,
    waypoints: list[Mapping[str, Any]],
    start_time: float,
    duration: float,
    easing: str,
    value_parser,
    constant,
    time_variable: str,
):
    has_waypoint = any(property_name in frame for frame in waypoints)
    has_start = start_value is not None
    if not has_waypoint and not has_start:
        return constant(final_value), None
    if not has_start:
        display = property_name.replace("_", ".")
        raise ValidationError(
            f"Camera move.from.{display} is required when {display} keyframes are used."
        )

    parsed_start = value_parser(start_value, f"camera.move.from.{property_name}")
    track = build_motion_track(
        property_name=property_name,
        start_time=start_time,
        duration=duration,
        start_value=parsed_start,
        final_value=final_value,
        waypoints=waypoints,
        default_easing=easing,
    )
    # Validate every resolved waypoint with the camera-specific domain parser.
    for index, frame in enumerate(track.keyframes):
        value_parser(frame.value, f"camera resolved {property_name} keyframe {index}")
    return (
        build_track_expression(
            track,
            constant,
            time_variable=time_variable,
        ),
        track,
    )


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
            item["zoom"] = frame["zoom"]
        focus = frame.get("focus")
        if isinstance(focus, Mapping):
            if "x" in focus:
                item["focus_x"] = focus["x"]
            if "y" in focus:
                item["focus_y"] = focus["y"]
        flattened.append(item)
    return flattened


def _focus_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValidationError(f"{label} must be a dictionary with x and y.")
    if "x" not in value or "y" not in value:
        raise ValidationError(f"{label}.x and {label}.y are required.")
    return value


def _focus_value(value: Any, label: str) -> float:
    result = _finite_float(value, label)
    if not 0.0 <= result <= 1.0:
        raise ValidationError(f"{label} must be between 0.0 and 1.0.")
    return result


def _zoom_value(value: Any, label: str) -> float:
    result = _finite_float(value, label)
    if not 1.0 <= result <= 4.0:
        raise ValidationError(f"{label} must be between 1.0 and 4.0.")
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


def _escape_zoompan(expression: str) -> str:
    return str(expression).replace(",", "\\,").replace(":", "\\:")
