"""Subtitle segment boundary safety for very short edge gaps."""

from __future__ import annotations

from typing import Any, Dict, List

from ...utils.logger import logger


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
        """Mutate range edges so short edge gaps are never exact-cut."""
        if not ranges:
            return ranges

        threshold = self._min_exact_segment_duration()
        first_start = max(0.0, float(ranges[0].get("start", 0.0) or 0.0))
        if 0.0 < first_start <= threshold:
            ranges[0]["start"] = 0.0
            logger.info(
                "[SubtitleGap] absorbed leading edge duration=%.3f threshold=%.3f",
                first_start,
                threshold,
            )

        last_end = max(0.0, float(ranges[-1].get("end", 0.0) or 0.0))
        trailing_gap = max(0.0, float(base_duration) - last_end)
        if 0.0 < trailing_gap <= threshold:
            ranges[-1]["end"] = float(base_duration)
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
