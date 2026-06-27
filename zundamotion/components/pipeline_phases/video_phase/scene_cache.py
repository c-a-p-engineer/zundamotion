"""Scene cache payloads, short keys, and subtitle entry construction.

This module is an internal SceneRenderer mixin; use scene_renderer.SceneRenderer.
"""

from __future__ import annotations

from typing import Any, Dict, List

from ....utils.subtitle_text import is_effective_subtitle_text


class SceneCacheMixin:
    """Build cache payloads and subtitle timing entries."""

    def _scene_base_cache_data(self, scene_hash_data: Dict[str, Any]) -> Dict[str, Any]:
        """Build cache data for the no-subtitle scene layer."""
        base_data = {
            key: value
            for key, value in scene_hash_data.items()
            if key != "subtitle_config"
        }
        base_data.update(
            {
                "scene_cache_layer": "base_no_subtitle",
                "scene_base_cache_version": "20260510_scene_base_v1",
            }
        )
        return base_data

    def _scene_subtitle_cache_data(
        self,
        scene_hash_data: Dict[str, Any],
        scene_base_hash_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Build cache data for the subtitle-burned scene layer."""
        return {
            **scene_hash_data,
            "scene_cache_layer": "subtitle_burned",
            "scene_subtitle_cache_version": "20260510_scene_sub_v1",
            "scene_base_cache_key": self.cache_manager._generate_hash(
                scene_base_hash_data
            ),
        }

    def _cache_key_short(self, key_data: Dict[str, Any]) -> str:
        try:
            return self.cache_manager._generate_hash(key_data)[:8]
        except Exception:
            return "-"

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
