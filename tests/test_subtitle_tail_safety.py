from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from zundamotion.components.video.subtitle_tail_safety import SubtitleTailSafetyMixin


class _SegmentDecisionBase:
    def _should_use_subtitle_segment_mode(
        self,
        ranges: List[Dict[str, Any]],
        *,
        base_duration: float,
        gap_threshold: float,
    ) -> bool:
        self.observed_ranges = ranges
        return len(ranges) > 1


class _Subject(SubtitleTailSafetyMixin, _SegmentDecisionBase):
    def __init__(self, fps: float) -> None:
        self.video_params = SimpleNamespace(fps=fps)
        self.observed_ranges: List[Dict[str, Any]] = []


def _ranges(*, start: float = 0.0, end: float = 9.9) -> List[Dict[str, Any]]:
    return [
        {
            "start": start,
            "end": 4.0,
            "subtitles": [{"start": start, "duration": 1.0}],
        },
        {
            "start": 4.0,
            "end": end,
            "subtitles": [{"start": 4.0, "duration": 1.0}],
        },
    ]


def test_exact_segment_threshold_requires_four_frames_at_30fps() -> None:
    subject = _Subject(30.0)
    assert subject._min_exact_segment_duration() == pytest.approx(4.0 / 30.0)


def test_130ms_tail_is_absorbed_at_30fps() -> None:
    subject = _Subject(30.0)
    ranges = _ranges(end=9.87)

    assert subject._should_use_subtitle_segment_mode(
        ranges,
        base_duration=10.0,
        gap_threshold=0.2,
    )
    assert ranges[-1]["end"] == pytest.approx(10.0)
    assert subject.observed_ranges[-1]["end"] == pytest.approx(10.0)


def test_renderable_tail_is_left_for_exact_gap_copy() -> None:
    subject = _Subject(30.0)
    ranges = _ranges(end=9.8)

    subject._should_use_subtitle_segment_mode(
        ranges,
        base_duration=10.0,
        gap_threshold=0.2,
    )

    assert ranges[-1]["end"] == pytest.approx(9.8)


def test_threshold_scales_with_output_fps() -> None:
    subject = _Subject(60.0)
    short_ranges = _ranges(end=9.94)
    long_ranges = _ranges(end=9.90)

    subject._should_use_subtitle_segment_mode(
        short_ranges,
        base_duration=10.0,
        gap_threshold=0.2,
    )
    subject._should_use_subtitle_segment_mode(
        long_ranges,
        base_duration=10.0,
        gap_threshold=0.2,
    )

    assert short_ranges[-1]["end"] == pytest.approx(10.0)
    assert long_ranges[-1]["end"] == pytest.approx(9.90)


def test_short_leading_gap_is_absorbed_into_first_chunk() -> None:
    subject = _Subject(30.0)
    ranges = _ranges(start=0.09)

    subject._should_use_subtitle_segment_mode(
        ranges,
        base_duration=10.0,
        gap_threshold=0.2,
    )

    assert ranges[0]["start"] == pytest.approx(0.0)
