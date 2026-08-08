"""Compatibility facade for modular subtitle PNG rendering."""

from concurrent.futures import ProcessPoolExecutor

# Historical module-level state is retained because lifecycle management and
# tests intentionally mutate these slots. Executor policy lives in png_executor.
_SUBTITLE_EXECUTOR: ProcessPoolExecutor | None = None
_SUBTITLE_EXECUTOR_WORKERS: int | None = None

from .png_draw import _render_subtitle_png
from .png_executor import (
    _get_shared_subtitle_executor,
    _resolve_subtitle_png_workers,
    _shutdown_subtitle_executor,
)
from .png_metadata import (
    _inspect_subtitle_png_bbox,
    _read_subtitle_dimensions_meta,
    _subtitle_meta_path,
    _write_subtitle_dimensions_meta,
)
from .png_renderer import SubtitlePNGRenderer
from .png_style import (
    RESAMPLE_LANCZOS,
    _background_is_visible,
    _background_layer_cache_key,
    _build_background_layer,
    _build_background_layer_cached,
    _build_background_layer_cached_from_key,
    _clamp_float,
    _coerce_optional_bool,
    _extract_background_config,
    _normalize_padding,
    _resolve_rgba,
)
from .png_text import (
    _estimate_auto_max_chars,
    _fits_within_width,
    _load_font_with_fallback,
    _measure_text_width,
    _wrap_text_by_chars_static,
    _wrap_text_by_pixel_static,
)

__all__ = [
    "SubtitlePNGRenderer",
    "RESAMPLE_LANCZOS",
    "_SUBTITLE_EXECUTOR",
    "_SUBTITLE_EXECUTOR_WORKERS",
    "_render_subtitle_png",
    "_get_shared_subtitle_executor",
    "_resolve_subtitle_png_workers",
    "_shutdown_subtitle_executor",
    "_inspect_subtitle_png_bbox",
    "_read_subtitle_dimensions_meta",
    "_subtitle_meta_path",
    "_write_subtitle_dimensions_meta",
    "_background_is_visible",
    "_background_layer_cache_key",
    "_build_background_layer",
    "_build_background_layer_cached",
    "_build_background_layer_cached_from_key",
    "_clamp_float",
    "_coerce_optional_bool",
    "_extract_background_config",
    "_normalize_padding",
    "_resolve_rgba",
    "_estimate_auto_max_chars",
    "_fits_within_width",
    "_load_font_with_fallback",
    "_measure_text_width",
    "_wrap_text_by_chars_static",
    "_wrap_text_by_pixel_static",
]
