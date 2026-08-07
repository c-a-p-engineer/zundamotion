"""Public CacheManager facade.

The historical implementation is retained in ``cache_base`` for behavior
compatibility while run diagnostics, media-probe caching, and lifecycle policy
are composed as explicit responsibilities here.
"""

from __future__ import annotations

from .cache_base import (
    _CACHE_KEY_PATH_FIELDS,
    _IMAGE_CACHE_KEY_SUFFIXES,
    _MEDIA_CACHE_KEY_SUFFIXES,
)
from .cache_lifecycle import CacheLifecycleMixin
from .cache_media import CacheMediaProbeMixin
from .cache_runtime import CacheManager as _RuntimeCacheManager
from .exceptions import CacheError
from .utils.ffmpeg_ops import normalize_media
from .utils.ffmpeg_params import AudioParams, VideoParams
from .utils.ffmpeg_probe import (
    MediaInfo,
    get_media_duration,
    get_media_info,
    probe_media_params_async,
)


class CacheManager(
    CacheLifecycleMixin,
    CacheMediaProbeMixin,
    _RuntimeCacheManager,
):
    """Compatibility facade for the modular cache implementation."""


__all__ = [
    "CacheManager",
    "CacheError",
    "MediaInfo",
    "AudioParams",
    "VideoParams",
    "get_media_info",
    "get_media_duration",
    "probe_media_params_async",
    "normalize_media",
]
