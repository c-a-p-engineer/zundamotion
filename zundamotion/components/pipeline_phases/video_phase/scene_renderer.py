"""Public per-scene renderer facade and orchestration entry point.

Implementation responsibilities live in the adjacent scene_* mixin modules.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Dict, List

from tqdm import tqdm

from ....utils.logger import logger
from .badge_tracker import BadgeTracker
from .scene_cache import SceneCacheMixin
from .scene_fast_path import SceneFastPathMixin
from .scene_preparation import ScenePreparationMixin
from .scene_standard_renderer import SceneStandardRendererMixin


class SceneRenderer(
    ScenePreparationMixin,
    SceneFastPathMixin,
    SceneCacheMixin,
    SceneStandardRendererMixin,
):
    """Initialize scene context and coordinate the selected render path."""

    def __init__(
        self,
        *,
        phase: Any,
        scene: Dict[str, Any],
        scene_hash_data: Dict[str, Any],
        scene_idx: int,
        total_scenes: int,
        line_data_map: Dict[str, Dict[str, Any]],
        timeline: Any,
        pbar_scenes: tqdm,
    ) -> None:
        self.phase = phase
        self.scene = scene
        self.scene_hash_data = scene_hash_data
        self.scene_idx = scene_idx
        self.total_scenes = total_scenes
        self.line_data_map = line_data_map
        self.timeline = timeline
        self.pbar_scenes = pbar_scenes

        # Shortcuts to frequently used phase attributes
        self.config = phase.config
        self.cache_manager = phase.cache_manager
        self.video_renderer = phase.video_renderer
        self.temp_dir = phase.temp_dir
        self.hw_kind = phase.hw_kind
        self.video_params = phase.video_params
        self.audio_params = phase.audio_params
        self.video_extensions = phase.video_extensions
        self._norm_char_entries = phase._norm_char_entries


    async def render_scene(self) -> List[Path]:
        scene = self.scene
        scene_id = scene["id"]
        bg_default = self.config.get("background", {}).get("default")
        pbar_scenes = self.pbar_scenes
        scene_hash_data = copy.deepcopy(self.scene_hash_data)
        scene_hash_data["scene_render_version"] = "20260502_subtitle_render_mode_v1"
        scene_base_hash_data = self._scene_base_cache_data(scene_hash_data)
        scene_sub_hash_data = self._scene_subtitle_cache_data(
            scene_hash_data,
            scene_base_hash_data,
        )

        scene_cp = bool(
            scene.get(
                "characters_persist",
                self.config.get("defaults", {}).get("characters_persist", False),
            )
        )
        badge_defs = scene.get("badges")
        if isinstance(badge_defs, list) and badge_defs:
            badge_tracker = BadgeTracker()
            badge_tracker.prime(
                [
                    item
                    for item in badge_defs
                    if isinstance(item, dict) and item.get("id")
                ]
            )
            for line in scene.get("lines", []):
                badge_updates = line.get("badges") or []
                persistent_updates = []
                transient_badges = []
                for item in badge_updates:
                    if not isinstance(item, dict):
                        continue
                    badge_id = item.get("id")
                    if isinstance(badge_id, str) and badge_tracker.has(badge_id):
                        persistent_updates.append(item)
                    elif (
                        item.get("text")
                        and item.get("position")
                        and item.get("visible", True) is not False
                    ):
                        transient_badges.append(item)
                if persistent_updates:
                    badge_tracker.apply(persistent_updates)
                snapshot = badge_tracker.snapshot() + transient_badges
                if snapshot:
                    line["_resolved_badges"] = snapshot
                else:
                    line.pop("_resolved_badges", None)
        tracker = None
        if scene_cp:
            from .character_tracker import CharacterTracker

            tracker = CharacterTracker(self.video_params.width, self.video_params.height)
            for idx, line in enumerate(scene.get("lines", []), start=1):
                if line.get("reset_characters"):
                    tracker.reset()
                tracker.apply(line.get("characters", []) or [])
                snap = tracker.snapshot()
                line_id = f"{scene_id}_{idx}"
                line_data = self.line_data_map.get(line_id)
                line_config = None
                if isinstance(line_data, dict):
                    line_config = line_data.get("line_config")
                if snap:
                    line["characters"] = snap
                    if isinstance(line_config, dict):
                        line_config["characters"] = copy.deepcopy(snap)
                else:
                    line.pop("characters", None)
                    if isinstance(line_config, dict):
                        line_config.pop("characters", None)

        bg_persist = bool(
            scene.get(
                "background_persist",
                self.config.get("defaults", {}).get("background_persist", False),
            )
        )
        if bg_persist:
            current_bg = scene.get("bg", bg_default)
            for idx, line in enumerate(scene.get("lines", []), start=1):
                line_bg = line.get("background")
                if isinstance(line_bg, dict) and line_bg.get("path"):
                    current_bg = str(line_bg["path"])
                elif current_bg:
                    line["background"] = {"path": current_bg}
                line_id = f"{scene_id}_{idx}"
                line_data = self.line_data_map.get(line_id)
                if line_data is not None and current_bg:
                    line_config = line_data.setdefault("line_config", {})
                    if isinstance(line_config, dict):
                        line_config["background"] = {"path": current_bg}

        generate_no_sub_video = bool(
            self.config.get("system", {}).get("generate_no_sub_video", False)
        )
        cached_scene_video_path = self.cache_manager.get_cached_path(
            key_data=scene_sub_hash_data,
            file_name=f"scene_{scene_id}_sub",
            extension="mp4",
        )
        if cached_scene_video_path:
            logger.info(
                "[SceneCache] scene=%s layer=sub HIT key=%s file=%s",
                scene_id,
                self._cache_key_short(scene_sub_hash_data),
                cached_scene_video_path.name,
            )
            pbar_scenes.update(1)
            return [cached_scene_video_path]

        cached_legacy_scene_video_path = self.cache_manager.get_cached_path(
            key_data=scene_hash_data,
            file_name=f"scene_{scene_id}",
            extension="mp4",
        )
        if cached_legacy_scene_video_path:
            logger.info(
                "[SceneCache] scene=%s layer=legacy HIT key=%s file=%s",
                scene_id,
                self._cache_key_short(scene_hash_data),
                cached_legacy_scene_video_path.name,
            )
            pbar_scenes.update(1)
            return [cached_legacy_scene_video_path]

        if generate_no_sub_video:
            cached_scene_video_path = self.cache_manager.get_cached_path(
                key_data=scene_hash_data,
                file_name=f"scene_{scene_id}_sub",
                extension="mp4",
            )
            if cached_scene_video_path:
                logger.info(
                    "[SceneCache] scene=%s layer=legacy_sub HIT key=%s file=%s",
                    scene_id,
                    self._cache_key_short(scene_hash_data),
                    cached_scene_video_path.name,
                )
                pbar_scenes.update(1)
                return [cached_scene_video_path]

        logger.info(
            "[SceneCache] scene=%s layer=sub MISS key=%s base_key=%s reason=%s",
            scene_id,
            self._cache_key_short(scene_sub_hash_data),
            self._cache_key_short(scene_base_hash_data),
            "subtitle_config_or_timing_changed",
        )

        if not getattr(self.phase, "parallel_scene_rendering", False):
            pbar_scenes.set_description(
                f"Scene Rendering (Scene {self.scene_idx + 1}/{self.total_scenes}: '{scene_id}')"
            )

        return await self._render_scene_internal(scene, scene_cp, bg_default, scene_hash_data)
