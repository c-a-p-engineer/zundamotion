import json
import logging
import os
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

            font_path = style.get("font_path", "assets/fonts/NotoSansJP-Regular.otf")
            font_size = style.get("font_size", 64)
            font_color = style.get("font_color", "white")
            box_color = style.get("box_color", "black@0.5")
            padding = style.get("box_padding", 10)
            max_width = style.get("max_pixel_width", 1800)  # Max width for wrapping
            stroke_width = style.get("stroke_width", 0)
            stroke_color = style.get("stroke_color", "black")

            font = ImageFont.truetype(font_path, font_size)

            # Wrap text: choose by style (pixel width or fixed chars)
            wrap_mode = (style.get("wrap_mode") or "").strip().lower()
            max_chars = style.get("max_chars_per_line")
            if wrap_mode == "chars" or (max_chars is not None and wrap_mode != "pixel"):
                try:
                    max_chars_i = int(max_chars) if max_chars is not None else 0
                except (TypeError, ValueError):
                    max_chars_i = 0
                wrapped_text = self._wrap_text_by_chars(text, max_chars_i)
            else:
                wrapped_text = self._wrap_text_by_pixel(text, font, max_width)
            lines = wrapped_text.split("\n")

            # Calculate text block size
            text_w = 0
            text_h = 0
            line_heights = []
            for line in lines:
                try:
                    # Use getbbox for more accurate size calculation
                    bbox = font.getbbox(line)
                    line_w = bbox[2] - bbox[0]
                    line_h = bbox[3] - bbox[1]
                except AttributeError:  # fallback for older Pillow
                    line_w, line_h = font.getsize(line)

                text_w = max(text_w, line_w)
                text_h += line_h
                line_heights.append(line_h)

            # Add padding for the box
            img_w = text_w + padding * 2
            img_h = text_h + padding * 2

            img = Image.new("RGBA", (img_w, img_h), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)

            # Draw background box
            if box_color:
                # Pillow doesn't support ffmpeg's "color@opacity" format directly
                # Simple parsing for now.
                color, alpha_str = (
                    box_color.split("@") if "@" in box_color else (box_color, "1.0")
                )
                alpha = int(float(alpha_str) * 255)

                # A bit of a hack to map color names to RGBA
                from PIL import ImageColor

                try:
                    rgb = ImageColor.getrgb(color)
                    draw.rectangle([(0, 0), (img_w, img_h)], fill=rgb + (alpha,))
                except ValueError:
                    logger.warning(f"Could not parse box_color '{color}'. Using black.")
                    draw.rectangle([(0, 0), (img_w, img_h)], fill=(0, 0, 0, alpha))

            # Draw text line by line
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

            img.save(output_path)
            logger.info(f"Saved subtitle PNG: size={img_w}x{img_h}, path={output_path}")
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
