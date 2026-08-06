"""Run-local latency instrumentation for SceneRenderer cache lookups."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Optional

from ....utils import perf_stats
from ....utils.logger import logger


class SceneCacheLatencyProxy:
    """Delegate CacheManager calls while measuring scene-level lookups."""

    def __init__(self, cache_manager: Any, *, scene_id: str) -> None:
        self._cache_manager = cache_manager
        self._scene_id = scene_id

    def __getattr__(self, name: str) -> Any:
        return getattr(self._cache_manager, name)

    @staticmethod
    def _layer(file_name: str) -> str:
        if file_name.endswith("_sub"):
            return "sub"
        if file_name.endswith("_base"):
            return "base"
        return "other"

    def get_cached_path(
        self,
        key_data: Any,
        file_name: str,
        extension: str,
    ) -> Optional[Path]:
        started = time.perf_counter()
        result = self._cache_manager.get_cached_path(
            key_data=key_data,
            file_name=file_name,
            extension=extension,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        status = "hit" if result is not None else "miss"
        layer = self._layer(file_name)

        perf_stats.incr("scene_cache_lookup_total")
        perf_stats.incr(f"scene_cache_lookup_{status}")
        perf_stats.incr(f"scene_cache_lookup_{layer}_{status}")
        perf_stats.add_ms("scene_cache_lookup_ms", elapsed_ms)
        perf_stats.add_ms(f"scene_cache_lookup_{status}_ms", elapsed_ms)
        perf_stats.add_ms(f"scene_cache_lookup_{layer}_ms", elapsed_ms)
        logger.info(
            "[SceneCacheLatency] scene=%s layer=%s status=%s elapsed_ms=%.3f file=%s",
            self._scene_id,
            layer,
            status.upper(),
            elapsed_ms,
            file_name,
        )
        return result
