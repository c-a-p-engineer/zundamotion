"""Bounded execution for planned subtitle video segments."""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from ...utils import perf_stats
from ...utils.logger import logger
from .subtitle_segment_plan import SubtitleSegment, SubtitleSegmentPlan
from .threading import build_ffmpeg_thread_flags


@dataclass(frozen=True)
class SubtitleSegmentExecutionResult:
    """Ordered video-only outputs produced from one subtitle segment plan."""

    paths: tuple[Path, ...]
    worker_count: int
    gap_segments: int
    subtitle_segments: int
    ffmpeg_calls: int


class SubtitleSegmentExecutorMixin:
    """Execute subtitle segments with bounded concurrency and stable ordering."""

    @staticmethod
    def _subtitle_segment_worker_count() -> int:
        """Return the experimental bounded worker count (1 or 2, default 1)."""
        raw = str(os.getenv("ZUNDAMOTION_SUBTITLE_SEGMENT_WORKERS", "1") or "1").strip()
        try:
            value = int(raw)
        except ValueError:
            value = 1
        if value not in {1, 2}:
            logger.warning(
                "[SubtitleExecutor] Unsupported worker count=%s; using 1",
                raw,
            )
            return 1
        return value

    def _subtitle_segment_thread_flags(self, worker_count: int) -> list[str]:
        """Split the existing FFmpeg thread budget across concurrent chunks."""
        return build_ffmpeg_thread_flags(
            getattr(self, "jobs", "0"),
            max(1, int(worker_count)),
            getattr(self, "hw_kind", None),
        )

    @staticmethod
    def _adjust_subtitles_for_segment(segment: SubtitleSegment) -> list[dict]:
        adjusted: list[dict] = []
        for subtitle in segment.subtitles:
            copied = dict(subtitle)
            copied["start"] = max(
                0.0,
                float(subtitle.get("start", 0.0) or 0.0) - float(segment.start),
            )
            adjusted.append(copied)
        return adjusted

    async def _render_one_subtitle_segment(
        self,
        base_video: Path,
        segment: SubtitleSegment,
        *,
        scene_id: str,
        segment_index: int,
        worker_count: int,
        subtitle_chunk_count: int,
    ) -> Path:
        duration = float(segment.duration)
        if segment.kind == "gap":
            output_path = self.temp_dir / (
                f"{base_video.stem}_sub_gap_v_{segment_index:03d}.mp4"
            )
            result = await self._cut_subtitle_video_segment(
                base_video,
                output_path,
                start=float(segment.start),
                duration=duration,
                scene_id=scene_id,
                segment_index=segment_index,
                worker_count=worker_count,
            )
            if result is None:
                raise RuntimeError(
                    "planned subtitle gap was below the exact segment threshold"
                )
            return result

        segment_base = self.temp_dir / (
            f"{base_video.stem}_sub_base_v_{segment_index:03d}.mp4"
        )
        cut = await self._cut_subtitle_video_segment(
            base_video,
            segment_base,
            start=float(segment.start),
            duration=duration,
            scene_id=scene_id,
            segment_index=segment_index,
            worker_count=worker_count,
        )
        if cut is None:
            raise RuntimeError(
                "planned subtitle chunk was below the exact segment threshold"
            )

        adjusted = self._adjust_subtitles_for_segment(segment)
        burn_path = self.temp_dir / (
            f"{base_video.stem}_sub_burn_v_{segment_index:03d}.mp4"
        )
        started = time.perf_counter()
        burned = await self._burn_subtitle_video_segment(
            cut,
            adjusted,
            burn_path,
            scene_id=scene_id,
            segment_index=segment_index,
            worker_count=worker_count,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        perf_stats.add_ms("subtitle_burn_ms", elapsed_ms)
        current_perf = perf_stats.current_perf_stats()
        if current_perf is not None:
            current_perf.record_subtitle_burn_chunk(
                scene_id=scene_id,
                chunk_index=int(segment.range_index or 0),
                chunk_count=subtitle_chunk_count,
                subtitle_count=len(adjusted),
                input_video_duration=duration,
                burn_duration_ms=elapsed_ms,
                output_path=str(burned),
                ffmpeg_call_count=2,
                start_time=float(segment.start),
                end_time=float(segment.end),
            )
        logger.info(
            "[SubtitleChunk] index=%d subtitles=%d duration=%.3f ffmpeg_ms=%.1f workers=%d",
            int(segment.range_index or 0) + 1,
            len(adjusted),
            duration,
            elapsed_ms,
            worker_count,
        )
        return burned

    async def _execute_subtitle_segment_plan(
        self,
        base_video: Path,
        plan: SubtitleSegmentPlan,
        *,
        scene_id: str,
        worker_count: Optional[int] = None,
    ) -> SubtitleSegmentExecutionResult:
        """Render all planned segments with fail-fast cancellation and stable order."""
        workers = (
            self._subtitle_segment_worker_count()
            if worker_count is None
            else max(1, min(2, int(worker_count)))
        )
        segments: Sequence[SubtitleSegment] = tuple(plan.segments)
        if not segments:
            raise ValueError("subtitle segment execution requires at least one segment")

        subtitle_count = sum(1 for item in segments if item.kind == "subtitle")
        gap_count = sum(1 for item in segments if item.kind == "gap")
        semaphore = asyncio.Semaphore(workers)

        async def run_one(index: int, segment: SubtitleSegment) -> Path:
            async with semaphore:
                return await self._render_one_subtitle_segment(
                    base_video,
                    segment,
                    scene_id=scene_id,
                    segment_index=index,
                    worker_count=workers,
                    subtitle_chunk_count=subtitle_count,
                )

        tasks = [
            asyncio.create_task(run_one(index, segment))
            for index, segment in enumerate(segments)
        ]
        try:
            ordered_paths = await asyncio.gather(*tasks)
        except Exception:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

        ffmpeg_calls = gap_count + (subtitle_count * 2)
        logger.info(
            "[SubtitleExecutor] scene=%s workers=%d segments=%d subtitle=%d gap=%d ffmpeg_calls=%d",
            scene_id,
            workers,
            len(segments),
            subtitle_count,
            gap_count,
            ffmpeg_calls,
        )
        return SubtitleSegmentExecutionResult(
            paths=tuple(ordered_paths),
            worker_count=workers,
            gap_segments=gap_count,
            subtitle_segments=subtitle_count,
            ffmpeg_calls=ffmpeg_calls,
        )

    async def _render_subtitle_segment_pipeline(
        self,
        base_video: Path,
        plan: SubtitleSegmentPlan,
        output_path: Path,
        *,
        base_duration: float,
        scene_id: str,
        worker_count: Optional[int] = None,
    ) -> Path:
        """Execute video-only segments, concat them, then copy source audio once."""
        execution = await self._execute_subtitle_segment_plan(
            base_video,
            plan,
            scene_id=scene_id,
            worker_count=worker_count,
        )
        video_only = self.temp_dir / f"{base_video.stem}_sub_video_concat.mp4"
        await self._concat_subtitle_video_segments(
            execution.paths,
            video_only,
            scene_id=scene_id,
        )
        result = await self._mux_subtitle_video_with_source_audio(
            video_only,
            base_video,
            output_path,
            duration=float(base_duration),
            scene_id=scene_id,
        )
        logger.info(
            "[SubtitleExecutor] scene=%s final_mux=success workers=%d segment_ffmpeg_calls=%d",
            scene_id,
            execution.worker_count,
            execution.ffmpeg_calls,
        )
        return result
