"""Render planned consecutive Run Base videos with original line indexes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

from ....utils.logger import logger
from .scene_run_base_plan import RunBasePlan


@dataclass(frozen=True)
class RenderedRunBase:
    """One generated Run Base and its original-line timing map."""

    start_line: int
    end_line: int
    path: Path
    character_keys: frozenset[str]
    has_insert_image: bool
    offsets: Mapping[int, float]


class SceneRunBaseRendererMixin:
    """Generate Run Base videos from pure plans without re-planning lines."""

    async def _prepare_run_bases(
        self,
        *,
        scene_id: str,
        background: str,
        is_background_video: bool,
        scene_base_path: Optional[Path],
        scene_copy: bool,
        has_line_background_override: bool,
    ) -> list[RenderedRunBase]:
        if scene_base_path is not None or scene_copy or has_line_background_override:
            return []

        plans = self._build_run_base_plans(scene_id)
        if not plans:
            return []

        rendered: list[RenderedRunBase] = []
        background_config: Dict[str, Any] = {
            "type": "video" if is_background_video else "image",
            "path": str(background),
        }
        for plan in plans:
            result = await self._render_run_base_plan(
                scene_id=scene_id,
                background_config=background_config,
                plan=plan,
            )
            if result is not None:
                rendered.append(result)
        return rendered

    async def _render_run_base_plan(
        self,
        *,
        scene_id: str,
        background_config: Dict[str, Any],
        plan: RunBasePlan,
    ) -> Optional[RenderedRunBase]:
        output_name = (
            f"scene_base_{scene_id}_run_{plan.start_line}_{plan.end_line}"
        )
        try:
            path = await self.video_renderer.render_scene_base_composited(
                background_config,
                plan.duration,
                output_name,
                list(plan.overlays),
            )
        except Exception as error:
            logger.warning(
                "[RunBase] generation failed scene=%s start=%d end=%d error=%s",
                scene_id,
                plan.start_line,
                plan.end_line,
                error,
            )
            return None

        logger.info(
            "[RunBase] generated scene=%s start=%d end=%d duration=%.3f offsets=%d path=%s",
            scene_id,
            plan.start_line,
            plan.end_line,
            plan.duration,
            len(plan.offsets),
            path,
        )
        return RenderedRunBase(
            start_line=plan.start_line,
            end_line=plan.end_line,
            path=Path(path),
            character_keys=plan.character_keys,
            has_insert_image=plan.has_insert_image,
            offsets=dict(plan.offsets),
        )

    @staticmethod
    def _find_run_base(
        run_bases: Iterable[RenderedRunBase],
        line_index: int,
    ) -> Optional[RenderedRunBase]:
        for run_base in run_bases:
            if run_base.start_line <= line_index <= run_base.end_line:
                return run_base
        return None
