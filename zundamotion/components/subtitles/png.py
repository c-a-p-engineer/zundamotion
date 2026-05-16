import atexit
import hashlib
import json
import logging
import os
import statistics
import time
from concurrent.futures import ProcessPoolExecutor
from functools import lru_cache
from pathlib import Path  # Pathをインポート
from typing import Any, Dict, Tuple

from PIL import Image, ImageColor, ImageDraw, ImageFont

from ...cache import CacheManager

logger = logging.getLogger(__name__)

# Module-level font cache to reduce load/latency jitter inside worker processes
_FONT_CACHE: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}
_SUBTITLE_EXECUTOR: ProcessPoolExecutor | None = None
_SUBTITLE_EXECUTOR_WORKERS: int | None = None

try:
    RESAMPLE_LANCZOS = Image.Resampling.LANCZOS  # type: ignore[attr-defined]
except AttributeError:  # pragma: no cover - Pillow<9 fallback
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


def _normalize_padding(padding: Any, default: int) -> tuple[int, int, int, int]:
    """Normalize padding values to (left, top, right, bottom)."""

    def _to_int(source: Any, fallback: int) -> int:
        try:
            return max(0, int(source))
        except (TypeError, ValueError):
            return max(0, int(fallback))

    if padding is None:
        value = _to_int(default, default)
        return value, value, value, value
    if isinstance(padding, (int, float)):
        value = _to_int(padding, default)
        return value, value, value, value
    if isinstance(padding, (list, tuple)):
        if len(padding) == 2:
            horizontal = _to_int(padding[0], default)
            vertical = _to_int(padding[1], default)
            return horizontal, vertical, horizontal, vertical
        if len(padding) == 4:
            return (
                _to_int(padding[0], default),
                _to_int(padding[1], default),
                _to_int(padding[2], default),
                _to_int(padding[3], default),
            )
    if isinstance(padding, dict):
        horizontal = padding.get("x", padding.get("horizontal"))
        vertical = padding.get("y", padding.get("vertical"))
        return (
            _to_int(padding.get("left", horizontal), default),
            _to_int(padding.get("top", vertical), default),
            _to_int(padding.get("right", horizontal), default),
            _to_int(padding.get("bottom", vertical), default),
        )
    value = _to_int(default, default)
    return value, value, value, value


def _extract_background_config(style: Dict[str, Any]) -> Dict[str, Any]:
    """Merge legacy/background styling keys into a unified dict."""

    background: Dict[str, Any] = {}
    background_style = style.get("background")
    if isinstance(background_style, dict):
        background.update(background_style)
    elif background_style:
        background["color"] = background_style

    mapping = {
        "background_color": "color",
        "box_color": "color",
        "background_show": "show",
        "background_visible": "show",
        "background_enabled": "show",
        "background_opacity": "opacity",
        "background_radius": "radius",
        "background_corner_radius": "radius",
        "background_border_color": "border_color",
        "background_border_width": "border_width",
        "background_border_opacity": "border_opacity",
        "background_padding": "padding",
        "background_image": "image",
        "background_image_path": "image",
        "background_image_opacity": "image_opacity",
    }
    for key, target in mapping.items():
        if key in style and style[key] is not None and target not in background:
            background[target] = style[key]

    if "padding" not in background and "box_padding" in style:
        background["padding"] = style["box_padding"]

    return background


