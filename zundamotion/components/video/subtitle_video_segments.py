"""Video-only subtitle segment generation, concat, and final mux primitives."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .overlays import _run_ffmpeg


class SubtitleVideoSegmentMixin:
    """Generate and concatenate zero-based CFR video segments without audio."""

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

    def _subtitle_video_thread_flags(
        self,
        worker_count: Optional[int],
    ) -> List[str]:
        """Use the executor's shared budget when a bounded worker count is active."""
        if worker_count is not None:
            resolver = getattr(self, "_subtitle_segment_thread_flags", None)
            if callable(resolver):
                return list(resolver(int(worker_count)))
        return list(self._single_job_thread_flags())

    async def _cut_subtitle_video_segment(
        self,
        base_video: Path,
        output_path: Path,
        *,
        start: float,
        duration: float,
        scene_id: Optional[str] = None,
        segment_index: Optional[int] = None,
        worker_count: Optional[int] = None,
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
        cmd.extend(self._subtitle_video_thread_flags(worker_count))
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
                "subtitle_segment_workers": worker_count,
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
        worker_count: Optional[int] = None,
    ) -> Path:
        """Burn subtitles into a video-only segment without audio mapping."""
        return await self._apply_subtitle_overlays_full(
            base_video,
            subtitles,
            output_path,
            scene_id=scene_id,
            chunk_index=segment_index,
            video_only=True,
            segment_workers=worker_count,
        )

    @staticmethod
    def _escape_ffconcat_path(path: Path) -> str:
        """Escape one absolute path for a single-quoted ffconcat file entry."""
        return str(path.resolve()).replace("'", "'\\''")

    def _write_subtitle_video_concat_list(
        self,
        segment_paths: Sequence[Path],
        *,
        output_path: Path,
    ) -> Path:
        """Write an ffconcat list in caller-supplied segment order."""
        if not segment_paths:
            raise ValueError("subtitle video concat requires at least one segment")
        list_path = self.temp_dir / f"{output_path.stem}_segments.ffconcat"
        list_path.parent.mkdir(parents=True, exist_ok=True)
        lines = ["ffconcat version 1.0"]
        lines.extend(
            f"file '{self._escape_ffconcat_path(Path(path))}'"
            for path in segment_paths
        )
        list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return list_path

    async def _concat_subtitle_video_segments(
        self,
        segment_paths: Sequence[Path],
        output_path: Path,
        *,
        scene_id: Optional[str] = None,
    ) -> Path:
        """Concatenate normalized video-only segments without re-encoding."""
        ordered_paths = tuple(Path(path) for path in segment_paths)
        list_path = self._write_subtitle_video_concat_list(
            ordered_paths,
            output_path=output_path,
        )
        cmd: List[str] = [
            self.ffmpeg_path,
            "-y",
            "-nostdin",
            "-fflags",
            "+genpts",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_path),
        ]
        cmd.extend(self._single_job_thread_flags())
        cmd.extend(
            [
                "-map",
                "0:v:0",
                "-an",
                "-c:v",
                "copy",
                "-avoid_negative_ts",
                "make_zero",
                "-movflags",
                "+faststart",
                str(output_path),
            ]
        )
        await _run_ffmpeg(
            cmd,
            context={
                "phase": "VideoPhase",
                "operation": "subtitle_video_segment_concat",
                "scene_id": scene_id,
                "input_paths": [str(path) for path in ordered_paths],
                "output_path": str(output_path),
            },
        )
        return output_path

    async def _mux_subtitle_video_with_source_audio(
        self,
        video_only_path: Path,
        source_media_path: Path,
        output_path: Path,
        *,
        duration: Optional[float] = None,
        scene_id: Optional[str] = None,
    ) -> Path:
        """Copy the original audio once onto the completed video-only stream."""
        cmd: List[str] = [
            self.ffmpeg_path,
            "-y",
            "-nostdin",
            "-i",
            str(video_only_path),
            "-i",
            str(source_media_path),
        ]
        cmd.extend(self._single_job_thread_flags())
        cmd.extend(
            [
                "-map",
                "0:v:0",
                "-map",
                "1:a?",
                "-c:v",
                "copy",
                "-c:a",
                "copy",
                "-avoid_negative_ts",
                "make_zero",
                "-movflags",
                "+faststart",
            ]
        )
        if duration is not None and float(duration) > 0.0:
            cmd.extend(["-t", f"{float(duration):.6f}"])
        cmd.append(str(output_path))
        await _run_ffmpeg(
            cmd,
            context={
                "phase": "VideoPhase",
                "operation": "subtitle_final_audio_mux",
                "scene_id": scene_id,
                "input_paths": [str(video_only_path), str(source_media_path)],
                "output_path": str(output_path),
            },
        )
        return output_path
