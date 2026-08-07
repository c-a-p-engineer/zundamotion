"""Preflight, scene cache reuse, and fast-path stages for standard rendering."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from ....exceptions import PipelineError
from ....utils import perf_stats
from ....utils.logger import logger
from .scene_timing import SceneTimingPlan


@dataclass(frozen=True)
class StandardSceneContext:
    """Immutable inputs and derived state shared by standard render stages."""

    scene: Dict[str, Any]
    scene_copy: bool
    scene_hash_data: Dict[str, Any]
    scene_id: str
    generate_no_sub_video: bool
    cache_scene_base_video: bool
    scene_base_hash_data: Dict[str, Any]
    scene_sub_hash_data: Dict[str, Any]
    background: Any
    is_background_video: bool
    has_line_background_override: bool
    timing: SceneTimingPlan


class SceneStandardContextMixin:
    """Build standard context and resolve early-return render paths."""

    def _prepare_standard_scene_context(
        self,
        *,
        scene: Dict[str, Any],
        scene_copy: bool,
        background_default: Optional[str],
        scene_hash_data: Dict[str, Any],
    ) -> StandardSceneContext:
        scene_id = scene["id"]
        generate_no_sub_video = bool(
            self.config.get("system", {}).get("generate_no_sub_video", False)
        )
        cache_scene_base_video = bool(
            self.config.get("system", {}).get("cache_scene_base_video", True)
        )
        scene_base_hash_data = self._scene_base_cache_data(scene_hash_data)
        scene_sub_hash_data = self._scene_subtitle_cache_data(
            scene_hash_data,
            scene_base_hash_data,
        )

        background = scene.get("bg", background_default)
        if not background:
            raise PipelineError(f"Scene '{scene_id}' does not define a background.")
        is_background_video = (
            Path(background).suffix.lower() in self.video_extensions
        )
        has_line_background_override = any(
            isinstance((line.get("background") or {}), dict)
            and bool((line.get("background") or {}).get("path"))
            for line in scene.get("lines", [])
        )
        timing = self._build_scene_timing_plan(
            scene=scene,
            scene_hash_data=scene_hash_data,
            scene_base_hash_data=scene_base_hash_data,
        )
        return StandardSceneContext(
            scene=scene,
            scene_copy=scene_copy,
            scene_hash_data=scene_hash_data,
            scene_id=scene_id,
            generate_no_sub_video=generate_no_sub_video,
            cache_scene_base_video=cache_scene_base_video,
            scene_base_hash_data=scene_base_hash_data,
            scene_sub_hash_data=scene_sub_hash_data,
            background=background,
            is_background_video=is_background_video,
            has_line_background_override=has_line_background_override,
            timing=timing,
        )

    async def _resolve_standard_scene_cache(
        self,
        context: StandardSceneContext,
    ) -> Optional[List[Path]]:
        timing = context.timing
        component_keys = timing.component_keys
        subtitle_entries = timing.subtitle_entries
        subtitle_timing_key = timing.subtitle_timing_key
        scene_id = context.scene_id

        if not context.cache_scene_base_video:
            self._record_scene_cache_event(
                scene_id=scene_id,
                layer="base",
                status="DISABLED",
                reason="cache_scene_base_video_false",
                detail=component_keys,
            )
            logger.info(
                "[SceneCache] scene=%s layer=base disabled reason=cache_scene_base_video_false",
                scene_id,
            )
            return None

        cached_base_scene_path = self.cache_manager.get_cached_path(
            key_data=context.scene_base_hash_data,
            file_name=f"scene_{scene_id}_base",
            extension="mp4",
        )
        if not cached_base_scene_path:
            base_key = self._cache_key_short(context.scene_base_hash_data)
            self._record_scene_cache_event(
                scene_id=scene_id,
                layer="base",
                status="MISS",
                key=base_key,
                reason="base_video_not_cached",
                detail=component_keys,
            )
            logger.info(
                "[SceneCache] scene=%s layer=base MISS key=%s subtitle_timing_key=%s reason=%s",
                scene_id,
                base_key,
                subtitle_timing_key,
                "base_video_not_cached",
            )
            return None

        perf_stats.record_line_clips_skipped_by_scene_cache(
            sum(
                1
                for index, _line in timing.lines
                if (self.line_data_map.get(f"{scene_id}_{index}") or {}).get("type")
                != "image_layer"
            )
        )
        base_key = self._cache_key_short(context.scene_base_hash_data)
        self._record_scene_cache_event(
            scene_id=scene_id,
            layer="base",
            status="HIT",
            key=base_key,
            detail=component_keys,
        )
        logger.info(
            "[SceneCache] scene=%s layer=base HIT key=%s subtitle_timing_key=%s file=%s; reusing before subtitle burn",
            scene_id,
            base_key,
            subtitle_timing_key,
            cached_base_scene_path.name,
        )

        scene_output_path = cached_base_scene_path
        if subtitle_entries:
            self._record_scene_cache_event(
                scene_id=scene_id,
                layer="sub",
                status="MISS",
                key=self._cache_key_short(context.scene_sub_hash_data),
                reason="subtitle_layer_changed_base_hit",
                detail=component_keys,
            )
            scene_output_path = await self.video_renderer.apply_subtitle_overlays(
                cached_base_scene_path,
                subtitle_entries,
                scene_id=scene_id,
            )
            logger.info(
                "[SceneCache] scene=%s layer=sub MISS reason=subtitle_layer_changed_base_hit subtitle_timing_key=%s -> burned subtitles from cached base (%d subtitles)",
                scene_id,
                subtitle_timing_key,
                len(subtitle_entries),
            )
            self.cache_manager.cache_file(
                source_path=scene_output_path,
                key_data=context.scene_sub_hash_data,
                file_name=f"scene_{scene_id}_sub",
                extension="mp4",
            )
            logger.info(
                "[SceneCache] scene=%s layer=sub STORE key=%s subtitle_timing_key=%s subtitles=%d",
                scene_id,
                self._cache_key_short(context.scene_sub_hash_data),
                subtitle_timing_key,
                len(subtitle_entries),
            )
            if context.generate_no_sub_video:
                self.cache_manager.cache_file(
                    source_path=scene_output_path,
                    key_data=context.scene_hash_data,
                    file_name=f"scene_{scene_id}_sub",
                    extension="mp4",
                )

        self._complete_scene_render(None)
        return [scene_output_path]

    async def _try_standard_scene_fast_path(
        self,
        context: StandardSceneContext,
    ) -> Optional[List[Path]]:
        timing = context.timing
        can_use, reason = self._can_use_simple_scene_fast_path(
            scene_duration=timing.scene_duration,
            bg_image=context.background,
            generate_no_sub_video=context.generate_no_sub_video,
            start_time_by_idx=timing.start_time_by_idx,
        )
        if not can_use:
            logger.info(
                "Scene %s: skipping simple fast path (%s)",
                context.scene_id,
                reason,
            )
            return None

        path = await self._render_simple_scene_fast(
            scene_id=context.scene_id,
            bg_default=context.background,
            scene_duration=timing.scene_duration,
            start_time_by_idx=timing.start_time_by_idx,
            scene_hash_data=context.scene_hash_data,
        )
        if path is None:
            return None
        self._complete_scene_render(None)
        return [path]
