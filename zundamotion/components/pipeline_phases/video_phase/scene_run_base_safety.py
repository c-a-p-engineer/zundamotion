"""Temporary correctness guard for the legacy inline Run Base optimizer."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pathlib import Path

from ....utils.logger import logger


class SceneRunBaseSafetyMixin:
    """Disable the known-unsafe inline Run Base path until planner integration."""

    def _legacy_run_base_enabled(self) -> bool:
        video_config = self.config.get("video", {}) or {}
        return bool(video_config.get("legacy_run_base_enabled", False))

    async def _render_scene_internal(
        self,
        scene: Dict[str, Any],
        scene_cp: bool,
        bg_default: Optional[str],
        scene_hash_data: Dict[str, Any],
    ) -> List[Path]:
        if self._legacy_run_base_enabled():
            logger.warning(
                "[RunBase] legacy inline optimizer explicitly enabled for scene=%s; "
                "original-index planner is not connected yet",
                scene.get("id", "unknown"),
            )
            effective_scene_copy = scene_cp
        else:
            # In the current standard renderer, scene_cp only controls static
            # scene-layer extraction and the legacy Run Base condition. Passing
            # True keeps output layers on the per-line path and prevents the
            # unsafe filtered-index optimization from running.
            effective_scene_copy = True
            logger.info(
                "[RunBase] legacy optimizer disabled scene=%s reason=correctness_guard",
                scene.get("id", "unknown"),
            )
        return await super()._render_scene_internal(
            scene,
            effective_scene_copy,
            bg_default,
            scene_hash_data,
        )
