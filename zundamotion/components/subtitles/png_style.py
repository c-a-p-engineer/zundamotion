"""Subtitle PNG style/background resolution and reusable background layers."""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

from PIL import Image, ImageColor, ImageDraw

logger = logging.getLogger(__name__)
try:
    RESAMPLE_LANCZOS = Image.Resampling.LANCZOS  # type: ignore[attr-defined]
except AttributeError:  # pragma: no cover
    RESAMPLE_LANCZOS = Image.LANCZOS


def _clamp_float(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, value))


def _coerce_optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return None


def _to_padding_int(source: Any, fallback: int) -> int:
    try:
        return max(0, int(source))
    except (TypeError, ValueError):
        return max(0, int(fallback))


def _normalize_padding(padding: Any, default: int) -> tuple[int, int, int, int]:
    """Normalize padding values to (left, top, right, bottom)."""
    if padding is None:
        value = _to_padding_int(default, default)
        return value, value, value, value
    if isinstance(padding, (int, float)):
        value = _to_padding_int(padding, default)
        return value, value, value, value
    if isinstance(padding, (list, tuple)):
        if len(padding) == 2:
            horizontal = _to_padding_int(padding[0], default)
            vertical = _to_padding_int(padding[1], default)
            return horizontal, vertical, horizontal, vertical
        if len(padding) == 4:
            return tuple(_to_padding_int(item, default) for item in padding)  # type: ignore[return-value]
    if isinstance(padding, dict):
        horizontal = padding.get("x", padding.get("horizontal"))
        vertical = padding.get("y", padding.get("vertical"))
        return (
            _to_padding_int(padding.get("left", horizontal), default),
            _to_padding_int(padding.get("top", vertical), default),
            _to_padding_int(padding.get("right", horizontal), default),
            _to_padding_int(padding.get("bottom", vertical), default),
        )
    value = _to_padding_int(default, default)
    return value, value, value, value


def _extract_background_config(style: Dict[str, Any]) -> Dict[str, Any]:
    background: Dict[str, Any] = {}
    background_style = style.get("background")
    if isinstance(background_style, dict):
        background.update(background_style)
    elif background_style:
        background["color"] = background_style
    mapping = {
        "background_color": "color", "box_color": "color",
        "background_show": "show", "background_visible": "show",
        "background_enabled": "show", "background_opacity": "opacity",
        "background_radius": "radius", "background_corner_radius": "radius",
        "background_border_color": "border_color", "background_border_width": "border_width",
        "background_border_opacity": "border_opacity", "background_padding": "padding",
        "background_image": "image", "background_image_path": "image",
        "background_image_opacity": "image_opacity",
    }
    for key, target in mapping.items():
        if key in style and style[key] is not None and target not in background:
            background[target] = style[key]
    if "padding" not in background and "box_padding" in style:
        background["padding"] = style["box_padding"]
    return background


def _sequence_rgba(color_value: Any, explicit_opacity: Any) -> tuple[int, int, int, int] | None:
    if not isinstance(color_value, (list, tuple)):
        return None
    if len(color_value) == 4:
        try:
            return tuple(int(max(0, min(255, c))) for c in color_value)  # type: ignore[return-value]
        except (TypeError, ValueError):
            return None
    if len(color_value) != 3:
        return None
    try:
        rgb = [int(max(0, min(255, c))) for c in color_value]
    except (TypeError, ValueError):
        return None
    alpha = 255
    if explicit_opacity is not None:
        try:
            alpha = int(round(_clamp_float(float(explicit_opacity)) * 255))
        except (TypeError, ValueError):
            pass
    return rgb[0], rgb[1], rgb[2], alpha


def _resolve_rgba(color_value: Any, explicit_opacity: Any = None) -> tuple[int, int, int, int] | None:
    if color_value is None:
        return None
    sequence = _sequence_rgba(color_value, explicit_opacity)
    if sequence is not None:
        return sequence
    color_str = str(color_value).strip()
    if not color_str:
        return None
    inline_alpha: float | None = None
    if "@" in color_str:
        base, _, alpha_part = color_str.partition("@")
        color_str = base.strip()
        try:
            inline_alpha = float(alpha_part)
        except ValueError:
            pass
    try:
        rgba = ImageColor.getrgb(color_str)
    except ValueError:
        return None
    r, g, b = rgba[:3]
    base_alpha = rgba[3] if len(rgba) == 4 else None
    if explicit_opacity is not None:
        try:
            alpha = int(round(_clamp_float(float(explicit_opacity)) * 255))
        except (TypeError, ValueError):
            alpha = base_alpha if base_alpha is not None else 255
    elif inline_alpha is not None:
        alpha = int(round(_clamp_float(inline_alpha) * 255))
    elif base_alpha is not None:
        alpha = int(max(0, min(255, base_alpha)))
    else:
        alpha = 255
    return int(r), int(g), int(b), alpha


