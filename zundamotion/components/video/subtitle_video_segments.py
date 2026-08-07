"""Video-only subtitle segment generation primitives."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from .overlays import _run_ffmpeg


class SubtitleVideoSegmentMixin:
    """Generate zero-based CFR video segments without audio streams."""

    def _subtitle_video_segment_filter(
        self,
        *,
        start: float,
        duration: float,
    ) -> str:
        """Return the canonical trim/fps/timebase filter for one segment."""
        fps = max(
            1,
            int(getattr(getattr(self, "video_params", None), "fps", 30) or 30),
        )
        return (
            f"[0:v]trim=start={float(start):.6f}:duration={float(duration):.6f},"
            "setpts=PTS-STARTPTS,"
            f"fps={fps},"
            f"settb=expr=1/{fps},"
            "setpts=N[v]"
        )

    async def _cut_subtitle_video_segment(
        self,
        base_video: Path,
        output_path: Path,
        *,
        start: float,
        duration: float,
        scene_id: Optional[str] = None,
        segment_index: Optional[int] = None,
    ) -> Optional[Path]:
        """Encode one exact video-only interval with normalized timestamps."""
        if duration <= self._min_exact_segment_duration():
            return None

        cmd: List[str] = [
            self.ffmpeg_path,
            "-y",
            "-nostdin",
            "-i",
            str(base_video),
        ]
        cmd.extend(self._single_job_thread_flags())
        cmd.extend(
            [
                "-filter_complex",
                self._subtitle_video_segment_filter(
                    start=start,
                    duration=duration,
                ),
                "-map",
                "[v]",
                "-an",
            ]
        )
        cmd.extend(self.video_params.to_ffmpeg_opts(self.hw_kind))
        cmd.extend(
            [
                "-t",
                f"{float(duration):.6f}",
                "-avoid_negative_ts",
                "make_zero",
                str(output_path),
            ]
        )
        await _run_ffmpeg(
            cmd,
            context={
                "phase": "VideoPhase",
                "operation": "subtitle_video_segment_cut",
                "scene_id": scene_id,
                "segment_index": segment_index,
                "input_paths": [str(base_video)],
                "output_path": str(output_path),
            },
        )
        return output_path

    async def _burn_subtitle_video_segment(
        self,
        base_video: Path,
        subtitles: List[Dict[str, Any]],
        output_path: Path,
        *,
        scene_id: Optional[str] = None,
        segment_index: Optional[int] = None,
    ) -> Path:
        """Burn subtitles into a video-only segment without audio mapping."""
        return await self._apply_subtitle_overlays_full(
            base_video,
            subtitles,
            output_path,
            scene_id=scene_id,
            chunk_index=segment_index,
            video_only=True,
        )
