"""Font loading, wrapping, and text width helpers for subtitle PNG rendering."""

from __future__ import annotations

import os
import statistics
from typing import List

from PIL import ImageFont

from ...utils.subtitle_text import wrap_subtitle_text_by_display_width

_FONT_CACHE: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def _load_font_with_fallback(font_path: str, font_size: int) -> ImageFont.FreeTypeFont:
    try:
        key = (font_path or "", int(font_size))
        if key in _FONT_CACHE:
            return _FONT_CACHE[key]
    except Exception:
        key = (font_path or "", font_size)
    for candidate in [font_path] if font_path else []:
        try:
            font = ImageFont.truetype(candidate, font_size)
            _FONT_CACHE[key] = font
            return font
        except Exception:
            pass
    candidates = [
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        "/Library/Fonts/Arial Unicode.ttf",
        "/Library/Fonts/Arial.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
    ]
    for candidate in candidates:
        try:
            if os.path.exists(candidate):
                font = ImageFont.truetype(candidate, font_size)
                _FONT_CACHE[key] = font
                return font
        except Exception:
            continue
    try:
        font = ImageFont.load_default()
        _FONT_CACHE[key] = font
        return font
    except Exception:
        return ImageFont.truetype("DejaVuSans.ttf", font_size)


def _measure_text_width(font: ImageFont.FreeTypeFont, text: str) -> int:
    if hasattr(font, "getbbox"):
        try:
            bbox = font.getbbox(text)
            return max(0, bbox[2] - bbox[0])
        except Exception:
            pass
    width, _ = font.getsize(text)
    return max(0, int(width))


def _estimate_auto_max_chars(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> int:
    if max_width <= 0:
        return 0
    chars = [char for char in text.replace("\\n", "\n") if not char.isspace()]
    if not chars:
        chars = list("あいうえお漢字ABC123")
    widths = [_measure_text_width(font, char) for char in chars[:64]]
    widths = [width for width in widths if width > 0]
    if not widths:
        widths = [max(1, _measure_text_width(font, "あ") or _measure_text_width(font, "W"))]
    median = statistics.median(widths)
    return 0 if median <= 0 else max(4, int(max_width // median))


def _fits_within_width(wrapped_text: str, font: ImageFont.FreeTypeFont, max_width: int) -> bool:
    return all(_measure_text_width(font, line) <= max_width for line in wrapped_text.split("\n"))


def _wrap_text_by_pixel_static(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> str:
    lines: List[str] = []
    for paragraph in text.replace("\\n", "\n").split("\n"):
        if not paragraph:
            lines.append("")
            continue
        current = ""
        for word in paragraph.split(" "):
            candidate = current + " " + word
            if _measure_text_width(font, candidate) <= max_width:
                current = candidate
            else:
                lines.append(current.strip())
                current = word
        lines.append(current.strip())
    return "\n".join(lines)


def _wrap_text_by_chars_static(text: str, max_chars: int) -> str:
    return wrap_subtitle_text_by_display_width(text, max_chars)


def wrap_render_text(text: str, font: ImageFont.FreeTypeFont, style: dict, max_width: int) -> str:
    wrap_mode = str(style.get("wrap_mode") or "").strip().lower()
    max_chars = style.get("max_chars_per_line")
    if wrap_mode != "chars" and (max_chars is None or wrap_mode == "pixel"):
        return _wrap_text_by_pixel_static(text, font, max_width)
    auto = isinstance(max_chars, str) and max_chars.strip().lower() == "auto"
    if not auto:
        try:
            value = int(max_chars) if max_chars is not None else 0
        except (TypeError, ValueError):
            value = 0
        return wrap_subtitle_text_by_display_width(text, value)
    value = _estimate_auto_max_chars(text, font, max_width)
    wrapped = wrap_subtitle_text_by_display_width(text, value)
    while value > 4 and not _fits_within_width(wrapped, font, max_width):
        value -= 1
        wrapped = wrap_subtitle_text_by_display_width(text, value)
    return wrapped