def _resolve_rgba(color_value: Any, explicit_opacity: Any = None) -> tuple[int, int, int, int] | None:
    """Convert color specifications into RGBA tuples."""

    if color_value is None:
        return None

    if isinstance(color_value, (list, tuple)):
        if len(color_value) == 4:
            try:
                return tuple(int(max(0, min(255, c))) for c in color_value)  # type: ignore[return-value]
            except (TypeError, ValueError):
                return None
        if len(color_value) == 3:
            try:
                rgb = [int(max(0, min(255, c))) for c in color_value]
            except (TypeError, ValueError):
                return None
            alpha = 255
            if explicit_opacity is not None:
                try:
                    alpha = int(round(_clamp_float(float(explicit_opacity)) * 255))
                except (TypeError, ValueError):
                    alpha = 255
            return rgb[0], rgb[1], rgb[2], alpha

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
            inline_alpha = None

    try:
        rgb = ImageColor.getrgb(color_str)
    except ValueError:
        return None

    if isinstance(rgb, tuple) and len(rgb) >= 3:
        r, g, b = rgb[:3]
        base_alpha: int | None = None
        if len(rgb) == 4:
            base_alpha = rgb[3]
    else:  # pragma: no cover - ImageColor should always return tuple
        r, g, b = rgb[0], rgb[1], rgb[2]
        base_alpha = None

    final_alpha: int
    if explicit_opacity is not None:
        try:
            final_alpha = int(round(_clamp_float(float(explicit_opacity)) * 255))
        except (TypeError, ValueError):
            final_alpha = base_alpha if base_alpha is not None else 255
    elif inline_alpha is not None:
        final_alpha = int(round(_clamp_float(inline_alpha) * 255))
    elif base_alpha is not None:
        final_alpha = int(max(0, min(255, base_alpha)))
    else:
        final_alpha = 255

    return int(r), int(g), int(b), final_alpha


def _background_is_visible(config: Dict[str, Any]) -> bool:
    explicit_flag = _coerce_optional_bool(
        config.get("show", config.get("visible", config.get("enabled")))
    )
    if explicit_flag is False:
        return False

    fill_rgba = _resolve_rgba(config.get("color") or config.get("fill"), config.get("opacity"))
    image_path = config.get("image") or config.get("image_path")
    outline_rgba = _resolve_rgba(
        config.get("border_color") or config.get("outline_color"),
        config.get("border_opacity"),
    )
    try:
        border_width = max(0, int(config.get("border_width", 0)))
    except (TypeError, ValueError):
        border_width = 0

    has_drawable = any(
        [fill_rgba, outline_rgba and border_width > 0, bool(image_path)]
    )
    if explicit_flag is True:
        return has_drawable
    return has_drawable


def _build_background_layer(
    size: tuple[int, int], config: Dict[str, Any]
) -> Image.Image | None:
    width, height = size
    if width <= 0 or height <= 0:
        return None
    if not _background_is_visible(config):
        return None

    fill_rgba = _resolve_rgba(config.get("color") or config.get("fill"), config.get("opacity"))
    image_path = config.get("image") or config.get("image_path")
    image_opacity = config.get("image_opacity")
    outline_rgba = _resolve_rgba(
        config.get("border_color") or config.get("outline_color"),
        config.get("border_opacity"),
    )
    try:
        border_width = max(0, int(config.get("border_width", 0)))
    except (TypeError, ValueError):
        border_width = 0
    try:
        radius = max(0, int(config.get("radius", config.get("corner_radius", 0))))
    except (TypeError, ValueError):
        radius = 0

    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    shape_mask = Image.new("L", size, 0)
    mask_draw = ImageDraw.Draw(shape_mask)
    bbox = (0, 0, max(0, width - 1), max(0, height - 1))
    if radius > 0:
        mask_draw.rounded_rectangle(bbox, radius=radius, fill=255)
    else:
        mask_draw.rectangle(bbox, fill=255)

    if fill_rgba:
        fill_img = Image.new("RGBA", size, fill_rgba)
        layer.paste(fill_img, (0, 0), mask=shape_mask)

    if image_path:
        try:
            with Image.open(image_path) as src:
                bg_image = src.convert("RGBA")
            if bg_image.size != size:
                bg_image = bg_image.resize(size, RESAMPLE_LANCZOS)
            opacity_source = image_opacity
            if opacity_source is None and config.get("opacity") is not None:
                opacity_source = config.get("opacity")
            if opacity_source is not None:
                try:
                    factor = _clamp_float(float(opacity_source))
                    if factor < 1.0:
                        r_band, g_band, b_band, a_band = bg_image.split()
                        a_band = a_band.point(
                            lambda v: int(round(v * factor))
                        )
                        bg_image = Image.merge("RGBA", (r_band, g_band, b_band, a_band))
                except (TypeError, ValueError):
                    pass
            layer.paste(bg_image, (0, 0), mask=shape_mask)
        except FileNotFoundError:
            logger.warning("背景画像が見つかりません: %s", image_path)
        except Exception as exc:  # pragma: no cover - unexpected PIL errors
            logger.warning("背景画像の読み込みに失敗しました: %s", exc)

    if outline_rgba and border_width > 0:
        draw = ImageDraw.Draw(layer)
        inset = border_width / 2
        outline_bbox = (
            inset,
            inset,
            max(inset, width - 1 - inset),
            max(inset, height - 1 - inset),
        )
        radius_outline = max(0.0, float(radius) - inset)
        if radius > 0:
            draw.rounded_rectangle(
                outline_bbox,
                radius=radius_outline,
                outline=outline_rgba,
                width=border_width,
            )
        else:
            draw.rectangle(
                outline_bbox,
                outline=outline_rgba,
                width=border_width,
            )

    return layer


