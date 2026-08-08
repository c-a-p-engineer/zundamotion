"""Resolve Markdown frontmatter into deterministic panel render configuration."""

from __future__ import annotations

from typing import Any, Dict

from ...exceptions import ValidationError
from ..subtitles.png import _normalize_padding


def resolve_markdown_background(frontmatter: Dict[str, Any]) -> str:
    bg = frontmatter.get("bg")
    if isinstance(bg, str) and bg.strip():
        return bg

    background = frontmatter.get("background")
    if isinstance(background, dict):
        default_bg = background.get("default")
        if isinstance(default_bg, str) and default_bg.strip():
            return default_bg
    raise ValidationError(
        "Markdown frontmatter requires top-level 'bg' or 'background.default'."
    )


def resolve_markdown_characters(
    frontmatter: Dict[str, Any],
) -> Dict[str, Dict[str, Any]]:
    defaults = frontmatter.get("defaults")
    if not isinstance(defaults, dict):
        return {}
    characters = defaults.get("characters")
    if not isinstance(characters, dict):
        return {}
    return {
        name: value
        for name, value in characters.items()
        if isinstance(value, dict)
    }


def resolve_markdown_render_config(frontmatter: Dict[str, Any]) -> Dict[str, Any]:
    video_cfg = _mapping(frontmatter.get("video"))
    subtitle_cfg = _mapping(frontmatter.get("subtitle"))
    markdown_cfg = _mapping(frontmatter.get("markdown"))
    layer_cfg = _mapping(markdown_cfg.get("layer"))
    panel_cfg = _mapping(markdown_cfg.get("panel"))
    text_cfg = _mapping(markdown_cfg.get("text"))

    width = _coerce_positive_int(video_cfg.get("width"), 1280)
    height = _coerce_positive_int(video_cfg.get("height"), 720)
    margin = _resolve_box_spacing(
        panel_cfg.get("margin"),
        x_default=max(40, int(round(width * 0.14))),
        y_default=max(32, int(round(height * 0.06))),
    )
    padding = _resolve_box_spacing(
        panel_cfg.get("padding"),
        x_default=max(28, int(round(width * 0.045))),
        y_default=max(24, int(round(height * 0.05))),
    )
    preferred_font_size = _coerce_positive_int(
        text_cfg.get("font_size"), max(30, int(round(height * 0.07)))
    )
    min_font_size = min(
        _coerce_positive_int(
            text_cfg.get("min_font_size"),
            max(18, int(round(preferred_font_size * 0.58))),
        ),
        preferred_font_size,
    )

    return {
        "canvas": {"width": width, "height": height},
        "layer": _resolve_layer_config(layer_cfg),
        "panel": {
            "margin": margin,
            "padding": padding,
            "background": _resolve_panel_background(panel_cfg, width, height),
        },
        "text": _resolve_text_config(
            text_cfg,
            subtitle_cfg,
            preferred_font_size=preferred_font_size,
            min_font_size=min_font_size,
        ),
    }


def _mapping(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _resolve_box_spacing(
    value: Any,
    *,
    x_default: int,
    y_default: int,
) -> Dict[str, int]:
    left, top, right, bottom = _normalize_padding(value, max(x_default, y_default))
    if value is None:
        left = right = x_default
        top = bottom = y_default
    return {
        "left": int(left),
        "top": int(top),
        "right": int(right),
        "bottom": int(bottom),
    }


def _resolve_layer_config(layer_cfg: Dict[str, Any]) -> Dict[str, Any]:
    position = _mapping(layer_cfg.get("position"))
    return {
        "scale": _coerce_float(layer_cfg.get("scale"), 0.92, minimum=0.1),
        "anchor": str(layer_cfg.get("anchor", "middle_center")),
        "position": {
            "x": _coerce_number(position.get("x"), 0),
            "y": _coerce_number(position.get("y"), 0),
        },
    }


def _resolve_panel_background(
    panel_cfg: Dict[str, Any], width: int, height: int
) -> Dict[str, Any]:
    background: Dict[str, Any] = {
        "color": "#0F172A",
        "opacity": 0.9,
        "radius": max(18, int(round(min(width, height) * 0.035))),
        "border_color": "#E2E8F0",
        "border_width": 2,
        "border_opacity": 0.75,
    }
    keys = (
        "color",
        "opacity",
        "radius",
        "border_color",
        "border_width",
        "border_opacity",
        "image",
        "image_opacity",
    )
    for key in keys:
        if panel_cfg.get(key) is not None:
            background[key] = panel_cfg[key]
    nested = panel_cfg.get("background")
    if isinstance(nested, dict):
        background.update({key: value for key, value in nested.items() if value is not None})
    return background


def _resolve_text_config(
    text_cfg: Dict[str, Any],
    subtitle_cfg: Dict[str, Any],
    *,
    preferred_font_size: int,
    min_font_size: int,
) -> Dict[str, Any]:
    return {
        "font_path": str(
            text_cfg.get("font_path")
            or subtitle_cfg.get("font_path")
            or "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf"
        ),
        "font_size": preferred_font_size,
        "min_font_size": min_font_size,
        "line_spacing": text_cfg.get("line_spacing"),
        "color": str(text_cfg.get("color", "#F8FAFC")),
        "heading_scale": _coerce_float(
            text_cfg.get("heading_scale"), 1.28, minimum=1.0
        ),
        "subheading_scale": _coerce_float(
            text_cfg.get("subheading_scale"), 1.12, minimum=1.0
        ),
        "list_indent": _coerce_positive_int(text_cfg.get("list_indent"), 28),
    }


def _coerce_positive_int(value: Any, default: int) -> int:
    try:
        result = int(value)
        return result if result > 0 else int(default)
    except (TypeError, ValueError):
        return int(default)


def _coerce_float(
    value: Any, default: float, *, minimum: float | None = None
) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        result = float(default)
    return max(minimum, result) if minimum is not None else result


def _coerce_number(value: Any, default: int | float) -> int | float:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return value
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    return int(numeric) if numeric.is_integer() else numeric
