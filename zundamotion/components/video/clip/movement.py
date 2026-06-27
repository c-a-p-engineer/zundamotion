from __future__ import annotations

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

    from_x_expr, from_y_expr = calculate_overlay_position(
        "W",
        "H",
        "w",
        "h",
        anchor,
        str(raw_from.get("x", "0")),
        str(raw_from.get("y", "0")),
    )
    progress_expr = _build_progress_expr(start, duration, easing)
    x_expr = f"({from_x_expr})+(({to_x_expr})-({from_x_expr}))*({progress_expr})"
    y_expr = f"({from_y_expr})+(({to_y_expr})-({from_y_expr}))*({progress_expr})"
    return x_expr, y_expr, True


def _to_float(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except Exception:
        return fallback


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
