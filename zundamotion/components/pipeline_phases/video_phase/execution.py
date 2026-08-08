"""Scene execution, ordered aggregation, and VideoPhase diagnostics."""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

from tqdm import tqdm

from zundamotion.timeline import Timeline
from zundamotion.utils.logger import logger

from .scene_renderer import SceneRenderer


class VideoPhaseExecutionMixin:
    async def _render_one_scene(
        self,
        *,
        scene_idx: int,
        scene: Dict[str, Any],
        total_scenes: int,
        line_data_map: Dict[str, Dict[str, Any]],
        timeline: Timeline,
        pbar_scenes: Any,
    ) -> List[Path]:
        scene_renderer = SceneRenderer(
            phase=self,
            scene=scene,
            scene_hash_data=self._generate_scene_hash(scene),
            scene_idx=scene_idx,
            total_scenes=total_scenes,
            line_data_map=line_data_map,
            timeline=timeline,
            pbar_scenes=pbar_scenes,
        )
        return await scene_renderer.render_scene()

    async def _render_parallel_scenes(
        self,
        scenes: List[Dict[str, Any]],
        line_data_map: Dict[str, Dict[str, Any]],
        timeline: Timeline,
        pbar_scenes: Any,
    ) -> List[Path]:
        semaphore = asyncio.Semaphore(self.scene_workers)
        scene_results: List[List[Path]] = [[] for _ in scenes]
        total_scenes = len(scenes)

        async def _render_one(scene_idx: int, scene: Dict[str, Any]) -> None:
            async with semaphore:
                scene_results[scene_idx] = await self._render_one_scene(
                    scene_idx=scene_idx,
                    scene=scene,
                    total_scenes=total_scenes,
                    line_data_map=line_data_map,
                    timeline=timeline,
                    pbar_scenes=pbar_scenes,
                )

        await asyncio.gather(
            *(_render_one(scene_idx, scene) for scene_idx, scene in enumerate(scenes))
        )
        return [clip for scene_clips in scene_results for clip in scene_clips]

    async def _render_serial_scenes(
        self,
        scenes: List[Dict[str, Any]],
        line_data_map: Dict[str, Dict[str, Any]],
        timeline: Timeline,
        pbar_scenes: Any,
    ) -> List[Path]:
        clips: List[Path] = []
        total_scenes = len(scenes)
        for scene_idx, scene in enumerate(scenes):
            clips.extend(
                await self._render_one_scene(
                    scene_idx=scene_idx,
                    scene=scene,
                    total_scenes=total_scenes,
                    line_data_map=line_data_map,
                    timeline=timeline,
                    pbar_scenes=pbar_scenes,
                )
            )
        return clips

    def _log_clip_diagnostics(self) -> None:
        try:
            if not self._clip_samples_all:
                return
            topn = sorted(
                self._clip_samples_all,
                key=lambda sample: float(sample.get("elapsed", 0.0)),
                reverse=True,
            )[:5]
            logger.info("[Diagnostics] Slowest line clips (top 5):")
            for sample in topn:
                logger.info(
                    "  Scene=%s Line=%s Elapsed=%.2fs subtitle=%s chars=%s insert_img=%s bg_video=%s",
                    sample.get("scene"),
                    sample.get("line"),
                    float(sample.get("elapsed", 0.0)),
                    bool(sample.get("subtitle")),
                    bool(sample.get("chars")),
                    bool(sample.get("insert_img")),
                    bool(sample.get("is_bg_video")),
                )
        except Exception:
            pass

    def _log_renderer_diagnostics(self) -> None:
        try:
            stats = getattr(self.video_renderer, "path_counters", None)
            if isinstance(stats, dict):
                logger.info(
                    "[Diagnostics] Filter path usage: cuda_overlay=%s, opencl_overlay=%s, gpu_scale_only=%s, cpu=%s",
                    stats.get("cuda_overlay", 0),
                    stats.get("opencl_overlay", 0),
                    stats.get("gpu_scale_only", 0),
                    stats.get("cpu", 0),
                )
        except Exception:
            pass
        try:
            subtitle_stats = getattr(self.video_renderer, "subtitle_overlay_stats", None)
            if isinstance(subtitle_stats, dict):
                logger.info(
                    "[Diagnostics] Subtitle overlay: mode=%s, subtitles=%s, chunks=%s, png_chunk_size=%s, base=%.2fs, layer_attempted=%s, layer_used=%s",
                    subtitle_stats.get("mode", "none"),
                    subtitle_stats.get("subtitles", 0),
                    subtitle_stats.get("chunks", 0),
                    subtitle_stats.get("png_chunk_size"),
                    float(subtitle_stats.get("base_duration") or 0.0),
                    bool(subtitle_stats.get("layer_video_attempted")),
                    bool(subtitle_stats.get("layer_video_used")),
                )
        except Exception:
            pass

    @staticmethod
    def _resync_timeline(
        timeline: Timeline,
        scenes: List[Dict[str, Any]],
        line_data_map: Dict[str, Dict[str, Any]],
    ) -> None:
        try:
            timeline.resync_with_scene_durations(scenes, line_data_map)
        except Exception as exc:
            logger.warning(
                "VideoPhase: failed to resync timeline with rendered durations: %s",
                exc,
            )

    async def _run_video_phase(
        self,
        scenes: List[Dict[str, Any]],
        line_data_map: Dict[str, Dict[str, Any]],
        timeline: Timeline,
    ) -> List[Path]:
        started_at = time.time()
        logger.info(
            "VideoPhase started. clip_workers=%s, scene_workers=%s, hw_kind=%s",
            self.clip_workers,
            self.scene_workers,
            self.hw_kind,
        )
        self._apply_initial_worker_backoff(scenes)
        self.parallel_scene_rendering = self.scene_workers > 1
        if self.parallel_scene_rendering and self.auto_tune_enabled:
            logger.info("VideoPhase: disabling auto_tune during parallel scene rendering.")

        with tqdm(
            total=len(scenes),
            desc="Scene Rendering",
            unit="scene",
            leave=False,
            disable=(os.getenv("TQDM_DISABLE") == "1" or not sys.stderr.isatty()),
        ) as pbar_scenes:
            if self.parallel_scene_rendering:
                all_clips = await self._render_parallel_scenes(
                    scenes, line_data_map, timeline, pbar_scenes
                )
            else:
                all_clips = await self._render_serial_scenes(
                    scenes, line_data_map, timeline, pbar_scenes
                )

        try:
            tqdm.write("", file=sys.stderr)
        except Exception:
            pass
        logger.info("VideoPhase completed in %.2f seconds.", time.time() - started_at)
        self._log_clip_diagnostics()
        self._log_renderer_diagnostics()
        self._resync_timeline(timeline, scenes, line_data_map)
        return all_clips
