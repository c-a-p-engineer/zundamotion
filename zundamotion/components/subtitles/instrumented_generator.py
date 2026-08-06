"""SubtitleGenerator facade with run-local PNG request instrumentation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Tuple

from ...utils import perf_stats
from ...utils.logger import logger
from .generator import SubtitleGenerator as BaseSubtitleGenerator
from .png import SubtitlePNGRenderer


class SubtitlePNGMetricsProxy:
    """Measure requests without changing PNG generation or cache keys."""

    def __init__(self, renderer: SubtitlePNGRenderer, cache_manager: Any) -> None:
        self._renderer = renderer
        self._cache_manager = cache_manager
        self._seen_keys: set[str] = set()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._renderer, name)

    def _expected_path(self, key_data: Dict[str, Any], cache_key: str) -> Path:
        if bool(getattr(self._cache_manager, "no_cache", False)):
            root = (
                getattr(self._cache_manager, "ephemeral_dir", None)
                or self._cache_manager.cache_dir
            )
            return Path(root) / f"temp_subtitle_{cache_key}.png"
        return self._cache_manager.get_cache_path(
            key_data=key_data,
            file_name="subtitle",
            extension="png",
        )

    async def render(
        self,
        text: str,
        style: Dict[str, Any],
    ) -> Tuple[Path, Dict[str, int]]:
        key_data = {"text": text, "style": style}
        cache_key = self._cache_manager._generate_hash(key_data)
        expected_path = self._expected_path(key_data, cache_key)
        first_request = cache_key not in self._seen_keys
        existed_before = expected_path.exists()

        perf_stats.incr("subtitle_png_request")
        if first_request:
            self._seen_keys.add(cache_key)
            perf_stats.incr("subtitle_png_unique")
        else:
            perf_stats.incr("subtitle_png_run_repeat")

        result = await self._renderer.render(text, style)
        if first_request:
            if existed_before:
                if bool(getattr(self._cache_manager, "no_cache", False)):
                    perf_stats.incr("subtitle_png_ephemeral_hit")
                    status = "ephemeral_hit"
                else:
                    perf_stats.incr("subtitle_png_persistent_hit")
                    status = "persistent_hit"
            else:
                perf_stats.incr("subtitle_png_generated")
                status = "generated"
            logger.info(
                "[SubtitlePNGMetric] status=%s key=%s file=%s",
                status,
                cache_key[:12],
                result[0].name,
            )
        return result


class SubtitleGenerator(BaseSubtitleGenerator):
    """Compatibility subclass that instruments only PNG renderer requests."""

    @property
    def png_renderer(self) -> SubtitlePNGMetricsProxy:
        if self._png_renderer is None:
            renderer = SubtitlePNGRenderer(self._cache_manager)
            self._png_renderer = SubtitlePNGMetricsProxy(
                renderer,
                self._cache_manager,
            )
        return self._png_renderer
