"""Reusable Pillow-based HSV filtering for RGBA images."""

from pathlib import Path
from typing import Any, Dict

from PIL import Image

from ...cache import CacheManager


class ImageColorFilterCache:
    """Cache hue, saturation, and brightness filtered PNG variants."""

    def __init__(self, cache_manager: CacheManager) -> None:
        self.cache_manager = cache_manager

    async def filter_image(self, source_path: Path, color_filter: Any) -> Path:
        """Return a cached filtered variant of an arbitrary RGBA-compatible image."""
        normalized = {
            "hue": float(color_filter.get("hue", 0.0)),
            "saturation": float(color_filter.get("saturation", 1.0)),
            "brightness": float(color_filter.get("brightness", 1.0)),
        }
        key_data = {
            "type": "image_color_filter",
            "image_path": source_path,
            "color_filter": normalized,
        }

        async def creator(output_path: Path) -> Path:
            self._render_filtered_png(source_path, output_path, normalized)
            return output_path

        return await self.cache_manager.get_or_create(
            key_data=key_data,
            file_name="image_color_filter",
            extension="png",
            creator_func=creator,
        )

    @staticmethod
    def _render_filtered_png(
        source_path: Path,
        output_path: Path,
        color_filter: Dict[str, float],
    ) -> None:
        with Image.open(source_path) as source:
            rgba = source.convert("RGBA")
            alpha = rgba.getchannel("A")
            hsv = rgba.convert("RGB").convert("HSV")
            hue, saturation, brightness = hsv.split()

            hue_offset = round(color_filter["hue"] * 255.0 / 360.0)
            hue = hue.point(lambda value: (value + hue_offset) % 256)
            saturation_scale = color_filter["saturation"]
            brightness_scale = color_filter["brightness"]
            saturation = saturation.point(
                lambda value: min(255, round(value * saturation_scale))
            )
            brightness = brightness.point(
                lambda value: min(255, round(value * brightness_scale))
            )

            rgb = Image.merge("HSV", (hue, saturation, brightness)).convert("RGB")
            filtered = rgb.convert("RGBA")
            filtered.putalpha(alpha)
            filtered.save(output_path, format="PNG")
