"""Scene cache payloads, short keys, and subtitle entry construction.

This module is an internal SceneRenderer mixin; use scene_renderer.SceneRenderer.
"""

from __future__ import annotations

from typing import Any, Dict, List

from ....utils import perf_stats
from ....utils.subtitle_text import is_effective_subtitle_text


class SceneCacheMixin:
    """Build cache payloads and subtitle timing entries."""

    def _scene_base_cache_data(self, scene_hash_data: Dict[str, Any]) -> Dict[str, Any]:
        """Build cache data for the no-subtitle scene layer."""
        base_data = self._without_subtitle_only_fields(scene_hash_data)
        base_data.update(
            {
                "scene_cache_layer": "base_no_subtitle",
                "scene_base_cache_version": "20260717_scene_base_v2",
            }
        )
        return base_data

    @classmethod
    def _without_subtitle_only_fields(cls, value: Any) -> Any:
        """Remove fields that affect only the subtitle-burned layer."""

        if isinstance(value, dict):
            return {
                key: cls._without_subtitle_only_fields(item)
                for key, item in value.items()
                if key not in {"subtitle", "subtitle_config", "subtitle_text"}
            }
        if isinstance(value, list):
            return [cls._without_subtitle_only_fields(item) for item in value]
        if isinstance(value, tuple):
            return tuple(cls._without_subtitle_only_fields(item) for item in value)
        return value

    def _scene_subtitle_cache_data(
        self,
        scene_hash_data: Dict[str, Any],
        scene_base_hash_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Build cache data for the subtitle-burned scene layer."""
        return {
            **scene_hash_data,
            "scene_cache_layer": "subtitle_burned",
            "scene_subtitle_cache_version": "20260717_scene_sub_v2",
            "scene_base_cache_key": self.cache_manager._generate_hash(
                scene_base_hash_data
            ),
        }

    def _cache_key_short(self, key_data: Dict[str, Any]) -> str:
        try:
            return self.cache_manager._generate_hash(key_data)[:8]
        except Exception:
            return "-"

    def _scene_cache_component_keys(
        self,
        scene_hash_data: Dict[str, Any],
        scene_base_hash_data: Dict[str, Any],
    ) -> Dict[str, str]:
        """Return short component keys that explain scene cache invalidation."""
        subtitle_config_data = {
            "scene_cache_component": "subtitle_config",
            "subtitle_config": scene_hash_data.get("subtitle_config", {}),
        }
        return {
            "base_key": self._cache_key_short(scene_base_hash_data),
            "subtitle_config_key": self._cache_key_short(subtitle_config_data),
        }

    def _subtitle_timing_key(self, subtitle_entries: List[Dict[str, Any]]) -> str:
        timing_data = {
            "scene_cache_component": "subtitle_timing",
            "entries": [
                {
                    "text": item.get("text", ""),
                    "start": round(float(item.get("start", 0.0) or 0.0), 3),
                    "duration": round(float(item.get("duration", 0.0) or 0.0), 3),
                    "line_config": item.get("line_config", {}),
                }
                for item in subtitle_entries
            ],
        }
        return self._cache_key_short(timing_data)

    def _record_scene_cache_event(
        self,
        *,
        scene_id: str,
        layer: str,
        status: str,
        key: str = "-",
        reason: str | None = None,
        detail: Dict[str, Any] | None = None,
    ) -> None:
        perf_stats.record_scene_cache_event(
            scene_id=scene_id,
            layer=layer,
            status=status,
            key=key,
            reason=reason,
            detail=detail,
        )

    def _build_subtitle_entries(
        self,
        scene_id: str,
        start_time_by_idx: Dict[int, float],
    ) -> List[Dict[str, Any]]:
        subtitle_entries: List[Dict[str, Any]] = []
        for idx, _line in enumerate(self.scene.get("lines", []) or [], start=1):
            data = self.line_data_map.get(f"{scene_id}_{idx}") or {}
            text = data.get("text")
            if not is_effective_subtitle_text(text):
                continue
            subtitle_entries.append(
                {
                    "text": text,
                    "line_config": data.get("line_config", {}),
                    "duration": float(data.get("duration", 0.0)),
                    "start": float(start_time_by_idx.get(idx, 0.0)),
                }
            )
        subtitle_entries.sort(key=lambda item: item["start"])
        return subtitle_entries
