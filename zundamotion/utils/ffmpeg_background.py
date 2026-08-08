"""FFmpeg background fit, crop/pad, and overlay-position helpers."""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

from .logger import logger

BACKGROUND_FIT_STRETCH = "stretch"
BACKGROUND_FIT_CONTAIN = "contain"
BACKGROUND_FIT_COVER = "cover"
BACKGROUND_FIT_WIDTH = "fit_width"
BACKGROUND_FIT_HEIGHT = "fit_height"
BACKGROUND_FIT_MODES = {
    BACKGROUND_FIT_STRETCH,
    BACKGROUND_FIT_CONTAIN,
    BACKGROUND_FIT_COVER,
    BACKGROUND_FIT_WIDTH,
    BACKGROUND_FIT_HEIGHT,
}
DEFAULT_BACKGROUND_ANCHOR = "middle_center"
DEFAULT_BACKGROUND_FILL_COLOR = "#000000"


def _to_expr(value: Any) -> str:
    if value is None:
        return "0"
    return str(value)


def _sanitize_anchor(anchor: Optional[str]) -> str:
    return DEFAULT_BACKGROUND_ANCHOR if not anchor else str(anchor)


def _anchor_base_position(
    bg_width: str, bg_height: str, fg_width: str, fg_height: str, anchor: str
) -> Tuple[str, str]:
    positions = {
        "top_left": ("0", "0"),
        "top_center": (f"({bg_width}-{fg_width})/2", "0"),
        "top_right": (f"{bg_width}-{fg_width}", "0"),
        "middle_left": ("0", f"({bg_height}-{fg_height})/2"),
        "middle_center": (
            f"({bg_width}-{fg_width})/2",
            f"({bg_height}-{fg_height})/2",
        ),
        "middle_right": (
            f"{bg_width}-{fg_width}",
            f"({bg_height}-{fg_height})/2",
        ),
        "bottom_left": ("0", f"{bg_height}-{fg_height}"),
        "bottom_center": (
            f"({bg_width}-{fg_width})/2",
            f"{bg_height}-{fg_height}",
        ),
        "bottom_right": (
            f"{bg_width}-{fg_width}",
            f"{bg_height}-{fg_height}",
        ),
    }
    if anchor not in positions:
        logger.warning("Unknown anchor point: %s. Defaulting to top_left.", anchor)
        return "0", "0"
    return positions[anchor]


def _add_offset(expr: str, offset: str) -> str:
    if not offset or offset == "0":
        return expr
    return f"{expr}{offset}" if offset.startswith("-") else f"{expr}+{offset}"


def calculate_overlay_position(
    bg_width_expr: str,
    bg_height_expr: str,
    fg_width_expr: str,
    fg_height_expr: str,
    anchor: str,
    offset_x: str = "0",
    offset_y: str = "0",
) -> Tuple[str, str]:
    x_expr, y_expr = _anchor_base_position(
        bg_width_expr, bg_height_expr, fg_width_expr, fg_height_expr, anchor
    )
    return _add_offset(x_expr, offset_x), _add_offset(y_expr, offset_y)


def _contain_steps(
    width: int, height: int, fill: str, anchor: str,
    offset_x: str, offset_y: str, flags: str,
) -> List[str]:
    x, y = calculate_overlay_position(
        str(width), str(height), "iw", "ih", anchor, offset_x, offset_y
    )
    return [
        f"scale={width}:{height}:flags={flags}:force_original_aspect_ratio=decrease",
        f"pad={width}:{height}:x={x}:y={y}:color={fill}",
    ]


def _cover_steps(
    width: int, height: int, anchor: str,
    offset_x: str, offset_y: str, flags: str,
) -> List[str]:
    x, y = calculate_overlay_position(
        "iw", "ih", str(width), str(height), anchor, offset_x, offset_y
    )
    return [
        f"scale={width}:{height}:flags={flags}:force_original_aspect_ratio=increase",
        f"crop={width}:{height}:{x}:{y}",
    ]


def _fit_width_steps(
    width: int, height: int, fill: str, anchor: str,
    offset_x: str, offset_y: str, flags: str,
) -> List[str]:
    crop_height = f"min({height},ih)"
    crop_x, crop_y = calculate_overlay_position(
        "iw", "ih", str(width), crop_height, anchor, offset_x, offset_y
    )
    pad_x, pad_y = calculate_overlay_position(
        str(width), str(height), "iw", "ih", anchor, offset_x, offset_y
    )
    return [
        f"scale={width}:-2:flags={flags}",
        f"crop={width}:{crop_height}:{crop_x}:{crop_y}",
        f"pad={width}:{height}:x={pad_x}:y={pad_y}:color={fill}",
    ]


def _fit_height_steps(
    width: int, height: int, fill: str, anchor: str,
    offset_x: str, offset_y: str, flags: str,
) -> List[str]:
    crop_width = f"min({width},iw)"
    crop_x, crop_y = calculate_overlay_position(
        "iw", "ih", crop_width, str(height), anchor, offset_x, offset_y
    )
    pad_x, pad_y = calculate_overlay_position(
        str(width), str(height), "iw", "ih", anchor, offset_x, offset_y
    )
    return [
        f"scale=-2:{height}:flags={flags}",
        f"crop={crop_width}:{height}:{crop_x}:{crop_y}",
        f"pad={width}:{height}:x={pad_x}:y={pad_y}:color={fill}",
    ]


def build_background_fit_steps(
    *, width: int, height: int, fit_mode: str, fill_color: str,
    anchor: str, offset_x: str, offset_y: str, scale_flags: str,
) -> List[str]:
    fit = (fit_mode or BACKGROUND_FIT_STRETCH).lower()
    if fit not in BACKGROUND_FIT_MODES:
        fit = BACKGROUND_FIT_STRETCH
    if fit == BACKGROUND_FIT_CONTAIN:
        return _contain_steps(width, height, fill_color, anchor, offset_x, offset_y, scale_flags)
    if fit == BACKGROUND_FIT_COVER:
        return _cover_steps(width, height, anchor, offset_x, offset_y, scale_flags)
    if fit == BACKGROUND_FIT_WIDTH:
        return _fit_width_steps(width, height, fill_color, anchor, offset_x, offset_y, scale_flags)
    if fit == BACKGROUND_FIT_HEIGHT:
        return _fit_height_steps(width, height, fill_color, anchor, offset_x, offset_y, scale_flags)
    return [f"scale={width}:{height}:flags={scale_flags}"]


def build_background_filter_complex(
    *, input_label: str, output_label: str, steps: List[str],
    apply_fps: bool, fps: int,
) -> List[str]:
    if not steps:
        expression = f"fps={fps}" if apply_fps else "null"
        return [f"[{input_label}]{expression}[{output_label}]"]
    parts: List[str] = []
    current = input_label
    for index, step in enumerate(steps):
        last = index == len(steps) - 1
        target = output_label if last else f"{output_label}_step{index + 1}"
        expression = f"{step},fps={fps}" if last and apply_fps else step
        parts.append(f"[{current}]{expression}[{target}]")
        current = target
    return parts


def compose_background_filter_expression(
    *, steps: List[str], apply_fps: bool, fps: int
) -> str:
    if not steps:
        return f"fps={fps}" if apply_fps else "null"
    filters = steps.copy()
    if apply_fps:
        filters[-1] = f"{filters[-1]},fps={fps}"
    return ",".join(filters)
