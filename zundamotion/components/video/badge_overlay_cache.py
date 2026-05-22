from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

from PIL import Image, ImageDraw

from zundamotion.cache import CacheManager

from ..subtitles.png import (
    SubtitlePNGRenderer,
    _background_is_visible,
    _build_background_layer_cached,
    _extract_background_config,
    _load_font_with_fallback,
    _normalize_padding,
)


BADGE_POSITION_CHOICES = {
    "top-left",
    "top-center",
    "top-right",
    "bottom-left",
    "bottom-center",
    "bottom-right",
}


class BadgeOverlayCache:
    """Render cached PNG badges and convert them into fg_overlay entries."""

    MARGIN_X = 48
    MARGIN_Y = 36
    DEFAULT_FONT_SIZE = 40
    DEFAULT_TEXT_COLOR = "#FFFFFF"
    DEFAULT_STROKE_COLOR = "#202020"
    DEFAULT_STROKE_WIDTH = 0
    DEFAULT_BACKGROUND = {
        "show": True,
        "color": "#D97706",
        "opacity": 1.0,
        "radius": 24,
        "border_color": "#7C2D12",
        "border_width": 3,
        "border_opacity": 1.0,
        "padding": {"left": 18, "right": 18, "top": 12, "bottom": 12},
    }
    DEFAULT_MAX_WIDTH = 720
    CACHE_VERSION = "20260522_badge_v3"

    def __init__(self, cache_manager: CacheManager):
        self.cache = cache_manager

    @classmethod
    def _normalize_text(cls, value: Any) -> str:
        return " ".join(str(value or "").replace("\n", " ").split()).strip()

    @classmethod
    def _resolve_style(
        cls,
        badge_config: Dict[str, Any],
        *,
        font_path: str,
        video_width: int,
    ) -> Dict[str, Any]:
        background_cfg = dict(cls.DEFAULT_BACKGROUND)
        user_background = badge_config.get("background")
        if isinstance(user_background, dict):
            background_cfg.update(user_background)

        try:
            font_size = int(float(badge_config.get("font_size", cls.DEFAULT_FONT_SIZE)))
        except Exception:
            font_size = cls.DEFAULT_FONT_SIZE
        font_size = max(1, font_size)

        try:
            stroke_width = int(float(badge_config.get("stroke_width", cls.DEFAULT_STROKE_WIDTH)))
        except Exception:
            stroke_width = cls.DEFAULT_STROKE_WIDTH
        stroke_width = max(0, stroke_width)

        available_width = max(1, int(video_width) - (cls.MARGIN_X * 2))
        try:
            max_width = int(float(badge_config.get("max_width", min(cls.DEFAULT_MAX_WIDTH, available_width))))
        except Exception:
            max_width = min(cls.DEFAULT_MAX_WIDTH, available_width)
        max_width = max(1, min(max_width, available_width))

        try:
            min_width = int(float(badge_config.get("min_width", 0)))
        except Exception:
            min_width = 0
        min_width = max(0, min(min_width, max_width))

        return {
            "font_path": font_path,
            "font_size": font_size,
            "font_color": str(badge_config.get("font_color", cls.DEFAULT_TEXT_COLOR)),
            "stroke_color": str(
                badge_config.get("stroke_color", cls.DEFAULT_STROKE_COLOR)
            ),
            "stroke_width": stroke_width,
            "text_align": str(badge_config.get("text_align", "center")),
            "max_pixel_width": max_width,
            "min_width": min_width,
            "background": background_cfg,
        }

    @classmethod
    def _measure_multiline_text(
        cls,
        text: str,
        *,
        font_path: str,
        font_size: int,
        stroke_width: int,
        max_width: int,
    ) -> Tuple[str, Any, list[tuple[int, int, int, int]], int, int]:
        font = _load_font_with_fallback(font_path, font_size)
        wrapped = SubtitlePNGRenderer._wrap_text_by_pixel_static(
            text,
            font,
            max(1, max_width),
        )
        line_bboxes: list[tuple[int, int, int, int]] = []
        text_width = 0
        text_height = 0
        for line in wrapped.split("\n"):
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
            line_bboxes.append(bbox)
            text_width = max(text_width, bbox[2] - bbox[0])
            text_height += bbox[3] - bbox[1]
        return wrapped, font, line_bboxes, text_width, text_height

    @classmethod
    def _render_badge_png(
        cls,
        *,
        text: str,
        style: Dict[str, Any],
        out_path: Path,
    ) -> Path:
        font_path = str(style.get("font_path", "") or "")
        font_size = int(style.get("font_size", cls.DEFAULT_FONT_SIZE) or cls.DEFAULT_FONT_SIZE)
        stroke_width = int(style.get("stroke_width", cls.DEFAULT_STROKE_WIDTH) or 0)
        background_cfg = _extract_background_config(style)
        background_visible = _background_is_visible(background_cfg)
        base_padding = 0
        padding_value = background_cfg.get("padding", base_padding) if background_visible else 0
        pad_left, pad_top, pad_right, pad_bottom = _normalize_padding(
            padding_value,
            base_padding,
        )

        try:
            max_width = int(style.get("max_pixel_width", cls.DEFAULT_MAX_WIDTH))
        except Exception:
            max_width = cls.DEFAULT_MAX_WIDTH
        max_text_width = max(1, max_width - pad_left - pad_right)

        wrapped, font, line_bboxes, text_width, text_height = cls._measure_multiline_text(
            text,
            font_path=font_path,
            font_size=font_size,
            stroke_width=stroke_width,
            max_width=max_text_width,
        )
        try:
            min_width = int(style.get("min_width", 0) or 0)
        except Exception:
            min_width = 0

        img_w = max(1, min_width, int(text_width + pad_left + pad_right))
        img_h = max(1, int(text_height + pad_top + pad_bottom))
        img = Image.new("RGBA", (img_w, img_h), (0, 0, 0, 0))

        background_layer = _build_background_layer_cached((img_w, img_h), background_cfg)
        if background_layer is not None:
            img = Image.alpha_composite(img, background_layer)

        draw = ImageDraw.Draw(img)
        align_raw = str(style.get("text_align", "center") or "center").strip().lower()
        if align_raw not in {"left", "center", "right"}:
            align_raw = "center"

        current_y = float(pad_top)
        for line, bbox in zip(wrapped.split("\n"), line_bboxes):
            x0, y0, x1, y1 = bbox
            line_w = x1 - x0
            line_h = y1 - y0
            if align_raw == "left":
                baseline_x = float(pad_left - x0)
            elif align_raw == "right":
                baseline_x = img_w - pad_right - line_w - x0
            else:
                baseline_x = (img_w - line_w) / 2 - x0
            baseline_y = current_y - y0
            draw.text(
                (baseline_x, baseline_y),
                line,
                font=font,
                fill=style.get("font_color", cls.DEFAULT_TEXT_COLOR),
                stroke_width=stroke_width,
                stroke_fill=style.get("stroke_color", cls.DEFAULT_STROKE_COLOR),
            )
            current_y += line_h

        img.save(out_path, format="PNG")
        return out_path

    @classmethod
    def _resolve_position(
        cls,
        position: str,
        *,
        video_width: int,
        video_height: int,
        overlay_width: int,
        overlay_height: int,
    ) -> Dict[str, int]:
        x = cls.MARGIN_X
        y = cls.MARGIN_Y

        if position.endswith("right"):
            x = max(0, int(video_width) - int(overlay_width) - cls.MARGIN_X)
        elif position.endswith("center"):
            x = max(0, int(round((int(video_width) - int(overlay_width)) / 2)))

        if position.startswith("bottom"):
            y = max(0, int(video_height) - int(overlay_height) - cls.MARGIN_Y)

        return {"x": x, "y": y}

    @staticmethod
    def _lookup_line_time(
        ref: Any,
        line_markers: Optional[Mapping[str, float]],
    ) -> Optional[float]:
        if line_markers is None or ref is None:
            return None
        if isinstance(ref, int):
            return line_markers.get(str(ref))
        if isinstance(ref, str):
            return line_markers.get(ref) or line_markers.get(ref.strip())
        return None

    def _resolve_timing(
        self,
        badge_config: Dict[str, Any],
        *,
        line_markers: Optional[Mapping[str, float]] = None,
    ) -> Dict[str, Any]:
        timing_cfg = badge_config.get("timing") or {}
        if not isinstance(timing_cfg, dict):
            timing_cfg = {}

        start = timing_cfg.get("start")
        if start is None:
            start = self._lookup_line_time(timing_cfg.get("show_on_line"), line_markers)
        try:
            start_value = max(0.0, float(start or 0.0))
        except Exception:
            start_value = 0.0

        end = timing_cfg.get("end")
        if end is None:
            end = self._lookup_line_time(timing_cfg.get("hide_on_line"), line_markers)
        end_value: Optional[float]
        if end is None:
            end_value = None
        else:
            end_value = float(end)

        duration = None
        if end_value is not None:
            duration = max(0.0, end_value - start_value)

        return {
            "start": start_value,
            "duration": duration,
        }

    async def get_badge_overlay(
        self,
        badge_config: Dict[str, Any],
        *,
        video_width: int,
        video_height: int,
        font_path: Optional[str] = None,
        line_markers: Optional[Mapping[str, float]] = None,
    ) -> Dict[str, Any]:
        text = self._normalize_text(badge_config.get("text"))
        position = str(badge_config.get("position") or "top-right").strip().lower()
        font_path_value = str(font_path or "")
        style = self._resolve_style(
            badge_config,
            font_path=font_path_value,
            video_width=video_width,
        )
        timing = self._resolve_timing(badge_config, line_markers=line_markers)
        key_data = {
            "op": "badge_overlay",
            "version": self.CACHE_VERSION,
            "text": text,
            "style": style,
        }

        async def _creator(out_path: Path) -> Path:
            return await asyncio.to_thread(
                self._render_badge_png,
                text=text,
                style=style,
                out_path=out_path,
            )

        png_path = await self.cache.get_or_create(
            key_data=key_data,
            file_name="badge_overlay",
            extension="png",
            creator_func=_creator,
        )
        with Image.open(png_path) as image:
            overlay_width, overlay_height = image.size
        position_xy = self._resolve_position(
            position,
            video_width=video_width,
            video_height=video_height,
            overlay_width=overlay_width,
            overlay_height=overlay_height,
        )
        return {
            "id": f"badge_{position}_{text}",
            "src": str(png_path),
            "mode": "overlay",
            "position": position_xy,
            "scale": 1.0,
            "opacity": 1.0,
            "timing": timing,
        }
