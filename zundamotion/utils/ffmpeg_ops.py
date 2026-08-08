# -*- coding: utf-8 -*-
"""Compatibility facade for modular FFmpeg high-level utilities."""

from .ffmpeg_background import (
    BACKGROUND_FIT_CONTAIN,
    BACKGROUND_FIT_COVER,
    BACKGROUND_FIT_HEIGHT,
    BACKGROUND_FIT_MODES,
    BACKGROUND_FIT_STRETCH,
    BACKGROUND_FIT_WIDTH,
    DEFAULT_BACKGROUND_ANCHOR,
    DEFAULT_BACKGROUND_FILL_COLOR,
    _sanitize_anchor,
    _to_expr,
    build_background_filter_complex,
    build_background_fit_steps,
    calculate_overlay_position,
    compose_background_filter_expression,
)
from .ffmpeg_concat import (
    TimestampWarningError,
    _contains_dts_warning,
    _log_transition_concat,
    compare_media_params,
    concat_videos_copy,
    concat_videos_safe,
)
from .ffmpeg_normalize import normalize_media
from .ffmpeg_transition import (
    _copy_segment,
    _create_freeze_tail,
    _encode_segment,
    apply_transition,
    apply_transition_local,
)

__all__ = [
    "BACKGROUND_FIT_STRETCH",
    "BACKGROUND_FIT_CONTAIN",
    "BACKGROUND_FIT_COVER",
    "BACKGROUND_FIT_WIDTH",
    "BACKGROUND_FIT_HEIGHT",
    "BACKGROUND_FIT_MODES",
    "DEFAULT_BACKGROUND_ANCHOR",
    "DEFAULT_BACKGROUND_FILL_COLOR",
    "TimestampWarningError",
    "build_background_fit_steps",
    "build_background_filter_complex",
    "compose_background_filter_expression",
    "compare_media_params",
    "concat_videos_copy",
    "concat_videos_safe",
    "apply_transition_local",
    "apply_transition",
    "calculate_overlay_position",
    "normalize_media",
]
