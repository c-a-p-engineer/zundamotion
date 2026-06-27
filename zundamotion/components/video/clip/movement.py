from __future__ import annotations

import math
from typing import Any, Dict, Tuple

from ....exceptions import ValidationError
from ....utils.ffmpeg_ops import calculate_overlay_position


SUPPORTED_MOVE_EASINGS = {"linear", "ease_in", "ease_out", "ease_in_out"}


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
    """Build FFmpeg overlay x/y expressions for a one-shot character move."""

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
        if "scale" in raw_from:
            return to_x_expr, to_y_expr, False
        raise ValidationError(
            "Character move.from must define x, y, or scale when no previous "
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


def build_scale_expression(
    *,
    move_config: Any,
    to_scale: float,
    time_base: float = 0.0,
) -> Tuple[str, bool]:
    """Build a per-frame FFmpeg scale multiplier for a character move."""

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
    easing = str(move_config.get("easing", "linear")).strip().lower()
    if easing not in SUPPORTED_MOVE_EASINGS:
        raise ValidationError(
            "Character move.easing must be one of: "
            + ", ".join(sorted(SUPPORTED_MOVE_EASINGS))
        )

    progress_expr = _build_progress_expr(start, duration, easing)
    scale_expr = (
        f"({from_scale:.6f})+(({final_scale:.6f})-({from_scale:.6f}))"
        f"*({progress_expr})"
    )
    return scale_expr, True


def has_scale_transition(move_config: Any) -> bool:
    """Return whether move.from defines an animated starting scale."""

    if not isinstance(move_config, dict) or move_config.get("enabled") is False:
        return False
    raw_from = move_config.get("from")
    return isinstance(raw_from, dict) and "scale" in raw_from


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

    raw_from = move_config.get("from") if isinstance(move_config, dict) else None
    from_scale = (
        _required_positive_float(raw_from.get("scale"), "move.from.scale")
        if isinstance(raw_from, dict) and "scale" in raw_from
        else float(to_scale)
    )
    max_scale = max(from_scale, float(to_scale))
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


def _required_positive_float(value: Any, label: str) -> float:
    try:
        result = float(value)
    except Exception as exc:
        raise ValidationError(f"Character {label} must be a number.") from exc
    if result <= 0.0:
        raise ValidationError(f"Character {label} must be greater than 0.")
    return result


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
