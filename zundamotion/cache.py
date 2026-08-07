"""Public CacheManager facade.

The historical implementation is retained in ``cache_base`` for behavior
compatibility while run diagnostics, media-probe caching, and lifecycle policy
are composed as explicit responsibilities here.
"""

from __future__ import annotations

import inspect
from pathlib import Path

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

    @staticmethod
    def _infer_probe_caller() -> str:
        internal_suffixes = (
            ".cache",
            ".cache_base",
            ".cache_runtime",
            ".cache_media",
            ".ffmpeg_probe",
        )
        for frame in inspect.stack()[2:]:
            module = inspect.getmodule(frame.frame)
            module_name = getattr(module, "__name__", "")
            if module_name.endswith(internal_suffixes):
                continue
            return str(frame.function)
        return "unknown"

    def _record_probe_cache_hit(
        self,
        *,
        file_path: Path,
        path: Path,
        caller: str,
        kind: str,
    ) -> None:
        metric_kind = "stream" if kind == "media_info" else kind
        super()._record_probe_cache_hit(
            file_path=file_path,
            path=path,
            caller=caller,
            kind=metric_kind,
        )


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
