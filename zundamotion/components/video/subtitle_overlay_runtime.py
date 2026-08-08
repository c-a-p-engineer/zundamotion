"""Subtitle overlay mode selection and execution mixin."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ...utils import perf_stats
from ...utils.ffmpeg_probe import get_media_duration
from ...utils.logger import logger
from .subtitle_overlay_execution import (
    execute_simple_subtitle_job,
    execute_subtitle_burn,
)
from .subtitle_overlay_graph import build_subtitle_burn_command
from .subtitle_segment_plan import build_subtitle_segment_plan


class SubtitleOverlayRuntimeMixin:
    """Production subtitle-overlay methods overriding the legacy monolith."""

    def _init_subtitle_overlay_stats(
        self, mode: str, subtitles: List[Dict[str, Any]]
    ) -> None:
        self.subtitle_overlay_stats = {
            "mode": mode,
            "subtitles": len(subtitles),
            "chunks": 0,
            "png_chunk_size": None,
            "base_duration": None,
            "layer_video_attempted": False,
            "layer_video_used": False,
        }

    async def _subtitle_base_duration(self, base_video: Path) -> Optional[float]:
        try:
            return await get_media_duration(
                str(base_video), caller="subtitle_base_duration"
            )
        except Exception:
            return None

    async def _try_subtitle_layer_video(
        self,
        base_video: Path,
        subtitles: List[Dict[str, Any]],
        output_path: Path,
        *,
        base_duration: Optional[float],
        mode: str,
    ) -> Optional[Path]:
        enabled = bool((getattr(self, "video_config", {}) or {}).get("subtitle_layer_video", False))
        if mode != "png" or not base_duration or not enabled:
            return None
        self.subtitle_overlay_stats["layer_video_attempted"] = True
        logger.info(
            "[SubtitleOverlay] Layer-video mode: generating transparent subtitle layer (%d subtitles, base=%.2fs)",
            len(subtitles),
            float(base_duration),
        )
        try:
            layer = await self._render_subtitle_layer_video(
                subtitles,
                duration=float(base_duration),
                output_path=self.temp_dir / f"{base_video.stem}_subtitle_layer.mov",
            )
            self.subtitle_overlay_stats["layer_video_used"] = True
            self.subtitle_overlay_stats_history.append(dict(self.subtitle_overlay_stats))
            return await self._overlay_subtitle_layer_video(
                base_video, layer, output_path, duration=float(base_duration)
            )
        except Exception as err:
            logger.warning(
                "[SubtitleOverlay] Layer-video mode failed (%s). Falling back to default burn.",
                err,
            )
            return None

    def _build_segment_plan(
        self,
        subtitles: List[Dict[str, Any]],
        base_duration: float,
    ):
        gap_threshold = float(
            (self.subtitle_gen.subtitle_config or {}).get("copy_gap_threshold", 0.20)
        )
        chunk_size = self._subtitle_png_chunk_size(
            subtitles, base_duration=base_duration
        )
        self.subtitle_overlay_stats["png_chunk_size"] = chunk_size
        return build_subtitle_segment_plan(
            subtitles,
            base_duration=base_duration,
            gap_threshold=gap_threshold,
            max_subtitles=chunk_size,
            min_exact_segment_duration=self._min_exact_segment_duration(),
        )

    def _log_segment_plan(
        self,
        subtitles: List[Dict[str, Any]],
        base_duration: float,
        plan: Any,
    ) -> None:
        threshold = self._min_exact_segment_duration()
        if plan.absorbed_leading_gap > 0.0:
            logger.info(
                "[SubtitleGap] absorbed leading edge duration=%.3f threshold=%.3f",
                plan.absorbed_leading_gap, threshold,
            )
        if plan.absorbed_trailing_gap > 0.0:
            logger.info(
                "[SubtitleGap] absorbed tail edge duration=%.3f threshold=%.3f",
                plan.absorbed_trailing_gap, threshold,
            )
        ranges = plan.to_legacy_ranges()
        self.subtitle_overlay_stats["chunks"] = len(ranges or [])
        stats = self._subtitle_timing_stats(subtitles, base_duration)
        logger.info(
            "[SubtitleChunk] subtitles=%d chunk_size=%d chunk_count=%d density=%.3f_per_s total_gap=%.3f longest_zone=%.3f",
            len(subtitles), self.subtitle_overlay_stats["png_chunk_size"],
            len(ranges or []), stats["density"], stats["gap_duration"], stats["longest_zone"],
        )

    async def _try_segment_pipeline(
        self,
        base_video: Path,
        subtitles: List[Dict[str, Any]],
        output_path: Path,
        *,
        base_duration: Optional[float],
        mode: str,
        scene_id: str,
    ) -> Optional[Path]:
        if mode != "png" or not base_duration or len(subtitles) < 2:
            return None
        plan = self._build_segment_plan(subtitles, float(base_duration))
        self._log_segment_plan(subtitles, float(base_duration), plan)
        if not plan.use_segment_mode:
            return None
        if len(plan.ranges) <= 1:
            logger.info(
                "[SubtitleOverlay] Single-chunk segment plan uses full burn to preserve CFR/timestamp stability (base=%.2fs, subtitles=%d)",
                float(base_duration), len(subtitles),
            )
            return None
        return await self._execute_segment_plan(
            base_video, subtitles, output_path,
            base_duration=float(base_duration), scene_id=scene_id, plan=plan,
        )

    async def _execute_segment_plan(
        self,
        base_video: Path,
        subtitles: List[Dict[str, Any]],
        output_path: Path,
        *,
        base_duration: float,
        scene_id: str,
        plan: Any,
    ) -> Optional[Path]:
        perf_stats.incr("subtitle_chunks", len(plan.ranges))
        workers = self._subtitle_segment_worker_count()
        self.subtitle_overlay_stats["segment_workers"] = workers
        logger.info(
            "[SubtitleOverlay] Segment mode: video-only chunks=%d segments=%d workers=%d (base=%.2fs, subtitles=%d, png_chunk_size=%d)",
            len(plan.ranges), len(plan.segments), workers, base_duration,
            len(subtitles), self.subtitle_overlay_stats["png_chunk_size"],
        )
        try:
            result = await self._render_subtitle_segment_pipeline(
                base_video, plan, output_path, base_duration=base_duration,
                scene_id=scene_id, worker_count=workers,
            )
            self.subtitle_overlay_stats_history.append(dict(self.subtitle_overlay_stats))
            return result
        except Exception as err:
            logger.warning(
                "[SubtitleOverlay] Video-only segment pipeline failed (%s). Falling back to full subtitle burn.",
                err,
            )
            return None

    async def _full_subtitle_burn(
        self,
        base_video: Path,
        subtitles: List[Dict[str, Any]],
        output_path: Path,
        *,
        base_duration: Optional[float],
        scene_id: str,
    ) -> Path:
        self.subtitle_overlay_stats["chunks"] = 1
        perf_stats.incr("subtitle_chunks", 1)
        started = time.perf_counter()
        result = await self._apply_subtitle_overlays_full(
            base_video, subtitles, output_path, scene_id=scene_id, chunk_index=0
        )
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        perf_stats.add_ms("subtitle_burn_ms", elapsed_ms)
        current = perf_stats.current_perf_stats()
        if current is not None:
            current.record_subtitle_burn_chunk(
                scene_id=scene_id, chunk_index=0, chunk_count=1,
                subtitle_count=len(subtitles), input_video_duration=float(base_duration or 0.0),
                burn_duration_ms=elapsed_ms, output_path=str(result), ffmpeg_call_count=1,
                start_time=0.0, end_time=float(base_duration or 0.0),
            )
        self.subtitle_overlay_stats_history.append(dict(self.subtitle_overlay_stats))
        return result

    async def apply_subtitle_overlays(
        self,
        base_video: Path,
        subtitles: List[Dict[str, Any]],
        *,
        scene_id: Optional[str] = None,
    ) -> Path:
        if not subtitles:
            return base_video
        output_path = self.temp_dir / f"{base_video.stem}_sub.mp4"
        resolved_scene_id = str(scene_id or base_video.stem)
        mode = self._subtitle_render_mode(subtitles)
        self._init_subtitle_overlay_stats(mode, subtitles)
        base_duration = await self._subtitle_base_duration(base_video)
        self.subtitle_overlay_stats["base_duration"] = base_duration
        layer_result = await self._try_subtitle_layer_video(
            base_video, subtitles, output_path,
            base_duration=base_duration, mode=mode,
        )
        if layer_result is not None:
            return layer_result
        segment_result = await self._try_segment_pipeline(
            base_video, subtitles, output_path, base_duration=base_duration,
            mode=mode, scene_id=resolved_scene_id,
        )
        if segment_result is not None:
            return segment_result
        return await self._full_subtitle_burn(
            base_video, subtitles, output_path, base_duration=base_duration,
            scene_id=resolved_scene_id,
        )

    async def _apply_subtitle_overlays_full(
        self,
        base_video: Path,
        subtitles: List[Dict[str, Any]],
        output_path: Path,
        *,
        scene_id: Optional[str] = None,
        chunk_index: Optional[int] = None,
        video_only: bool = False,
        segment_workers: Optional[int] = None,
    ) -> Path:
        try:
            base_duration = await get_media_duration(
                str(base_video), caller="subtitle_chunk_duration"
            )
        except Exception:
            base_duration = None
        built = await build_subtitle_burn_command(
            self, base_video=base_video, subtitles=subtitles,
            output_path=output_path, base_duration=base_duration,
            video_only=video_only, segment_workers=segment_workers,
        )
        return await execute_subtitle_burn(
            cmd=built.argv, base_video=base_video, output_path=output_path,
            scene_id=scene_id, chunk_index=chunk_index,
        )

    async def _render_subtitle_layer_video(
        self,
        subtitles: List[Dict[str, Any]],
        *,
        duration: float,
        output_path: Path,
    ) -> Path:
        cmd, previous, parts = self._subtitle_layer_base_command(duration)
        for index, subtitle in enumerate(subtitles, start=1):
            extra, snippet = await self.subtitle_gen.build_subtitle_overlay(
                subtitle["text"], subtitle["duration"], subtitle.get("line_config", {}),
                in_label=previous.strip("[]"), index=index, force_cpu=True, allow_cuda=False,
            )
            for key, value in extra.items():
                cmd.extend([key, value])
            start = float(subtitle["start"])
            end = start + float(subtitle["duration"])
            parts.append(snippet.replace(
                f"between(t,0,{subtitle['duration']})", f"between(t,{start},{end})"
            ))
            previous = f"[with_subtitle_{index}]"
        cmd.extend(self._single_job_thread_flags())
        cmd.extend(["-filter_complex", ";".join(parts), "-map", previous])
        cmd.extend(["-an", "-c:v", "qtrle", "-pix_fmt", "argb", "-t", f"{duration:.3f}", str(output_path)])
        return await execute_simple_subtitle_job(cmd, output_path)

    def _subtitle_layer_base_command(self, duration: float):
        params = self.video_params
        command = [
            self.ffmpeg_path, "-y", "-nostdin", "-f", "lavfi", "-i",
            f"color=c=black@0.0:s={int(params.width)}x{int(params.height)}:r={int(params.fps)}:d={duration:.3f},format=rgba",
        ]
        return command, "[0:v]", []

    async def _overlay_subtitle_layer_video(
        self,
        base_video: Path,
        layer_video: Path,
        output_path: Path,
        *,
        duration: float,
    ) -> Path:
        cmd = [
            self.ffmpeg_path, "-y", "-nostdin", "-i", str(base_video),
            "-i", str(layer_video), *self._single_job_thread_flags(),
            "-filter_complex", "[0:v][1:v]overlay=0:0:format=auto[final_v]",
            "-map", "[final_v]", "-map", "0:a?",
        ]
        cmd.extend(self._subtitle_burn_video_opts("png"))
        cmd.extend(["-c:a", "copy", "-t", f"{duration:.3f}", str(output_path)])
        return await execute_simple_subtitle_job(cmd, output_path)
