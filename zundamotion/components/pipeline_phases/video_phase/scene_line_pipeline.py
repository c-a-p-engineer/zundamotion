"""Base preparation and per-line execution stage for standard scenes."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from ....utils.logger import logger
from .scene_run_base_renderer import RenderedRunBase
from .scene_standard_context import StandardSceneContext


@dataclass(frozen=True)
class StandardSceneLayers:
    """Prepared base media and static-layer decisions for line rendering."""

    static_character_keys: frozenset[Any]
    static_insert_in_base: bool
    scene_level_insert_video: Optional[Path]
    scene_base_path: Optional[Path]
    normalized_background_path: Optional[Path]
    run_bases: tuple[RenderedRunBase, ...]
    image_layers_by_line: Dict[int, List[Dict[str, Any]]]


class SceneLinePipelineMixin:
    """Prepare base layers and execute wait/talk lines in original order."""

    async def _prepare_standard_scene_layers(
        self,
        context: StandardSceneContext,
    ) -> StandardSceneLayers:
        timing = context.timing
        base_plan = self._build_scene_base_plan(
            scene=context.scene,
            scene_copy=context.scene_copy,
            is_background_video=context.is_background_video,
            has_line_background_override=context.has_line_background_override,
        )
        if base_plan.detection_error is not None:
            logger.debug(
                "Static overlay detection failed on scene %s: %s",
                context.scene_id,
                base_plan.detection_error,
            )
        base_result = await self._prepare_scene_base(
            scene_id=context.scene_id,
            background=context.background,
            is_background_video=context.is_background_video,
            scene_duration=timing.scene_duration,
            plan=base_plan,
        )
        run_bases = await self._prepare_run_bases(
            scene_id=context.scene_id,
            background=str(context.background),
            is_background_video=context.is_background_video,
            scene_base_path=base_result.scene_base_path,
            scene_copy=context.scene_copy,
            has_line_background_override=context.has_line_background_override,
        )
        image_layers_by_line = self._collect_image_layers_by_line(
            [line for _, line in timing.lines]
        )
        return StandardSceneLayers(
            static_character_keys=frozenset(
                base_plan.static_character_keys
            ),
            static_insert_in_base=base_plan.static_insert_in_base,
            scene_level_insert_video=base_result.scene_level_insert_video,
            scene_base_path=base_result.scene_base_path,
            normalized_background_path=base_result.normalized_background_path,
            run_bases=tuple(run_bases),
            image_layers_by_line=image_layers_by_line,
        )

    async def _render_standard_scene_lines(
        self,
        context: StandardSceneContext,
        layers: StandardSceneLayers,
    ) -> List[Optional[Path]]:
        timing = context.timing

        async def process_one(
            line_index: int,
            line: Dict[str, Any],
        ) -> Optional[Path]:
            line_total_started = time.perf_counter()
            line_context = self._build_scene_line_context(
                scene_id=context.scene_id,
                line_index=line_index,
                line=line,
                scene_background=str(context.background),
                scene_base_path=layers.scene_base_path,
                normalized_background_path=layers.normalized_background_path,
                start_time_by_index=timing.start_time_by_idx,
                run_bases=list(layers.run_bases),
                image_layers_by_line=layers.image_layers_by_line,
            )
            if line_context.line_type == "image_layer":
                return None
            if line_context.line_type == "wait":
                return await self._render_wait_line(line_context)

            logger.debug(
                "Rendering clip for line '%s...' (Scene '%s', Line %s)",
                line_context.text[:30],
                context.scene_id,
                line_index,
            )
            talk_plan = self._build_scene_talk_plan(
                context=line_context,
                static_character_keys=layers.static_character_keys,
                static_insert_in_base=layers.static_insert_in_base,
                scene_level_insert_video=layers.scene_level_insert_video,
            )
            render_outcome = await self._render_talk_line(
                context=line_context,
                plan=talk_plan,
                static_character_keys=layers.static_character_keys,
                static_insert_in_base=layers.static_insert_in_base,
            )
            self._record_talk_line_metrics(
                scene_id=context.scene_id,
                context=line_context,
                plan=talk_plan,
                outcome=render_outcome,
                line_total_started=line_total_started,
            )
            return render_outcome.path

        return await self._execute_scene_lines(
            timing.lines,
            process_one,
            max_workers=self.phase.clip_workers,
            scene_id=context.scene_id,
        )