def _background_layer_cache_key(
    size: tuple[int, int], config: Dict[str, Any]
) -> tuple[Any, ...] | None:
    width, height = size
    if width <= 0 or height <= 0:
        return None
    if not _background_is_visible(config):
        return None

    image_path_raw = config.get("image") or config.get("image_path")
    image_signature: tuple[str, int | None, int | None] | None = None
    if image_path_raw:
        try:
            image_path = Path(str(image_path_raw)).resolve()
            stat = image_path.stat()
            image_signature = (str(image_path), int(stat.st_mtime), int(stat.st_size))
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
        int(width),
        int(height),
        _resolve_rgba(config.get("color") or config.get("fill"), config.get("opacity")),
        image_signature,
        str(config.get("image_opacity", "")),
        _resolve_rgba(
            config.get("border_color") or config.get("outline_color"),
            config.get("border_opacity"),
        ),
        border_width,
        radius,
    )


@lru_cache(maxsize=128)
def _build_background_layer_cached_from_key(cache_key: tuple[Any, ...]) -> Image.Image | None:
    (
        width,
        height,
        fill_rgba,
        image_signature,
        image_opacity,
        outline_rgba,
        border_width,
        radius,
    ) = cache_key

    config: Dict[str, Any] = {
        "color": fill_rgba,
        "image_opacity": None if image_opacity == "" else image_opacity,
        "border_color": outline_rgba,
        "border_width": border_width,
        "radius": radius,
    }
    if image_signature:
        config["image"] = image_signature[0]
    return _build_background_layer((int(width), int(height)), config)


def _build_background_layer_cached(
    size: tuple[int, int], config: Dict[str, Any]
) -> Image.Image | None:
    cache_key = _background_layer_cache_key(size, config)
    if cache_key is None:
        return _build_background_layer(size, config)
    return _build_background_layer_cached_from_key(cache_key)


def _subtitle_meta_path(png_path: Path) -> Path:
    return png_path.with_suffix(".json")


def _read_subtitle_dimensions_meta(png_path: Path) -> Dict[str, int] | None:
    meta_path = _subtitle_meta_path(png_path)
    if not meta_path.exists():
        return None
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        width = int(meta.get("w", 0))
        height = int(meta.get("h", 0))
        if width > 0 and height > 0:
            return {"w": width, "h": height}
    except Exception:
        return None
    return None


def _write_subtitle_dimensions_meta(png_path: Path, width: int, height: int) -> None:
    try:
        with open(_subtitle_meta_path(png_path), "w", encoding="utf-8") as f:
            json.dump({"w": int(width), "h": int(height)}, f, ensure_ascii=False)
    except Exception:
        logger.debug("Failed to write subtitle PNG metadata: %s", png_path, exc_info=True)


