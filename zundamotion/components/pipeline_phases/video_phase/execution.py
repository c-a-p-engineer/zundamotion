"""Scene preload, worker policy, and result aggregation for VideoPhase."""

from __future__ import annotations

import asyncio
import contextvars
import os
from pathlib import Path
from typing import Any, Dict, List, Tuple

from zundamotion.components.video import VideoRenderer
from zundamotion.timeline import Timeline
from zundamotion.utils.ffmpeg_hw import get_hw_filter_mode
from zundamotion.utils.logger import logger
from .preload import build_preload_assets, preload_assets
from .scene_renderer import SceneRenderer


class VideoPhaseExecutionMixin:
    def _jobs_count(self) -> int:
        if str(self.jobs).lower() == "auto":
            return self._auto_jobs_count()
        try:
            return max(1, int(self.jobs))
        except (TypeError, ValueError):
            return 1

    def _auto_jobs_count(self) -> int:
        cpu = os.cpu_count() or 1
        if self.hw_encoder == "gpu":
            return max(1, min(3, cpu // 2 or 1))
        if self.hw_encoder == "cpu":
            return max(1, min(2, cpu // 2 or 1))
        return max(1, min(2, cpu // 2 or 1))

    @staticmethod
    def _resolve_effective_hw_kind(
        requested: str, detected: str | None, filter_mode: str
    ) -> str | None:
        if requested == "cpu":
            return None
        if requested == "gpu":
            return detected
        return detected

    async def _preload_scene_assets(
        self, scenes: List[Dict[str, Any]], line_data_map: Dict[str, Dict[str, Any]]
    ) -> None:
        try:
            assets = build_preload_assets(scenes, line_data_map)
            await preload_assets(assets)
        except Exception as exc:
            logger.debug("VideoPhase: asset preload skipped due to error: %s", exc)

    async def _render_one_scene(
        self,
        *,
        index: int,
        scene: Dict[str, Any],
        renderer: VideoRenderer,
        timeline: Timeline,
        line_data_map: Dict[str, Dict[str, Any]],
        semaphore: asyncio.Semaphore,
    ) -> Tuple[int, Path, Dict[str, Any]]:
        scene_id = scene.get("id", f"scene_{index}")
        logger.info(
            "VideoPhase: [%d/%d] Rendering scene '%s'...",
            index + 1,
            len(self.config.get("scenes", [])),
            scene_id,
        )
        async with semaphore:
            ctx = contextvars.copy_context()
            task = asyncio.create_task(
                ctx.run(
                    SceneRenderer(
                        renderer=renderer,
                        cache_manager=self.cache_manager,
                        temp_dir=self.temp_dir,
                        config=self.config,
                        video_params=self.video_params,
                        audio_params=self.audio_params,
                        hw_encoder=self.hw_encoder,
                        quality=self.quality,
                    ).render_scene,
                    scene,
                    index,
                    timeline,
                    line_data_map,
                )
            )
            path, result = await task
        return index, path, result

    async def _render_scene_set(
        self,
        *,
        scenes: List[Dict[str, Any]],
        renderer: VideoRenderer,
        timeline: Timeline,
        line_data_map: Dict[str, Dict[str, Any]],
        workers: int,
    ) -> List[Tuple[int, Path, Dict[str, Any]]]:
        semaphore = asyncio.Semaphore(workers)
        tasks = [
            self._render_one_scene(
                index=index, scene=scene, renderer=renderer, timeline=timeline,
                line_data_map=line_data_map, semaphore=semaphore,
            )
            for index, scene in enumerate(scenes)
        ]
        return list(await asyncio.gather(*tasks))

    def _aggregate_scene_results(
        self,
        results: List[Tuple[int, Path, Dict[str, Any]]],
    ) -> tuple[List[Path], Dict[str, Dict[str, Any]], List[Tuple[int, str]]]:
        ordered = sorted(results, key=lambda item: item[0])
        paths = [item[1] for item in ordered]
        metadata: Dict[str, Dict[str, Any]] = {}
        voicevox: List[Tuple[int, str]] = []
        for _index, _path, result in ordered:
            metadata.update(result.get("line_data", {}))
            voicevox.extend(result.get("used_voicevox_info", []))
        return paths, metadata, voicevox

    async def _build_renderer(self) -> VideoRenderer:
        renderer = VideoRenderer(
            config=self.config,
            cache_manager=self.cache_manager,
            temp_dir=self.temp_dir,
            video_params=self.video_params,
            audio_params=self.audio_params,
            hw_encoder=self.hw_encoder,
            quality=self.quality,
        )
        detected = await renderer.detected_hw_kind()
        filter_mode = get_hw_filter_mode()
        renderer.hw_kind = self._resolve_effective_hw_kind(
            self.hw_encoder, detected, filter_mode
        )
        return renderer
