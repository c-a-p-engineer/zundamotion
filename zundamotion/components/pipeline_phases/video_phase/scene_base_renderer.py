"""Scene-level base video generation and background normalization.

This module is an internal SceneRenderer mixin; use scene_renderer.SceneRenderer.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ....utils.ffmpeg_ops import normalize_media
from ....utils.logger import logger
from .scene_base_plan import SceneBasePlan


@dataclass(frozen=True)
class SceneBaseRenderResult:
    """Generated base paths consumed by per-line scene rendering."""

    scene_base_path: Optional[Path]
    normalized_background_path: Optional[Path]
    scene_level_insert_video: Optional[Path]


class SceneBaseRendererMixin:
    """Execute the I/O described by a :class:`SceneBasePlan`."""

    async def _normalize_common_insert_video(
        self,
        *,
        scene_id: str,
        plan: SceneBasePlan,
    ) -> Optional[Path]:
        insert_path = plan.common_insert_video_path
        if insert_path is None:
            return None
        try:
            normalized = await normalize_media(
                input_path=insert_path,
                video_params=self.video_params,
                audio_params=self.audio_params,
                cache_manager=self.cache_manager,
            )
            logger.info(
                "Scene %s: pre-normalized common insert video -> %s",
                scene_id,
                normalized.name,
            )
            return None if plan.scene_copy else normalized
        except Exception as error:
            logger.warning(
                "Scene %s: failed to pre-normalize common insert video %s: %s",
                scene_id,
                insert_path.name,
                error,
            )
            return None

    async def _normalize_scene_background(
        self,
        *,
        background_path: Path,
        layout: dict,
    ) -> Path:
        return await normalize_media(
            input_path=background_path,
            video_params=self.video_params,
            audio_params=self.audio_params,
            cache_manager=self.cache_manager,
            fit_mode=layout["fit"],
            fill_color=layout["fill_color"],
            anchor=layout["anchor"],
            position=layout["position"],
            scale_flags=self.video_renderer.scale_flags,
        )

    async def _render_planned_scene_base(
        self,
        *,
        scene_id: str,
        background: str,
        is_background_video: bool,
        scene_duration: float,
        plan: SceneBasePlan,
    ) -> Optional[Path]:
        background_config = {
            "type": "video" if is_background_video else "image",
            "path": str(background),
            "fit": plan.base_background_layout["fit"],
            "fill_color": plan.base_background_layout["fill_color"],
            "anchor": plan.base_background_layout["anchor"],
            "position": dict(plan.base_background_layout["position"]),
        }
        if plan.static_overlays:
            return await self.video_renderer.render_scene_base_composited(
                background_config,
                scene_duration,
                f"scene_base_{scene_id}",
                plan.static_overlays,
            )

        key_data = {
            "type": "shared_scene_base",
            "version": "20260502_v1",
            "background_config": background_config,
            "duration": round(float(scene_duration), 3),
            "video_params": self.video_params.__dict__,
            "audio_params": self.audio_params.__dict__,
            "hw_kind": self.hw_kind,
        }

        async def creator(output_path: Path) -> Path:
            return await self.video_renderer.render_scene_base(
                background_config,
                scene_duration,
                output_path.stem,
            )

        return await self.cache_manager.get_or_create(
            key_data=key_data,
            file_name="scene_base_shared",
            extension="mp4",
            creator_func=creator,
        )

    async def _render_scene_base_fallback(
        self,
        *,
        scene_id: str,
        background: str,
        scene_duration: float,
        plan: SceneBasePlan,
    ) -> tuple[Optional[Path], Optional[Path]]:
        try:
            normalized = await self._normalize_scene_background(
                background_path=Path(background),
                layout=plan.base_background_layout,
            )
            base_path = await self.video_renderer.render_looped_background_video(
                str(normalized),
                scene_duration,
                f"scene_bg_{scene_id}",
                fit_mode=plan.base_background_layout["fit"],
                fill_color=plan.base_background_layout["fill_color"],
                anchor=plan.base_background_layout["anchor"],
                position=plan.base_background_layout["position"],
            )
            if base_path:
                logger.debug(
                    "Fallback generated looped background -> %s",
                    base_path.name,
                )
            return base_path, normalized
        except Exception as error:
            logger.warning(
                "Fallback looped BG generation also failed for scene %s: %s",
                scene_id,
                error,
            )
            return None, None

    async def _prepare_scene_base(
        self,
        *,
        scene_id: str,
        background: str,
        is_background_video: bool,
        scene_duration: float,
        plan: SceneBasePlan,
    ) -> SceneBaseRenderResult:
        insert_video = await self._normalize_common_insert_video(
            scene_id=scene_id,
            plan=plan,
        )
        scene_base_path: Optional[Path] = None
        normalized_background: Optional[Path] = None

        if plan.should_generate_base:
            try:
                scene_base_path = await self._render_planned_scene_base(
                    scene_id=scene_id,
                    background=background,
                    is_background_video=is_background_video,
                    scene_duration=scene_duration,
                    plan=plan,
                )
                if scene_base_path:
                    logger.info(
                        "Scene %s: generated base with %d static overlay(s) -> %s",
                        scene_id,
                        len(plan.static_overlays),
                        scene_base_path.name,
                    )
            except Exception as error:
                logger.warning(
                    "Failed to generate scene base for scene %s: %s",
                    scene_id,
                    error,
                )
                if is_background_video:
                    scene_base_path, normalized_background = (
                        await self._render_scene_base_fallback(
                            scene_id=scene_id,
                            background=background,
                            scene_duration=scene_duration,
                            plan=plan,
                        )
                    )
        elif is_background_video:
            try:
                normalized_background = await self._normalize_scene_background(
                    background_path=Path(background),
                    layout=plan.base_background_layout,
                )
                logger.info(
                    "Scene %s: skipping base generation (static_overlays=%d, lines=%d < threshold=%d). Using pre-normalized background.",
                    scene_id,
                    len(plan.static_overlays),
                    plan.total_lines,
                    plan.minimum_lines,
                )
            except Exception as error:
                logger.warning(
                    "Scene %s: background pre-normalization failed (%s). Proceeding as-is without base.",
                    scene_id,
                    error,
                )

        return SceneBaseRenderResult(
            scene_base_path=scene_base_path,
            normalized_background_path=normalized_background,
            scene_level_insert_video=insert_video,
        )
