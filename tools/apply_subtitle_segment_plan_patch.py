"""Connect the pure subtitle segment planner to OverlayMixin once."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OVERLAYS = ROOT / "zundamotion/components/video/overlays.py"


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    text = OVERLAYS.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from .threading import build_ffmpeg_thread_flags\n",
        "from .threading import build_ffmpeg_thread_flags\n"
        "from .subtitle_segment_plan import (\n"
        "    SubtitleRangePlan,\n"
        "    build_subtitle_segment_plan,\n"
        "    merge_subtitle_ranges as plan_merge_subtitle_ranges,\n"
        "    should_use_subtitle_segment_mode as plan_should_use_segment_mode,\n"
        "    split_subtitle_ranges_for_png as plan_split_subtitle_ranges_for_png,\n"
        ")\n",
        label="subtitle segment plan imports",
    )

    decision_start = text.index("    def _should_use_subtitle_segment_mode(\n")
    decision_end = text.index("    def _max_cuda_subtitle_overlays", decision_start)
    decision = '''    def _should_use_subtitle_segment_mode(
        self,
        ranges: List[Dict[str, Any]],
        *,
        base_duration: float,
        gap_threshold: float,
    ) -> bool:
        """Compatibility wrapper around the pure segment-mode decision."""
        planned_ranges = tuple(
            SubtitleRangePlan(
                start=float(item["start"]),
                end=float(item["end"]),
                subtitles=tuple(dict(sub) for sub in item.get("subtitles", [])),
            )
            for item in ranges
        )
        return plan_should_use_segment_mode(
            planned_ranges,
            base_duration=base_duration,
            gap_threshold=gap_threshold,
            min_exact_segment_duration=self._min_exact_segment_duration(),
        )

'''
    text = text[:decision_start] + decision + text[decision_end:]

    merge_start = text.index("    @staticmethod\n    def _merge_subtitle_ranges(\n")
    split_start = text.index("    @classmethod\n    def _split_subtitle_ranges_for_png(\n", merge_start)
    merge_wrapper = '''    @staticmethod
    def _merge_subtitle_ranges(
        subtitles: List[Dict[str, Any]],
        *,
        base_duration: Optional[float],
        gap_threshold: float = 0.20,
    ) -> List[Dict[str, Any]]:
        """Compatibility wrapper around pure range merging."""
        return [
            item.to_legacy_dict()
            for item in plan_merge_subtitle_ranges(
                subtitles,
                base_duration=base_duration,
                gap_threshold=gap_threshold,
            )
        ]

'''
    text = text[:merge_start] + merge_wrapper + text[split_start:]

    split_start = text.index("    @classmethod\n    def _split_subtitle_ranges_for_png(\n")
    cut_start = text.index("    async def _cut_video_segment_exact(\n", split_start)
    split_wrapper = '''    @classmethod
    def _split_subtitle_ranges_for_png(
        cls,
        subtitles: List[Dict[str, Any]],
        *,
        base_duration: Optional[float],
        gap_threshold: float = 0.20,
        max_subtitles: int = 12,
    ) -> List[Dict[str, Any]]:
        """Compatibility wrapper around pure PNG chunk planning."""
        return [
            item.to_legacy_dict()
            for item in plan_split_subtitle_ranges_for_png(
                subtitles,
                base_duration=base_duration,
                gap_threshold=gap_threshold,
                max_subtitles=max_subtitles,
            )
        ]

'''
    text = text[:split_start] + split_wrapper + text[cut_start:]

    plan_start = text.index(
        "            ranges = self._split_subtitle_ranges_for_png(\n",
        text.index("    async def apply_subtitle_overlays(\n"),
    )
    chunks_line = text.index(
        '            self.subtitle_overlay_stats["chunks"] = len(ranges or [])\n',
        plan_start,
    )
    plan_block = '''            segment_plan = build_subtitle_segment_plan(
                subtitles,
                base_duration=float(base_dur),
                gap_threshold=gap_threshold,
                max_subtitles=png_chunk_size,
                min_exact_segment_duration=self._min_exact_segment_duration(),
            )
            if segment_plan.absorbed_leading_gap > 0.0:
                logger.info(
                    "[SubtitleGap] absorbed leading edge duration=%.3f threshold=%.3f",
                    segment_plan.absorbed_leading_gap,
                    self._min_exact_segment_duration(),
                )
            if segment_plan.absorbed_trailing_gap > 0.0:
                logger.info(
                    "[SubtitleGap] absorbed tail edge duration=%.3f threshold=%.3f",
                    segment_plan.absorbed_trailing_gap,
                    self._min_exact_segment_duration(),
                )
            ranges = segment_plan.to_legacy_ranges()
'''
    text = text[:plan_start] + plan_block + text[chunks_line:]

    text = replace_once(
        text,
        '''            if self._should_use_subtitle_segment_mode(
                ranges,
                base_duration=float(base_dur),
                gap_threshold=gap_threshold,
            ):
''',
        '''            if segment_plan.use_segment_mode:
''',
        label="segment mode plan decision",
    )

    if "ranges = self._split_subtitle_ranges_for_png(" in text[
        text.index("    async def apply_subtitle_overlays(\n"):
    ]:
        raise RuntimeError("apply_subtitle_overlays still plans ranges inline")
    if "if self._should_use_subtitle_segment_mode(" in text[
        text.index("    async def apply_subtitle_overlays(\n"):
    ]:
        raise RuntimeError("apply_subtitle_overlays still decides segment mode inline")
    OVERLAYS.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
