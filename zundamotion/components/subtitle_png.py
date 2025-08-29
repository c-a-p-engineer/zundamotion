import json
import logging
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path  # Pathをインポート
from typing import Any, Dict, Tuple

from PIL import Image, ImageDraw, ImageFont

from zundamotion.cache import CacheManager

logger = logging.getLogger(__name__)


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

            workers = max(1, (os.cpu_count() or 2) // 2)
        except Exception:
            workers = 1
        self._executor = ProcessPoolExecutor(max_workers=workers)

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

        img = Image.open(png_path)
        return png_path, {"w": img.width, "h": img.height}

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
    box_color = style_.get("box_color", "black@0.5")
    padding = style_.get("box_padding", 10)
    max_width = style_.get("max_pixel_width", 1800)
    stroke_width = style_.get("stroke_width", 0)
    stroke_color = style_.get("stroke_color", "black")

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
    line_heights = []
    for line in lines:
        try:
            bbox = font.getbbox(line)
            line_w = bbox[2] - bbox[0]
            line_h = bbox[3] - bbox[1]
        except AttributeError:
            line_w, line_h = font.getsize(line)
        text_w = max(text_w, line_w)
        text_h += line_h
        line_heights.append(line_h)

    img_w = text_w + padding * 2
    img_h = text_h + padding * 2
    img = Image.new("RGBA", (img_w, img_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    if box_color:
        from PIL import ImageColor

        color, alpha_str = (
            box_color.split("@") if "@" in box_color else (box_color, "1.0")
        )
        alpha = int(float(alpha_str) * 255)
        try:
            rgb = ImageColor.getrgb(color)
            draw.rectangle([(0, 0), (img_w, img_h)], fill=rgb + (alpha,))
        except ValueError:
            draw.rectangle([(0, 0), (img_w, img_h)], fill=(0, 0, 0, alpha))

    current_y = padding
    for i, line in enumerate(lines):
        try:
            bbox = font.getbbox(line)
            line_w = bbox[2] - bbox[0]
        except AttributeError:
            line_w, _ = font.getsize(line)
        x_pos = (img_w - line_w) / 2
        draw.text(
            (x_pos, current_y),
            line,
            font=font,
            fill=font_color,
            stroke_width=stroke_width,
            stroke_fill=stroke_color,
        )
        current_y += line_heights[i]

    img.save(out_path_str)
    return img_w, img_h


def _load_font_with_fallback(font_path: str, font_size: int) -> ImageFont.FreeTypeFont:
    """Load a TrueType/OpenType font with sensible fallbacks.

    Tries the given path first; if it fails, attempts common system fonts
    (DejaVu/Noto/Arial). Falls back to PIL's default bitmap font.
    """
    try:
        if font_path and os.path.exists(font_path):
            return ImageFont.truetype(font_path, font_size)
        # Try even if path doesn't exist; Pillow may resolve by name
        if font_path:
            return ImageFont.truetype(font_path, font_size)
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
                return ImageFont.truetype(p, font_size)
        except Exception:
            continue
    # Final fallback
    try:
        return ImageFont.load_default()
    except Exception:
        # As a last resort, attempt DejaVu by name
        return ImageFont.truetype("DejaVuSans.ttf", font_size)