def _inspect_subtitle_png_bbox(png_path: Path) -> Dict[str, int | bool | str]:
    with Image.open(png_path) as img:
        rgba = img.convert("RGBA")
        alpha = rgba.getchannel("A")
        bbox = alpha.getbbox()
        width, height = rgba.size
    if bbox is None:
        return {
            "width": width,
            "height": height,
            "transparent_left": width,
            "transparent_top": height,
            "transparent_right": width,
            "transparent_bottom": height,
            "full_canvas": False,
            "bbox_mode": "empty",
        }
    x0, y0, x1, y1 = bbox
    left = x0
    top = y0
    right = max(0, width - x1)
    bottom = max(0, height - y1)
    bbox_mode = "tight" if any((left, top, right, bottom)) else "full"
    return {
        "width": width,
        "height": height,
        "transparent_left": left,
        "transparent_top": top,
        "transparent_right": right,
        "transparent_bottom": bottom,
        "full_canvas": bbox_mode == "full",
        "bbox_mode": bbox_mode,
    }


def _measure_text_width(font: ImageFont.FreeTypeFont, text: str) -> int:
    if hasattr(font, "getbbox"):
        try:
            bbox = font.getbbox(text)
            return max(0, bbox[2] - bbox[0])
        except Exception:
            pass
    width, _ = font.getsize(text)
    return max(0, int(width))


