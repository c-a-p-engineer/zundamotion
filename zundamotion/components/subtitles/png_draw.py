"""Picklable subtitle PNG drawing pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from PIL import Image, ImageDraw, ImageFont

from .png_style import (
    _background_is_visible,
    _build_background_layer_cached,
    _extract_background_config,
    _normalize_padding,
)
from .png_text import _load_font_with_fallback, wrap_render_text


@dataclass(frozen=True)
class DrawStyle:
    font: ImageFont.FreeTypeFont
    font_color: Any
    stroke_width: int
    stroke_color: Any
    max_width: int
    padding: tuple[int, int, int, int]
    background: Dict[str, Any]
    line_spacing_extra: int
    line_spacing_multiplier: float
    align: str


@dataclass(frozen=True)
class TextLayout:
    lines: List[str]
    bboxes: List[tuple[int, int, int, int]]
    heights: List[int]
    spacing: List[int]
    text_width: int
    text_height: int


def _int_value(value: Any, default: int, *, minimum: int | None = None) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        result = default
    return max(minimum, result) if minimum is not None else result


def _float_value(value: Any, default: float, *, minimum: float | None = None) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        result = default
    return max(minimum, result) if minimum is not None else result


def _resolve_draw_style(style: Dict[str, Any]) -> DrawStyle:
    font_path = style.get("font_path", "assets/fonts/NotoSansJP-Regular.otf")
    font_size = _int_value(style.get("font_size", 64), 64, minimum=1)
    max_width = _int_value(style.get("max_pixel_width", 1800), 1800, minimum=1)
    stroke_width = _int_value(style.get("stroke_width", 0) or 0, 0, minimum=0)
    base_padding = _int_value(style.get("box_padding", 10), 10, minimum=0)
    background = _extract_background_config(style)
    default_box = style.get("box_color", "black@0.5")
    if "color" not in background and default_box:
        background["color"] = default_box
    padding_value = background.get("padding", base_padding) if _background_is_visible(background) else 0
    align = str(style.get("text_align", style.get("align", "center")) or "center").strip().lower()
    if align not in {"left", "center", "right"}:
        align = "center"
    return DrawStyle(
        font=_load_font_with_fallback(str(font_path), font_size),
        font_color=style.get("font_color", "white"),
        stroke_width=stroke_width,
        stroke_color=style.get("stroke_color", "black"),
        max_width=max_width,
        padding=_normalize_padding(padding_value, base_padding),
        background=background,
        line_spacing_extra=_int_value(style.get("line_spacing_offset_per_line", 0) or 0, 0, minimum=0),
        line_spacing_multiplier=_float_value(style.get("line_spacing_multiplier", 1.0) or 1.0, 1.0, minimum=1.0),
        align=align,
    )


def _line_bbox(font: ImageFont.FreeTypeFont, line: str, stroke_width: int) -> tuple[int, int, int, int]:
    bbox = None
    includes_stroke = False
    if hasattr(font, "getbbox"):
        try:
            bbox = font.getbbox(line, stroke_width=stroke_width)
            includes_stroke = True
        except TypeError:
            bbox = font.getbbox(line)
        except Exception:
            pass
    if bbox is None:
        width, height = font.getsize(line)
        bbox = (0, 0, width, height)
    if stroke_width and not includes_stroke:
        x0, y0, x1, y1 = bbox
        bbox = (x0 - stroke_width, y0 - stroke_width, x1 + stroke_width, y1 + stroke_width)
    return tuple(int(value) for value in bbox)


def _line_spacing(heights: List[int], extra: int, multiplier: float) -> List[int]:
    result: List[int] = []
    ratio = multiplier - 1.0
    for height in heights[:-1]:
        gap = extra
        if ratio > 0.0:
            gap += max(0, int(round(height * ratio)))
        result.append(max(0, gap))
    return result


def _layout_text(text: str, style: Dict[str, Any], resolved: DrawStyle) -> TextLayout:
    wrapped = wrap_render_text(text, resolved.font, style, resolved.max_width)
    lines = wrapped.split("\n")
    bboxes = [_line_bbox(resolved.font, line, resolved.stroke_width) for line in lines]
    widths = [bbox[2] - bbox[0] for bbox in bboxes]
    heights = [bbox[3] - bbox[1] for bbox in bboxes]
    spacing = _line_spacing(heights, resolved.line_spacing_extra, resolved.line_spacing_multiplier)
    return TextLayout(
        lines=lines, bboxes=bboxes, heights=heights, spacing=spacing,
        text_width=max(widths, default=0),
        text_height=sum(heights) + sum(spacing),
    )


def _baseline_x(align: str, padding_left: int, text_width: int, bbox: tuple[int, int, int, int]) -> float:
    x0, _y0, x1, _y1 = bbox
    line_width = x1 - x0
    if align == "left":
        return float(padding_left - x0)
    if align == "right":
        return padding_left + max(0.0, text_width - line_width) - x0
    return padding_left + (text_width - line_width) / 2 - x0 if text_width > 0 else float(padding_left - x0)


def _draw_text(image: Image.Image, layout: TextLayout, style: DrawStyle) -> None:
    draw = ImageDraw.Draw(image)
    left, top, _right, _bottom = style.padding
    current_y = float(top)
    for index, line in enumerate(layout.lines):
        bbox = layout.bboxes[index]
        draw.text(
            (_baseline_x(style.align, left, layout.text_width, bbox), current_y - bbox[1]),
            line, font=style.font, fill=style.font_color,
            stroke_width=style.stroke_width, stroke_fill=style.stroke_color,
        )
        current_y += layout.heights[index]
        if index < len(layout.lines) - 1 and layout.spacing:
            current_y += layout.spacing[index]


def _save_options(style: Dict[str, Any]) -> Dict[str, Any]:
    options: Dict[str, Any] = {}
    try:
        value = style.get("png_compress_level", style.get("compress_level"))
        if value is not None:
            options["compress_level"] = max(0, min(9, int(value)))
    except (TypeError, ValueError):
        pass
    if "png_optimize" in style:
        options["optimize"] = bool(style.get("png_optimize"))
    elif "optimize" in style:
        options["optimize"] = bool(style.get("optimize"))
    return options


def _render_subtitle_png(text: str, style: Dict[str, Any], out_path: str) -> Tuple[int, int]:
    """ProcessPool-picklable entry point for deterministic PNG rendering."""
    resolved = _resolve_draw_style(style)
    layout = _layout_text(text, style, resolved)
    left, top, right, bottom = resolved.padding
    width = max(1, int(layout.text_width + left + right))
    height = max(1, int(layout.text_height + top + bottom))
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    background = _build_background_layer_cached((width, height), resolved.background)
    if background is not None:
        image = Image.alpha_composite(image, background)
    _draw_text(image, layout, resolved)
    image.save(out_path, **_save_options(style))
    return width, height
