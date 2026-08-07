"""Subtitle segment boundary safety for very short edge gaps."""

from __future__ import annotations

from typing import Any, Dict, List

from ...utils.logger import logger
from .subtitle_segment_plan import (
    SubtitleRangePlan,
    absorb_unrenderable_edge_gaps,
)


MIN_SAFE_EXACT_SEGMENT_FRAMES = 4.0
MIN_SAFE_EXACT_SEGMENT_SECONDS = 0.05


class SubtitleTailSafetyMixin:
    """Prevent exact-cut attempts that contain too few video frames.

    FFmpeg may report a positive container duration at the end of a scene even
    when that interval has too few decodable frames to open the encoder. Such
    intervals are included in the adjacent subtitle chunk instead of becoming a
    standalone gap file.
    """

    def _min_exact_segment_duration(self) -> float:
        params = getattr(self, "video_params", None)
        try:
            fps = float(getattr(params, "fps", 30.0) or 30.0)
        except (TypeError, ValueError):
            fps = 30.0
        fps = max(1.0, fps)
        return max(
            MIN_SAFE_EXACT_SEGMENT_SECONDS,
            MIN_SAFE_EXACT_SEGMENT_FRAMES / fps,
        )

    def _absorb_unrenderable_subtitle_edge_gaps(
        self,
        ranges: List[Dict[str, Any]],
        *,
        base_duration: float,
    ) -> List[Dict[str, Any]]:
        """Apply the pure edge plan back to the legacy mutable range list."""
        if not ranges:
            return ranges

        planned = tuple(
            SubtitleRangePlan(
                start=float(item.get("start", 0.0) or 0.0),
                end=float(item.get("end", 0.0) or 0.0),
                subtitles=tuple(
                    dict(subtitle)
                    for subtitle in item.get("subtitles", [])
                    if isinstance(subtitle, dict)
                ),
            )
            for item in ranges
        )
        adjusted, leading_gap, trailing_gap = absorb_unrenderable_edge_gaps(
            planned,
            base_duration=base_duration,
            min_exact_segment_duration=self._min_exact_segment_duration(),
        )
        for target, item in zip(ranges, adjusted):
            target["start"] = item.start
            target["end"] = item.end

        threshold = self._min_exact_segment_duration()
        if leading_gap > 0.0:
            logger.info(
                "[SubtitleGap] absorbed leading edge duration=%.3f threshold=%.3f",
                leading_gap,
                threshold,
            )
        if trailing_gap > 0.0:
            logger.info(
                "[SubtitleGap] absorbed tail edge duration=%.3f threshold=%.3f",
                trailing_gap,
                threshold,
            )
        return ranges

    def _should_use_subtitle_segment_mode(
        self,
        ranges: List[Dict[str, Any]],
        *,
        base_duration: float,
        gap_threshold: float,
    ) -> bool:
        self._absorb_unrenderable_subtitle_edge_gaps(
            ranges,
            base_duration=base_duration,
        )
        return super()._should_use_subtitle_segment_mode(
            ranges,
            base_duration=base_duration,
            gap_threshold=gap_threshold,
        )
