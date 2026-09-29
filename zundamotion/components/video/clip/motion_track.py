"""Pure property-track model for character motion.

Authoring/validation resolves YAML semantics before this module.  The track
itself is renderer-agnostic except for the optional FFmpeg expression lowering
helper kept here so easing math has one owner.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Callable, Iterable, Mapping, Sequence

from ....exceptions import ValidationError


SUPPORTED_MOTION_EASINGS = frozenset(
    {"linear", "ease_in", "ease_out", "ease_in_out"}
)


@dataclass(frozen=True)
class MotionKeyframe:
    """One resolved property value at an absolute clip-local time."""

    time: float
    value: float
    easing_to_here: str | None = None


@dataclass(frozen=True)
class MotionTrack:
    """Immutable resolved keyframes for one numeric motion property."""

    property: str
    keyframes: tuple[MotionKeyframe, ...]


def build_motion_track(
    *,
    property_name: str,
    start_time: float,
    duration: float,
    start_value: object,
    final_value: object,
    waypoints: Sequence[Mapping[str, object]],
    default_easing: str,
) -> MotionTrack:
    """Resolve sparse authoring waypoints into one property-specific track."""

    resolved_start = _finite_float(start_time, "motion start")
    resolved_duration = _finite_float(duration, "motion duration")
    if resolved_duration <= 0.0:
        raise ValidationError("Character move.duration must be greater than 0.")

    easing = _resolve_easing(default_easing, "move.easing")
    frames: list[MotionKeyframe] = [
        MotionKeyframe(
            time=resolved_start,
            value=_finite_float(start_value, f"move start {property_name}"),
        )
    ]

    for index, waypoint in enumerate(waypoints):
        if property_name not in waypoint:
            continue
        at = _finite_float(waypoint.get("at"), f"move.keyframes[{index}].at")
        waypoint_easing = _resolve_easing(
            waypoint.get("easing", easing),
            f"move.keyframes[{index}].easing",
        )
        frames.append(
            MotionKeyframe(
                time=resolved_start + at,
                value=_finite_float(
                    waypoint[property_name],
                    f"move.keyframes[{index}].{property_name}",
                ),
                easing_to_here=waypoint_easing,
            )
        )

    frames.append(
        MotionKeyframe(
            time=resolved_start + resolved_duration,
            value=_finite_float(final_value, f"move final {property_name}"),
            easing_to_here=easing,
        )
    )
    return MotionTrack(property=property_name, keyframes=tuple(frames))


def build_track_expression(
    track: MotionTrack,
    value_expression: Callable[[float], str],
) -> str:
    """Lower a resolved track to a deterministic piecewise FFmpeg expression."""

    frames = track.keyframes
    if len(frames) < 2:
        raise ValidationError("Character motion track requires at least two keyframes.")

    expression = value_expression(frames[-1].value)
    for index in range(len(frames) - 2, -1, -1):
        left = frames[index]
        right = frames[index + 1]
        segment = _segment_expression(
            left=left,
            right=right,
            value_expression=value_expression,
        )
        expression = f"if(lt(t,{right.time:.6f}),{segment},{expression})"

    first = frames[0]
    return f"if(lt(t,{first.time:.6f}),{value_expression(first.value)},{expression})"


def evaluate_motion_track(track: MotionTrack, time: float) -> float:
    """Evaluate a track numerically for unit tests and diagnostics."""

    frames = track.keyframes
    if not frames:
        raise ValidationError("Character motion track has no keyframes.")
    t = _finite_float(time, "motion evaluation time")
    if t <= frames[0].time:
        return frames[0].value

    for index in range(1, len(frames)):
        right = frames[index]
        if t <= right.time:
            left = frames[index - 1]
            duration = right.time - left.time
            if duration <= 0.0:
                return right.value
            progress = (t - left.time) / duration
            eased = ease_progress(progress, right.easing_to_here or "linear")
            return left.value + (right.value - left.value) * eased
    return frames[-1].value


def track_max_value(track: MotionTrack) -> float:
    """Return the maximum resolved value contained in a numeric track."""

    if not track.keyframes:
        raise ValidationError("Character motion track has no keyframes.")
    return max(frame.value for frame in track.keyframes)


def track_changes_value(track: MotionTrack) -> bool:
    """Return whether any resolved keyframe differs from the first value."""

    if not track.keyframes:
        return False
    first = track.keyframes[0].value
    return any(abs(frame.value - first) > 1e-12 for frame in track.keyframes[1:])


def ease_progress(progress: float, easing: str) -> float:
    """Apply the public easing vocabulary to a normalized numeric progress."""

    p = min(1.0, max(0.0, float(progress)))
    normalized = _resolve_easing(easing, "motion easing")
    if normalized == "linear":
        return p
    if normalized == "ease_in":
        return p * p
    if normalized == "ease_out":
        return 1.0 - (1.0 - p) * (1.0 - p)
    if p < 0.5:
        return 2.0 * p * p
    return 1.0 - 2.0 * (1.0 - p) * (1.0 - p)


def _segment_expression(
    *,
    left: MotionKeyframe,
    right: MotionKeyframe,
    value_expression: Callable[[float], str],
) -> str:
    duration = right.time - left.time
    if duration <= 0.0:
        raise ValidationError("Character motion keyframe times must be strictly increasing.")

    progress = f"((t-{left.time:.6f})/{duration:.6f})"
    eased = _eased_progress_expression(
        progress,
        right.easing_to_here or "linear",
    )
    start = value_expression(left.value)
    end = value_expression(right.value)
    return f"({start})+(({end})-({start}))*({eased})"


def _eased_progress_expression(progress: str, easing: str) -> str:
    normalized = _resolve_easing(easing, "motion easing")
    if normalized == "linear":
        return progress
    if normalized == "ease_in":
        return f"({progress})*({progress})"
    if normalized == "ease_out":
        return f"1-(1-({progress}))*(1-({progress}))"
    return (
        f"if(lt({progress},0.5),2*({progress})*({progress}),"
        f"1-2*(1-({progress}))*(1-({progress})))"
    )


def _resolve_easing(value: object, label: str) -> str:
    normalized = str(value).strip().lower()
    if normalized not in SUPPORTED_MOTION_EASINGS:
        raise ValidationError(
            f"Character {label} must be one of: "
            + ", ".join(sorted(SUPPORTED_MOTION_EASINGS))
        )
    return normalized


def _finite_float(value: object, label: str) -> float:
    if isinstance(value, bool):
        raise ValidationError(f"Character {label} must be a finite number.")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"Character {label} must be a finite number.") from exc
    if not math.isfinite(result):
        raise ValidationError(f"Character {label} must be a finite number.")
    return result
