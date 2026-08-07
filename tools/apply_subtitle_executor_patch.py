"""Connect the bounded subtitle segment executor to the existing overlay path."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OVERLAYS = ROOT / "zundamotion/components/video/overlays.py"
SEGMENT_TEST = ROOT / "tests/test_subtitle_video_segments.py"


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def patch_overlays() -> None:
    text = OVERLAYS.read_text(encoding="utf-8")
    text = text.replace(
        "from ...utils.ffmpeg_ops import concat_videos_safe\n",
        "",
        1,
    )

    segment_start = text.index("            if segment_plan.use_segment_mode:\n")
    fallback_start = text.index(
        '        self.subtitle_overlay_stats["chunks"] = 1\n',
        segment_start,
    )
    replacement = '''            if segment_plan.use_segment_mode:
                perf_stats.incr("subtitle_chunks", len(segment_plan.ranges))
                worker_count = self._subtitle_segment_worker_count()
                self.subtitle_overlay_stats["segment_workers"] = worker_count
                logger.info(
                    "[SubtitleOverlay] Segment mode: video-only chunks=%d segments=%d workers=%d "
                    "(base=%.2fs, subtitles=%d, png_chunk_size=%d)",
                    len(segment_plan.ranges),
                    len(segment_plan.segments),
                    worker_count,
                    float(base_dur),
                    len(subtitles),
                    png_chunk_size,
                )
                try:
                    result = await self._render_subtitle_segment_pipeline(
                        base_video,
                        segment_plan,
                        output_path,
                        base_duration=float(base_dur),
                        scene_id=resolved_scene_id,
                        worker_count=worker_count,
                    )
                    self.subtitle_overlay_stats_history.append(
                        dict(self.subtitle_overlay_stats)
                    )
                    return result
                except Exception as err:
                    logger.warning(
                        "[SubtitleOverlay] Video-only segment pipeline failed (%s). "
                        "Falling back to full subtitle burn.",
                        err,
                    )

'''
    text = text[:segment_start] + replacement + text[fallback_start:]

    method_start = text.index("    async def _apply_subtitle_overlays_full(\n")
    method_text = text[method_start:]
    method_text = replace_once(
        method_text,
        """        chunk_index: Optional[int] = None,
        video_only: bool = False,
    ) -> Path:
""",
        """        chunk_index: Optional[int] = None,
        video_only: bool = False,
        segment_workers: Optional[int] = None,
    ) -> Path:
""",
        label="segment worker argument",
    )
    first_thread_call = method_text.index("        cmd.extend(self._single_job_thread_flags())\n")
    method_text = (
        method_text[:first_thread_call]
        + '''        if segment_workers is None:
            cmd.extend(self._single_job_thread_flags())
        else:
            cmd.extend(self._subtitle_segment_thread_flags(segment_workers))
'''
        + method_text[first_thread_call + len("        cmd.extend(self._single_job_thread_flags())\n") :]
    )
    text = text[:method_start] + method_text

    if "concat_videos_safe(" in text:
        raise RuntimeError("legacy subtitle concat call remains")
    if "_cut_video_segment_exact(" in text[segment_start:fallback_start]:
        raise RuntimeError("legacy A/V segment cut remains in active segment path")
    OVERLAYS.write_text(text, encoding="utf-8")


def patch_existing_segment_test() -> None:
    text = SEGMENT_TEST.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '''    assert kwargs == {
        "scene_id": "scene-a",
        "chunk_index": 2,
        "video_only": True,
    }
''',
        '''    assert kwargs == {
        "scene_id": "scene-a",
        "chunk_index": 2,
        "video_only": True,
        "segment_workers": None,
    }
''',
        label="existing video-only burn contract",
    )
    SEGMENT_TEST.write_text(text, encoding="utf-8")


def main() -> None:
    patch_overlays()
    patch_existing_segment_test()


if __name__ == "__main__":
    main()