def _estimate_auto_max_chars(
    text: str, font: ImageFont.FreeTypeFont, max_width: int
) -> int:
    if max_width <= 0:
        return 0

    sample_chars = [char for char in text.replace("\\n", "\n") if not char.isspace()]
    if not sample_chars:
        sample_chars = list("あいうえお漢字ABC123")

    widths = []
    for char in sample_chars[:64]:
        width = _measure_text_width(font, char)
        if width > 0:
            widths.append(width)

    if not widths:
        fallback_width = _measure_text_width(font, "あ") or _measure_text_width(font, "W")
        widths.append(max(1, fallback_width))

    median_width = statistics.median(widths)
    if median_width <= 0:
        return 0

    return max(4, int(max_width // median_width))


def _fits_within_width(
    wrapped_text: str, font: ImageFont.FreeTypeFont, max_width: int
) -> bool:
    for line in wrapped_text.split("\n"):
        if _measure_text_width(font, line) > max_width:
            return False
    return True


class SubtitlePNGRenderer:
    """
    Generates and caches subtitle images using Pillow.
    """

    def __init__(self, cache_manager: CacheManager):
        self.cache_manager = cache_manager
        self.subtitle_cache_dir = (
            cache_manager.cache_dir / "subtitles"
        )  # Pathオブジェクトを使用
        self.subtitle_cache_dir.mkdir(exist_ok=True)  # ディレクトリ作成
        self._executor, workers = _get_shared_subtitle_executor()
        try:
            logger.info("SubtitlePNGRenderer workers=%d", workers)
        except Exception:
            pass

    async def render(
        self, text: str, style: Dict[str, Any]
    ) -> Tuple[Path, Dict[str, int]]:  # 戻り値の型ヒントをPathに変更
        """
        Renders a subtitle PNG image based on the given text and style.
        Returns the path to the generated image and its dimensions.

        Args:
            text (str): The subtitle text.
            style (Dict[str, Any]): The styling options.

        Returns:
            Tuple[Path, Dict[str, int]]: Path to the PNG file and a dict with "w" and "h".
        """
        # キャッシュキーデータにテキストとスタイルをすべて含める
        key_data = {
            "text": text,
            "style": style,
        }
        cache_key = self.cache_manager._generate_hash(key_data)
        expected_cached_path = self.cache_manager.get_cache_path(
            key_data=key_data,
            file_name="subtitle",
            extension="png",
        )
        expected_ephemeral_path = (
            (self.cache_manager.ephemeral_dir or self.cache_manager.cache_dir)
            / f"temp_subtitle_{cache_key}.png"
        )
        was_cached = (
            expected_ephemeral_path.exists()
            if self.cache_manager.no_cache
            else expected_cached_path.exists()
        )
        render_started = time.perf_counter()
        text_hash = hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()[:12]

        async def creator_func(output_path: Path) -> Path:
            logger.info(
                f"SubtitleEngine=image (cache miss), generating to {output_path.name}"
            )
            # オフロードしてPNGを生成
            loop = None
            try:
                import asyncio

                loop = asyncio.get_running_loop()
            except Exception:
                pass

            create_started = time.perf_counter()
            if loop:
                width, height = await loop.run_in_executor(
                    self._executor, _render_subtitle_png, text, style, str(output_path)
                )
            else:
                width, height = _render_subtitle_png(text, style, str(output_path))
            _write_subtitle_dimensions_meta(output_path, width, height)
            try:
                bbox = _inspect_subtitle_png_bbox(output_path)
                logger.info(
                    "[SubtitlePNG] text_hash=%s size=%sx%s bbox=%s margin_ltrb=%s,%s,%s,%s full_canvas=%s render_ms=%.1f cache=miss",
                    text_hash,
                    bbox["width"],
                    bbox["height"],
                    bbox["bbox_mode"],
                    bbox["transparent_left"],
                    bbox["transparent_top"],
                    bbox["transparent_right"],
                    bbox["transparent_bottom"],
                    bbox["full_canvas"],
                    (time.perf_counter() - create_started) * 1000.0,
                )
            except Exception:
                logger.debug("Failed to inspect subtitle PNG bbox: %s", output_path, exc_info=True)
            logger.info(f"Saved subtitle PNG to {output_path}")
            return output_path

        # CacheManagerのget_or_createを使用
        png_path = await self.cache_manager.get_or_create(
            key_data=key_data,
            file_name="subtitle",
            extension="png",
            creator_func=creator_func,
        )

        dims = _read_subtitle_dimensions_meta(png_path)
        if dims is not None:
            if was_cached:
                try:
                    bbox = _inspect_subtitle_png_bbox(png_path)
                    logger.info(
                        "[SubtitlePNG] text_hash=%s size=%sx%s bbox=%s margin_ltrb=%s,%s,%s,%s full_canvas=%s render_ms=%.1f cache=hit",
                        text_hash,
                        bbox["width"],
                        bbox["height"],
                        bbox["bbox_mode"],
                        bbox["transparent_left"],
                        bbox["transparent_top"],
                        bbox["transparent_right"],
                        bbox["transparent_bottom"],
                        bbox["full_canvas"],
                        (time.perf_counter() - render_started) * 1000.0,
                    )
                except Exception:
                    logger.debug("Failed to inspect cached subtitle PNG bbox: %s", png_path, exc_info=True)
            return png_path, dims

        with Image.open(png_path) as img:
            width, height = img.width, img.height
        _write_subtitle_dimensions_meta(png_path, width, height)
        return png_path, {"w": width, "h": height}

    def _wrap_text_by_pixel(
        self, text: str, font: ImageFont.FreeTypeFont, max_width: int
    ) -> str:
        """Wraps text to fit within a specified pixel width."""
        lines = []

        # First, split by existing newlines
        paragraphs = text.replace("\\n", "\n").split("\n")

        for paragraph in paragraphs:
            if not paragraph:
                lines.append("")
                continue

            words = paragraph.split(" ")
            current_line = ""
            for word in words:
                try:
                    bbox = font.getbbox(current_line + " " + word)
                    line_width = bbox[2] - bbox[0]
                except AttributeError:
                    line_width, _ = font.getsize(current_line + " " + word)

                if line_width <= max_width:
                    current_line += " " + word
                else:
                    lines.append(current_line.strip())
                    current_line = word
            lines.append(current_line.strip())

        return "\n".join(lines)

    def _wrap_text_by_chars(self, text: str, max_chars: int) -> str:
        """
        Wrap text by a fixed number of characters per line.
        """
        if not max_chars or max_chars <= 0:
            return text
        lines = []
        for paragraph in text.replace("\\n", "\n").split("\n"):
            if not paragraph:
                lines.append("")
                continue
            cur = paragraph
            while len(cur) > max_chars:
                lines.append(cur[:max_chars])
                cur = cur[max_chars:]
            lines.append(cur)
        return "\n".join(lines)

        # static counterparts for use inside ProcessPoolExecutor
    @staticmethod
    def _wrap_text_by_pixel_static(
        text: str, font: ImageFont.FreeTypeFont, max_width: int
    ) -> str:
        lines = []
        paragraphs = text.replace("\\n", "\n").split("\n")
        for paragraph in paragraphs:
            if not paragraph:
                lines.append("")
                continue
            words = paragraph.split(" ")
            current_line = ""
            for word in words:
                try:
                    bbox = font.getbbox(current_line + " " + word)
                    line_width = bbox[2] - bbox[0]
                except AttributeError:
                    line_width, _ = font.getsize(current_line + " " + word)
                if line_width <= max_width:
                    current_line += " " + word
                else:
                    lines.append(current_line.strip())
                    current_line = word
            lines.append(current_line.strip())
        return "\n".join(lines)

    @staticmethod
    def _wrap_text_by_chars_static(text: str, max_chars: int) -> str:
        if not max_chars or max_chars <= 0:
            return text
        lines = []
        for paragraph in text.replace("\\n", "\n").split("\n"):
            if not paragraph:
                lines.append("")
                continue
            cur = paragraph
            while len(cur) > max_chars:
                lines.append(cur[:max_chars])
                cur = cur[max_chars:]
            lines.append(cur)
        return "\n".join(lines)


# NOTE:
# For ProcessPoolExecutor, the target function must be picklable.
# Define the heavy rendering function at module scope to avoid
# "Can't get local object ..." pickling errors.
def _render_subtitle_png(
    text_: str, style_: Dict[str, Any], out_path_str: str
) -> Tuple[int, int]:
    font_path = style_.get("font_path", "assets/fonts/NotoSansJP-Regular.otf")
    font_size = style_.get("font_size", 64)
    font_color = style_.get("font_color", "white")
    max_width = style_.get("max_pixel_width", 1800)
    try:
        max_width_i = max(1, int(max_width))
    except (TypeError, ValueError):
        max_width_i = 1800
    try:
        stroke_width = int(style_.get("stroke_width", 0) or 0)
    except (TypeError, ValueError):
        stroke_width = 0
    stroke_color = style_.get("stroke_color", "black")

    try:
        base_padding = int(style_.get("box_padding", 10))
    except (TypeError, ValueError):
        base_padding = 10
    background_cfg = _extract_background_config(style_)
    default_box_color = style_.get("box_color", "black@0.5")
    if "color" not in background_cfg and default_box_color:
        background_cfg["color"] = default_box_color
    background_visible = _background_is_visible(background_cfg)
    padding_value = background_cfg.get("padding", base_padding) if background_visible else 0
    pad_left, pad_top, pad_right, pad_bottom = _normalize_padding(padding_value, base_padding)

    try:
        line_spacing_extra = int(style_.get("line_spacing_offset_per_line", 0) or 0)
    except (TypeError, ValueError):
        line_spacing_extra = 0
    if line_spacing_extra < 0:
        line_spacing_extra = 0
    try:
        line_spacing_multiplier = float(style_.get("line_spacing_multiplier", 1.0) or 1.0)
    except (TypeError, ValueError):
        line_spacing_multiplier = 1.0
    if line_spacing_multiplier < 1.0:
        line_spacing_multiplier = 1.0

    align_raw = str(
        style_.get("text_align", style_.get("align", "center")) or "center"
    ).strip().lower()
    if align_raw not in {"left", "center", "right"}:
        align_raw = "center"

    font = _load_font_with_fallback(font_path, font_size)

    wrap_mode = (style_.get("wrap_mode") or "").strip().lower()
    max_chars = style_.get("max_chars_per_line")
    auto_char_wrap = isinstance(max_chars, str) and max_chars.strip().lower() == "auto"

    if wrap_mode == "chars" or (max_chars is not None and wrap_mode != "pixel"):
        if auto_char_wrap:
            max_chars_i = _estimate_auto_max_chars(text_, font, max_width_i)
            wrapped_text = SubtitlePNGRenderer._wrap_text_by_chars_static(text_, max_chars_i)
            while max_chars_i > 4 and not _fits_within_width(
                wrapped_text, font, max_width_i
            ):
                max_chars_i -= 1
                wrapped_text = SubtitlePNGRenderer._wrap_text_by_chars_static(
                    text_, max_chars_i
                )
        else:
            try:
                max_chars_i = int(max_chars) if max_chars is not None else 0
            except (TypeError, ValueError):
                max_chars_i = 0
            wrapped_text = SubtitlePNGRenderer._wrap_text_by_chars_static(text_, max_chars_i)
    else:
        wrapped_text = SubtitlePNGRenderer._wrap_text_by_pixel_static(text_, font, max_width_i)
    lines = wrapped_text.split("\n")

    text_w = 0
    text_h = 0
    line_heights: list[int] = []
    line_bboxes: list[tuple[int, int, int, int]] = []
    for line in lines:
        bbox: tuple[int, int, int, int] | None = None
        bbox_includes_stroke = False
        if hasattr(font, "getbbox"):
            try:
                bbox = font.getbbox(line, stroke_width=stroke_width)
                bbox_includes_stroke = True
            except TypeError:
                bbox = font.getbbox(line)
            except Exception:
                bbox = None
        if bbox is None:
            width, height = font.getsize(line)
            bbox = (0, 0, width, height)
        if stroke_width and not bbox_includes_stroke:
            x0, y0, x1, y1 = bbox
            bbox = (
                int(x0 - stroke_width),
                int(y0 - stroke_width),
                int(x1 + stroke_width),
                int(y1 + stroke_width),
            )
        x0, y0, x1, y1 = bbox
        line_w = x1 - x0
        line_h = y1 - y0
        text_w = max(text_w, line_w)
        text_h += line_h
        line_heights.append(line_h)
        line_bboxes.append(bbox)

    spacing_offsets: list[int] = []
    if len(lines) > 1:
        spacing_ratio = line_spacing_multiplier - 1.0
        for idx in range(len(lines) - 1):
            extra = line_spacing_extra
            if spacing_ratio > 0.0:
                multiplier_gap = int(round(line_heights[idx] * spacing_ratio))
                if multiplier_gap > 0:
                    extra += multiplier_gap
            spacing_offsets.append(max(0, extra))
        if spacing_offsets:
            text_h += sum(spacing_offsets)

    img_w = max(1, int(text_w + pad_left + pad_right))
    img_h = max(1, int(text_h + pad_top + pad_bottom))
    img = Image.new("RGBA", (img_w, img_h), (0, 0, 0, 0))

    background_layer = _build_background_layer_cached((img_w, img_h), background_cfg)
    if background_layer is not None:
        img = Image.alpha_composite(img, background_layer)

    draw = ImageDraw.Draw(img)

    current_y = float(pad_top)
    for i, line in enumerate(lines):
        bbox = line_bboxes[i]
        x0, y0, x1, _ = bbox
        line_w = x1 - x0
        if align_raw == "left":
            baseline_x = float(pad_left - x0)
        elif align_raw == "right":
            baseline_x = pad_left + max(0.0, text_w - line_w) - x0
        else:
            if text_w > 0:
                baseline_x = pad_left + (text_w - line_w) / 2 - x0
            else:
                baseline_x = float(pad_left - x0)
        baseline_y = current_y - y0
        draw.text(
            (baseline_x, baseline_y),
            line,
            font=font,
            fill=font_color,
            stroke_width=stroke_width,
            stroke_fill=stroke_color,
        )
        current_y += line_heights[i]
        if i < len(lines) - 1 and spacing_offsets:
            current_y += spacing_offsets[i]

    save_kwargs: Dict[str, Any] = {}
    try:
        compress_level = style_.get("png_compress_level", style_.get("compress_level"))
        if compress_level is not None:
            save_kwargs["compress_level"] = max(0, min(9, int(compress_level)))
    except (TypeError, ValueError):
        pass
    if "png_optimize" in style_:
        save_kwargs["optimize"] = bool(style_.get("png_optimize"))
    elif "optimize" in style_:
        save_kwargs["optimize"] = bool(style_.get("optimize"))

    img.save(out_path_str, **save_kwargs)
    return img_w, img_h


def _resolve_subtitle_png_workers() -> int:
    try:
        env_workers = os.getenv("SUB_PNG_WORKERS")
        if env_workers and env_workers.isdigit():
            return max(1, int(env_workers))
        return max(1, (os.cpu_count() or 2) // 2)
    except Exception:
        return 1


def _shutdown_subtitle_executor() -> None:
    global _SUBTITLE_EXECUTOR, _SUBTITLE_EXECUTOR_WORKERS
    if _SUBTITLE_EXECUTOR is None:
        return
    try:
        _SUBTITLE_EXECUTOR.shutdown(wait=False, cancel_futures=True)
    except Exception:
        pass
    _SUBTITLE_EXECUTOR = None
    _SUBTITLE_EXECUTOR_WORKERS = None


def _get_shared_subtitle_executor() -> tuple[ProcessPoolExecutor, int]:
    global _SUBTITLE_EXECUTOR, _SUBTITLE_EXECUTOR_WORKERS
    workers = _resolve_subtitle_png_workers()
    if _SUBTITLE_EXECUTOR is None or _SUBTITLE_EXECUTOR_WORKERS != workers:
        if _SUBTITLE_EXECUTOR is not None:
            _shutdown_subtitle_executor()
        _SUBTITLE_EXECUTOR = ProcessPoolExecutor(max_workers=workers)
        _SUBTITLE_EXECUTOR_WORKERS = workers
        atexit.register(_shutdown_subtitle_executor)
    return _SUBTITLE_EXECUTOR, workers


def _load_font_with_fallback(font_path: str, font_size: int) -> ImageFont.FreeTypeFont:
    """Load a TrueType/OpenType font with sensible fallbacks.

    Tries the given path first; if it fails, attempts common system fonts
    (DejaVu/Noto/Arial). Falls back to PIL's default bitmap font.
    """
    # Return cached instance when possible
    try:
        key = (font_path or "", int(font_size))
        if key in _FONT_CACHE:
            return _FONT_CACHE[key]
    except Exception:
        pass
    try:
        if font_path and os.path.exists(font_path):
            font = ImageFont.truetype(font_path, font_size)
            _FONT_CACHE[key] = font
            return font
        # Try even if path doesn't exist; Pillow may resolve by name
        if font_path:
            font = ImageFont.truetype(font_path, font_size)
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
    for p in candidates:
        try:
            if os.path.exists(p):
                try:
                    font = ImageFont.truetype(p, font_size)
                    _FONT_CACHE[key] = font
                    return font
                except Exception:
                    continue
        except Exception:
            continue
    # Final fallback
    try:
        f = ImageFont.load_default()
        try:
            _FONT_CACHE[key] = f
        except Exception:
            pass
        return f
    except Exception:
        # As a last resort, attempt DejaVu by name
        return ImageFont.truetype("DejaVuSans.ttf", font_size)