def _background_is_visible(config: Dict[str, Any]) -> bool:
    explicit = _coerce_optional_bool(config.get("show", config.get("visible", config.get("enabled"))))
    if explicit is False:
        return False
    fill = _resolve_rgba(config.get("color") or config.get("fill"), config.get("opacity"))
    image_path = config.get("image") or config.get("image_path")
    outline = _resolve_rgba(config.get("border_color") or config.get("outline_color"), config.get("border_opacity"))
    try:
        border_width = max(0, int(config.get("border_width", 0)))
    except (TypeError, ValueError):
        border_width = 0
    return bool(fill or (outline and border_width > 0) or image_path)


def _shape_mask(size: tuple[int, int], radius: int) -> Image.Image:
    width, height = size
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    bbox = (0, 0, max(0, width - 1), max(0, height - 1))
    if radius > 0:
        draw.rounded_rectangle(bbox, radius=radius, fill=255)
    else:
        draw.rectangle(bbox, fill=255)
    return mask


def _paste_background_image(
    layer: Image.Image, mask: Image.Image, size: tuple[int, int],
    image_path: Any, image_opacity: Any, fallback_opacity: Any,
) -> None:
    if not image_path:
        return
    try:
        with Image.open(image_path) as src:
            bg_image = src.convert("RGBA")
        if bg_image.size != size:
            bg_image = bg_image.resize(size, RESAMPLE_LANCZOS)
        opacity = image_opacity if image_opacity is not None else fallback_opacity
        if opacity is not None:
            factor = _clamp_float(float(opacity))
            if factor < 1.0:
                r, g, b, a = bg_image.split()
                a = a.point(lambda value: int(round(value * factor)))
                bg_image = Image.merge("RGBA", (r, g, b, a))
        layer.paste(bg_image, (0, 0), mask=mask)
    except FileNotFoundError:
        logger.warning("背景画像が見つかりません: %s", image_path)
    except Exception as exc:  # pragma: no cover
        logger.warning("背景画像の読み込みに失敗しました: %s", exc)


def _draw_outline(layer: Image.Image, config: Dict[str, Any], size: tuple[int, int], radius: int) -> None:
    outline = _resolve_rgba(config.get("border_color") or config.get("outline_color"), config.get("border_opacity"))
    try:
        width = max(0, int(config.get("border_width", 0)))
    except (TypeError, ValueError):
        width = 0
    if not outline or width <= 0:
        return
    draw = ImageDraw.Draw(layer)
    inset = width / 2
    w, h = size
    bbox = (inset, inset, max(inset, w - 1 - inset), max(inset, h - 1 - inset))
    outline_radius = max(0.0, float(radius) - inset)
    if radius > 0:
        draw.rounded_rectangle(bbox, radius=outline_radius, outline=outline, width=width)
    else:
        draw.rectangle(bbox, outline=outline, width=width)


def _build_background_layer(size: tuple[int, int], config: Dict[str, Any]) -> Image.Image | None:
    width, height = size
    if width <= 0 or height <= 0 or not _background_is_visible(config):
        return None
    try:
        radius = max(0, int(config.get("radius", config.get("corner_radius", 0))))
    except (TypeError, ValueError):
        radius = 0
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    mask = _shape_mask(size, radius)
    fill = _resolve_rgba(config.get("color") or config.get("fill"), config.get("opacity"))
    if fill:
        layer.paste(Image.new("RGBA", size, fill), (0, 0), mask=mask)
    _paste_background_image(
        layer, mask, size, config.get("image") or config.get("image_path"),
        config.get("image_opacity"), config.get("opacity"),
    )
    _draw_outline(layer, config, size, radius)
    return layer


def _background_layer_cache_key(size: tuple[int, int], config: Dict[str, Any]) -> tuple[Any, ...] | None:
    width, height = size
    if width <= 0 or height <= 0 or not _background_is_visible(config):
        return None
    image_raw = config.get("image") or config.get("image_path")
    image_signature = None
    if image_raw:
        try:
            path = Path(str(image_raw)).resolve()
            stat = path.stat()
            image_signature = (str(path), int(stat.st_mtime), int(stat.st_size))
        except Exception:
            return None
    try:
        border_width = max(0, int(config.get("border_width", 0)))
    except (TypeError, ValueError):
        border_width = 0
    try:
        radius = max(0, int(config.get("radius", config.get("corner_radius", 0))))
    except (TypeError, ValueError):
        radius = 0
    return (
        int(width), int(height),
        _resolve_rgba(config.get("color") or config.get("fill"), config.get("opacity")),
        image_signature, str(config.get("image_opacity", "")),
        _resolve_rgba(config.get("border_color") or config.get("outline_color"), config.get("border_opacity")),
        border_width, radius,
    )


@lru_cache(maxsize=128)
def _build_background_layer_cached_from_key(key: tuple[Any, ...]) -> Image.Image | None:
    width, height, fill, image_signature, image_opacity, outline, border_width, radius = key
    config: Dict[str, Any] = {
        "color": fill, "image_opacity": None if image_opacity == "" else image_opacity,
        "border_color": outline, "border_width": border_width, "radius": radius,
    }
    if image_signature:
        config["image"] = image_signature[0]
    return _build_background_layer((int(width), int(height)), config)


def _build_background_layer_cached(size: tuple[int, int], config: Dict[str, Any]) -> Image.Image | None:
    key = _background_layer_cache_key(size, config)
    return _build_background_layer(size, config) if key is None else _build_background_layer_cached_from_key(key)
