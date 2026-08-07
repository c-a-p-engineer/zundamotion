"""Persist assembled scene outputs using legacy-compatible cache contracts."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Sequence

from ....utils.logger import logger
from .scene_assembly import SceneAssemblyResult


class SceneResultCacheMixin:
    """Store assembled base, subtitle, and compatibility scene cache entries."""

    def _store_scene_result_cache(
        self,
        *,
        scene_id: str,
        assembly: SceneAssemblyResult,
        cache_scene_base_video: bool,
        subtitle_entries: Sequence[Dict[str, Any]],
        generate_no_sub_video: bool,
        scene_hash_data: Dict[str, Any],
        scene_base_hash_data: Dict[str, Any],
        scene_sub_hash_data: Dict[str, Any],
        subtitle_timing_key: str,
    ) -> Path:
        """Persist one assembled scene without changing cache key semantics."""
        no_sub_path = assembly.no_sub_path
        final_path = assembly.final_path

        if cache_scene_base_video:
            self.cache_manager.cache_file(
                source_path=no_sub_path,
                key_data=scene_base_hash_data,
                file_name=f"scene_{scene_id}_base",
                extension="mp4",
            )
            logger.info(
                "[SceneCache] scene=%s layer=base STORE key=%s subtitle_timing_key=%s file_name=scene_%s_base.mp4",
                scene_id,
                self._cache_key_short(scene_base_hash_data),
                subtitle_timing_key,
                scene_id,
            )

        if subtitle_entries:
            self.cache_manager.cache_file(
                source_path=final_path,
                key_data=scene_sub_hash_data,
                file_name=f"scene_{scene_id}_sub",
                extension="mp4",
            )
            logger.info(
                "[SceneCache] scene=%s layer=sub STORE key=%s subtitle_timing_key=%s subtitles=%d",
                scene_id,
                self._cache_key_short(scene_sub_hash_data),
                subtitle_timing_key,
                len(subtitle_entries),
            )
            if generate_no_sub_video:
                self.cache_manager.cache_file(
                    source_path=no_sub_path,
                    key_data=scene_hash_data,
                    file_name=f"scene_{scene_id}",
                    extension="mp4",
                )
                self.cache_manager.cache_file(
                    source_path=final_path,
                    key_data=scene_hash_data,
                    file_name=f"scene_{scene_id}_sub",
                    extension="mp4",
                )
        else:
            self.cache_manager.cache_file(
                source_path=final_path,
                key_data=scene_hash_data,
                file_name=f"scene_{scene_id}",
                extension="mp4",
            )

        return final_path
