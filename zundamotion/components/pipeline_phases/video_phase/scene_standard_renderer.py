"""Standard scene render orchestration.

This module is an internal SceneRenderer mixin; use scene_renderer.SceneRenderer.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional


class SceneStandardRendererMixin:
    """Coordinate the named stages of standard per-line scene rendering."""

    async def _render_scene_internal(
        self,
        scene: Dict[str, Any],
        scene_cp: bool,
        bg_default: Optional[str],
        scene_hash_data: Dict[str, Any],
    ) -> List[Path]:
        context = self._prepare_standard_scene_context(
            scene=scene,
            scene_copy=scene_cp,
            background_default=bg_default,
            scene_hash_data=scene_hash_data,
        )

        cached_result = await self._resolve_standard_scene_cache(context)
        if cached_result is not None:
            return cached_result

        fast_result = await self._try_standard_scene_fast_path(context)
        if fast_result is not None:
            return fast_result

        await self._precache_standard_scene_assets(context)
        layers = await self._prepare_standard_scene_layers(context)
        line_results = await self._render_standard_scene_lines(
            context,
            layers,
        )
        await self._maybe_retune_line_workers()

        assembly = await self._assemble_scene_media(
            scene_id=context.scene_id,
            line_results=line_results,
            scene=context.scene,
            badge_line_markers=context.timing.badge_line_markers,
            subtitle_entries=context.timing.subtitle_entries,
        )
        scene_results: List[Path] = []
        if assembly is not None:
            scene_results.append(
                self._store_scene_result_cache(
                    scene_id=context.scene_id,
                    assembly=assembly,
                    cache_scene_base_video=context.cache_scene_base_video,
                    subtitle_entries=context.timing.subtitle_entries,
                    generate_no_sub_video=context.generate_no_sub_video,
                    scene_hash_data=context.scene_hash_data,
                    scene_base_hash_data=context.scene_base_hash_data,
                    scene_sub_hash_data=context.scene_sub_hash_data,
                    subtitle_timing_key=context.timing.subtitle_timing_key,
                )
            )

        self._complete_scene_render(layers.scene_base_path)
        return scene_results
