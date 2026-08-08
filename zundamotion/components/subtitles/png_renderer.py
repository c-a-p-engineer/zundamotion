"""Cache-aware orchestration for subtitle PNG generation."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from pathlib import Path
from typing import Any, Dict, Tuple

from PIL import Image, ImageFont

from ...cache import CacheManager
from ...utils import perf_stats
from ...utils.subtitle_text import wrap_subtitle_text_by_display_width
from .png_draw import _render_subtitle_png
from .png_executor import _get_shared_subtitle_executor
from .png_metadata import (
    _inspect_subtitle_png_bbox,
    _read_subtitle_dimensions_meta,
    _write_subtitle_dimensions_meta,
)
from .png_text import _wrap_text_by_pixel_static

logger = logging.getLogger(__name__)


def _expected_paths(cache_manager: CacheManager, key_data: Dict[str, Any], cache_key: str) -> tuple[Path, Path]:
    cached = cache_manager.get_cache_path(
        key_data=key_data, file_name="subtitle", extension="png"
    )
    ephemeral = (
        (cache_manager.ephemeral_dir or cache_manager.cache_dir)
        / f"temp_subtitle_{cache_key}.png"
    )
    return cached, ephemeral


def _log_png_bbox(path: Path, text_hash: str, started: float, cache_status: str) -> None:
    try:
        bbox = _inspect_subtitle_png_bbox(path)
        logger.info(
            "[SubtitlePNG] text_hash=%s size=%sx%s bbox=%s margin_ltrb=%s,%s,%s,%s full_canvas=%s render_ms=%.1f cache=%s",
            text_hash, bbox["width"], bbox["height"], bbox["bbox_mode"],
            bbox["transparent_left"], bbox["transparent_top"],
            bbox["transparent_right"], bbox["transparent_bottom"],
            bbox["full_canvas"], (time.perf_counter() - started) * 1000.0, cache_status,
        )
    except Exception:
        logger.debug("Failed to inspect subtitle PNG bbox: %s", path, exc_info=True)


async def _render_missing_png(
    *, executor: Any, text: str, style: Dict[str, Any],
    text_hash: str, output_path: Path,
) -> Path:
    logger.info("SubtitleEngine=image (cache miss), generating to %s", output_path.name)
    started = time.perf_counter()
    try:
        loop = asyncio.get_running_loop()
    except Exception:
        loop = None
    if loop is not None:
        width, height = await loop.run_in_executor(
            executor, _render_subtitle_png, text, style, str(output_path)
        )
    else:
        width, height = _render_subtitle_png(text, style, str(output_path))
    _write_subtitle_dimensions_meta(output_path, width, height)
    _log_png_bbox(output_path, text_hash, started, "miss")
    logger.info("Saved subtitle PNG to %s", output_path)
    return output_path


def _resolve_dimensions(path: Path) -> Dict[str, int]:
    dims = _read_subtitle_dimensions_meta(path)
    if dims is not None:
        return dims
    with Image.open(path) as image:
        width, height = image.width, image.height
    _write_subtitle_dimensions_meta(path, width, height)
    return {"w": width, "h": height}


class SubtitlePNGRenderer:
    """Generate and cache subtitle images using Pillow."""

    def __init__(self, cache_manager: CacheManager):
        self.cache_manager = cache_manager
        self.subtitle_cache_dir = cache_manager.cache_dir / "subtitles"
        self.subtitle_cache_dir.mkdir(exist_ok=True)
        self._executor, workers = _get_shared_subtitle_executor()
        logger.info("SubtitlePNGRenderer workers=%d", workers)

    async def render(self, text: str, style: Dict[str, Any]) -> Tuple[Path, Dict[str, int]]:
        key_data = {"text": text, "style": style}
        cache_key = self.cache_manager._generate_hash(key_data)
        cached, ephemeral = _expected_paths(self.cache_manager, key_data, cache_key)
        was_cached = ephemeral.exists() if self.cache_manager.no_cache else cached.exists()
        started = time.perf_counter()
        perf_stats.incr("subtitle_png")
        text_hash = hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()[:12]

        async def creator(path: Path) -> Path:
            return await _render_missing_png(
                executor=self._executor, text=text, style=style,
                text_hash=text_hash, output_path=path,
            )

        png_path = await self.cache_manager.get_or_create(
            key_data=key_data, file_name="subtitle", extension="png", creator_func=creator
        )
        dims = _resolve_dimensions(png_path)
        if was_cached:
            _log_png_bbox(png_path, text_hash, started, "hit")
        return png_path, dims

    def _wrap_text_by_pixel(self, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> str:
        return _wrap_text_by_pixel_static(text, font, max_width)

    def _wrap_text_by_chars(self, text: str, max_chars: int) -> str:
        return wrap_subtitle_text_by_display_width(text, max_chars)

    @staticmethod
    def _wrap_text_by_pixel_static(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> str:
        return _wrap_text_by_pixel_static(text, font, max_width)

    @staticmethod
    def _wrap_text_by_chars_static(text: str, max_chars: int) -> str:
        return wrap_subtitle_text_by_display_width(text, max_chars)
