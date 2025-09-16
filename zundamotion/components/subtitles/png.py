import json
import logging
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path  # Pathをインポート
from typing import Any, Dict, Tuple

from PIL import Image, ImageColor, ImageDraw, ImageFont

from ...cache import CacheManager

logger = logging.getLogger(__name__)

# Module-level font cache to reduce load/latency jitter inside worker processes
_FONT_CACHE: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}

try:
    RESAMPLE_LANCZOS = Image.Resampling.LANCZOS  # type: ignore[attr-defined]
except AttributeError:  # pragma: no cover - Pillow<9 fallback
    RESAMPLE_LANCZOS = Image.LANCZOS


def _clamp_float(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, value))


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


def _build_background_layer(
    size: tuple[int, int], config: Dict[str, Any]
) -> Image.Image | None:
    width, height = size
    if width <= 0 or height <= 0:
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

    has_drawable = any(
        [fill_rgba, outline_rgba and border_width > 0, bool(image_path)]
    )
    if not has_drawable:
        return None

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
        # 画像生成はCPU負荷が高く、イベントループをブロックするため
        # プロセスプールで並列化してオフロードする
        # デフォルト: 物理コアの半分（最低1）
        try:
            import os
            env_workers = os.getenv("SUB_PNG_WORKERS")
            if env_workers and env_workers.isdigit():
                workers = max(1, int(env_workers))
            else:
                workers = max(1, (os.cpu_count() or 2) // 2)
        except Exception:
            workers = 1
        self._executor = ProcessPoolExecutor(max_workers=workers)
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

            if loop:
                await loop.run_in_executor(
                    self._executor, _render_subtitle_png, text, style, str(output_path)
                )
            else:
                _render_subtitle_png(text, style, str(output_path))
            logger.info(f"Saved subtitle PNG to {output_path}")
            return output_path

        # CacheManagerのget_or_createを使用
        png_path = await self.cache_manager.get_or_create(
            key_data=key_data,
            file_name="subtitle",
            extension="png",
            creator_func=creator_func,
        )

        with Image.open(png_path) as img:
            width, height = img.width, img.height
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
    padding_value = background_cfg.get("padding", base_padding)
    pad_left, pad_top, pad_right, pad_bottom = _normalize_padding(padding_value, base_padding)

    try:
        line_spacing_extra = int(style_.get("line_spacing_offset_per_line", 0) or 0)
    except (TypeError, ValueError):
        line_spacing_extra = 0
    if line_spacing_extra < 0:
        line_spacing_extra = 0

    font = _load_font_with_fallback(font_path, font_size)

    wrap_mode = (style_.get("wrap_mode") or "").strip().lower()
    max_chars = style_.get("max_chars_per_line")
    if wrap_mode == "chars" or (max_chars is not None and wrap_mode != "pixel"):
        try:
            max_chars_i = int(max_chars) if max_chars is not None else 0
        except (TypeError, ValueError):
            max_chars_i = 0
        wrapped_text = SubtitlePNGRenderer._wrap_text_by_chars_static(text_, max_chars_i)
    else:
        wrapped_text = SubtitlePNGRenderer._wrap_text_by_pixel_static(text_, font, max_width)
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

    if line_spacing_extra and len(lines) > 1:
        text_h += line_spacing_extra * (len(lines) - 1)

    img_w = max(1, int(text_w + pad_left + pad_right))
    img_h = max(1, int(text_h + pad_top + pad_bottom))
    img = Image.new("RGBA", (img_w, img_h), (0, 0, 0, 0))

    background_layer = _build_background_layer((img_w, img_h), background_cfg)
    if background_layer is not None:
        img = Image.alpha_composite(img, background_layer)

    draw = ImageDraw.Draw(img)

    current_y = float(pad_top)
    for i, line in enumerate(lines):
        bbox = line_bboxes[i]
        x0, y0, x1, _ = bbox
        line_w = x1 - x0
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
        if line_spacing_extra and i < len(lines) - 1:
            current_y += line_spacing_extra

    img.save(out_path_str)
    return img_w, img_h


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
