"""Wait-line cache planning, rendering, and foreground application."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from ....exceptions import PipelineError
from ....utils.logger import logger
from .scene_line_context import SceneLineContext


class SceneWaitRendererMixin:
    """Render one resolved wait line without owning line scheduling."""

    def _build_wait_cache_data(
        self,
        context: SceneLineContext,
    ) -> Dict[str, Any]:
        """Build the legacy-compatible wait clip cache payload."""
        line_config = context.line_config
        return {
            "type": "wait",
            "duration": context.duration,
            "bg_image_path": context.background_source,
            "is_bg_video": context.background_is_video,
            "start_time": context.scene_start_time,
            "video_config": self.config.get("video", {}),
            "line_config": line_config,
            "image_layer_overlays": list(context.image_layer_overlays),
            "extra_audio_overlays": list(context.extra_audio_overlays),
            "hw_kind": self.hw_kind,
            "video_params": self.video_params.__dict__,
            "audio_params": self.audio_params.__dict__,
            "screen_effects": line_config.get("screen_effects"),
            "background_effects": line_config.get("background_effects"),
            "background_layout": context.background_layout,
            "video_filter": context.background_config.get("video_filter"),
        }

    async def _render_wait_line(self, context: SceneLineContext) -> Path:
        """Resolve cache, render on miss, then apply line foreground overlays."""
        logger.debug(
            "Rendering wait clip for %ss (Scene line '%s')",
            context.duration,
            context.line_id,
        )
        wait_cache_data = self._build_wait_cache_data(context)
        line_config = context.line_config
        image_layer_overlays = list(context.image_layer_overlays)
        extra_audio_overlays = list(context.extra_audio_overlays)

        async def creator(output_path: Path) -> Path:
            clip_path = await self.video_renderer.render_wait_clip(
                context.duration,
                context.background_config,
                output_path.stem,
                line_config,
                characters_config=line_config.get("characters", []) or [],
                image_layer_overlays=image_layer_overlays,
                extra_audio_overlays=extra_audio_overlays,
            )
            if clip_path is None:
                raise PipelineError(
                    f"Wait clip rendering failed for line: {context.line_id}"
                )
            return Path(clip_path)

        clip_path = await self.cache_manager.get_or_create(
            key_data=wait_cache_data,
            file_name=context.line_id,
            extension="mp4",
            creator_func=creator,
        )
        foreground_overlays = await self._resolve_visual_overlays(
            context.visual_container,
            scope_id=context.line_id,
        )
        if foreground_overlays:
            clip_path = await self.video_renderer.apply_foreground_overlays(
                Path(clip_path),
                foreground_overlays,
            )
        return Path(clip_path)
