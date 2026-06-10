"""Reusable Pillow-based HSV filtering for RGBA images.

Supports whole-image adjustment and target-based partial recoloring.
"""

import math
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from PIL import Image

from ...cache import CacheManager

RGBA_PIXEL = Tuple[int, int, int, int]


class ImageColorFilterCache:
    """Cache hue, saturation, and brightness filtered PNG variants."""

    def __init__(self, cache_manager: CacheManager) -> None:
        self.cache_manager = cache_manager

    async def filter_image(self, source_path: Path, color_filter: Any) -> Path:
        """Return a cached filtered variant of an arbitrary RGBA-compatible image."""
        normalized = self._normalize_color_filter(color_filter)
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
        color_filter: Dict[str, Any],
    ) -> None:
        with Image.open(source_path) as source:
            rgba = source.convert("RGBA")
            if ImageColorFilterCache._is_identity_filter(color_filter):
                rgba.save(output_path, format="PNG")
                return
            filtered = ImageColorFilterCache._apply_color_filter(rgba, color_filter)
            filtered.save(output_path, format="PNG")

    @staticmethod
    def _normalize_color_filter(color_filter: Any) -> Dict[str, Any]:
        normalized: Dict[str, Any] = {
            "hue": float(color_filter.get("hue", 0.0)),
            "saturation": float(color_filter.get("saturation", 1.0)),
            "brightness": float(color_filter.get("brightness", 1.0)),
        }
        targets = color_filter.get("targets") or []
        normalized["targets"] = [
            ImageColorFilterCache._normalize_target(target) for target in targets
        ]
        return normalized

    @staticmethod
    def _normalize_target(target: Dict[str, Any]) -> Dict[str, Any]:
        region = dict(target["region"])
        select_cfg = dict(target["select"]["color"])
        adjust = {
            "hue": float(target["adjust"].get("hue", 0.0)),
            "saturation": float(target["adjust"].get("saturation", 1.0)),
            "brightness": float(target["adjust"].get("brightness", 1.0)),
        }
        normalized_target: Dict[str, Any] = {
            "name": target.get("name"),
            "region": region,
            "select": {"color": select_cfg},
            "adjust": adjust,
        }
        if "ratio" in region:
            region["ratio"] = float(region["ratio"])
        for key in ("x", "y", "width", "height"):
            if key in region:
                region[key] = float(region[key])
        select_cfg["mode"] = str(select_cfg["mode"])
        if select_cfg["mode"] == "luma":
            select_cfg["min"] = float(select_cfg["min"])
            select_cfg["max"] = float(select_cfg["max"])
        elif select_cfg["mode"] == "rgb_distance":
            select_cfg["color"] = str(select_cfg["color"])
            select_cfg["tolerance"] = float(select_cfg["tolerance"])
        return normalized_target

    @staticmethod
    def _is_identity_filter(color_filter: Dict[str, Any]) -> bool:
        has_global = (
            color_filter["hue"] != 0.0
            or color_filter["saturation"] != 1.0
            or color_filter["brightness"] != 1.0
        )
        return not has_global and not color_filter["targets"]

    @staticmethod
    def _apply_color_filter(rgba: Image.Image, color_filter: Dict[str, Any]) -> Image.Image:
        pixels = list(rgba.getdata())
        alpha_mask = [pixel[3] > 0 for pixel in pixels]
        working = list(pixels)

        global_adjust = {
            "hue": color_filter["hue"],
            "saturation": color_filter["saturation"],
            "brightness": color_filter["brightness"],
        }
        if global_adjust != {"hue": 0.0, "saturation": 1.0, "brightness": 1.0}:
            working = ImageColorFilterCache._adjust_pixels(
                working,
                alpha_mask,
                global_adjust,
            )

        for target in color_filter["targets"]:
            region_mask = ImageColorFilterCache._build_region_mask(
                width=rgba.width,
                height=rgba.height,
                region=target["region"],
            )
            color_mask = ImageColorFilterCache._build_color_mask(
                pixels=working,
                color_select=target["select"]["color"],
            )
            final_mask = [
                alpha and region and color
                for alpha, region, color in zip(alpha_mask, region_mask, color_mask)
            ]
            working = ImageColorFilterCache._adjust_pixels(
                working,
                final_mask,
                target["adjust"],
            )

        filtered = Image.new("RGBA", rgba.size)
        filtered.putdata(working)
        return filtered

    @staticmethod
    def _adjust_pixels(
        pixels: List[RGBA_PIXEL],
        mask: Iterable[bool],
        adjust: Dict[str, float],
    ) -> List[RGBA_PIXEL]:
        mask_values = list(mask)
        if not any(mask_values):
            return pixels

        hsv_image = Image.new("RGB", (len(pixels), 1))
        hsv_image.putdata([pixel[:3] for pixel in pixels])
        hue_band, saturation_band, value_band = hsv_image.convert("HSV").split()
        hue_values = list(hue_band.getdata())
        saturation_values = list(saturation_band.getdata())
        value_values = list(value_band.getdata())

        hue_offset = int(round(adjust["hue"] * 255.0 / 360.0)) % 256
        saturation_scale = adjust["saturation"]
        brightness_scale = adjust["brightness"]

        for index, pixel in enumerate(pixels):
            if not mask_values[index]:
                continue
            original_saturation = saturation_values[index]
            original_value = value_values[index]
            hue_values[index] = (hue_values[index] + hue_offset) % 256
            saturation_values[index] = ImageColorFilterCache._adjust_saturation(
                original_saturation,
                original_value,
                saturation_scale,
                brightness_scale,
            )
            value_values[index] = ImageColorFilterCache._adjust_value(
                original_value,
                brightness_scale,
            )

        hsv_result = Image.new("HSV", (len(hue_values), 1))
        hsv_result.putdata(list(zip(hue_values, saturation_values, value_values)))
        rgb_values = list(hsv_result.convert("RGB").getdata())
        return [
            (rgb[0], rgb[1], rgb[2], pixel[3])
            for rgb, pixel in zip(rgb_values, pixels)
        ]

    @staticmethod
    def _build_region_mask(width: int, height: int, region: Dict[str, Any]) -> List[bool]:
        region_type = region["type"]
        if region_type == "top":
            cutoff = math.ceil(height * float(region["ratio"]))
            return [(index // width) < cutoff for index in range(width * height)]
        if region_type == "bottom":
            start_row = height - math.ceil(height * float(region["ratio"]))
            return [(index // width) >= start_row for index in range(width * height)]

        x0 = int(width * float(region["x"]))
        y0 = int(height * float(region["y"]))
        x1 = math.ceil(width * (float(region["x"]) + float(region["width"])))
        y1 = math.ceil(height * (float(region["y"]) + float(region["height"])))
        mask: List[bool] = []
        for index in range(width * height):
            x = index % width
            y = index // width
            mask.append(x0 <= x < x1 and y0 <= y < y1)
        return mask

    @staticmethod
    def _build_color_mask(
        pixels: List[RGBA_PIXEL],
        color_select: Dict[str, Any],
    ) -> List[bool]:
        mode = color_select["mode"]
        if mode == "luma":
            min_luma = float(color_select["min"])
            max_luma = float(color_select["max"])
            return [
                min_luma <= ImageColorFilterCache._compute_luma(pixel) <= max_luma
                for pixel in pixels
            ]

        target_rgb = ImageColorFilterCache._parse_hex_rgb(str(color_select["color"]))
        tolerance_sq = float(color_select["tolerance"]) ** 2
        return [
            ImageColorFilterCache._rgb_distance_sq(pixel[:3], target_rgb) <= tolerance_sq
            for pixel in pixels
        ]

    @staticmethod
    def _compute_luma(pixel: RGBA_PIXEL) -> float:
        red, green, blue, _alpha = pixel
        return 0.299 * red + 0.587 * green + 0.114 * blue

    @staticmethod
    def _adjust_saturation(
        original_saturation: int,
        original_value: int,
        saturation_scale: float,
        brightness_scale: float,
    ) -> int:
        scaled = round(original_saturation * saturation_scale)
        if saturation_scale <= 1.0 and brightness_scale <= 1.0:
            return min(255, scaled)

        darkness_ratio = 1.0 - (original_value / 255.0)
        floor = 0.0
        if saturation_scale > 1.0:
            floor += 120.0 * (saturation_scale - 1.0) * darkness_ratio
        if brightness_scale > 1.0:
            floor += 64.0 * (brightness_scale - 1.0) * darkness_ratio
        return min(255, round(max(scaled, floor)))

    @staticmethod
    def _adjust_value(original_value: int, brightness_scale: float) -> int:
        scaled = original_value * brightness_scale
        if brightness_scale <= 1.0:
            return min(255, round(scaled))

        darkness_ratio = 1.0 - (original_value / 255.0)
        lift = 72.0 * (brightness_scale - 1.0) * darkness_ratio
        return min(255, round(scaled + lift))

    @staticmethod
    def _parse_hex_rgb(value: str) -> Tuple[int, int, int]:
        text = value.lstrip("#")
        if len(text) == 3:
            text = "".join(ch * 2 for ch in text)
        if len(text) == 8:
            text = text[:6]
        return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))

    @staticmethod
    def _rgb_distance_sq(left: Tuple[int, int, int], right: Tuple[int, int, int]) -> float:
        return float(
            (left[0] - right[0]) ** 2
            + (left[1] - right[1]) ** 2
            + (left[2] - right[2]) ** 2
        )
