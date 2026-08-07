from copy import deepcopy

import pytest

from zundamotion.components.video.subtitle_segment_plan import (
    SubtitleRangePlan,
    absorb_unrenderable_edge_gaps,
    build_subtitle_segment_plan,
    merge_subtitle_ranges,
    should_use_subtitle_segment_mode,
    split_subtitle_ranges_for_png,
)


def _sub(start: float, duration: float, text: str) -> dict:
    return {"start": start, "duration": duration, "text": text}


def test_merge_preserves_input_order_and_copies_subtitles() -> None:
    subtitles = [
        _sub(0.0, 1.0, "a"),
        _sub(1.15, 0.5, "b"),
        _sub(2.0, 0.5, "c"),
    ]
    original = deepcopy(subtitles)

    ranges = merge_subtitle_ranges(
        subtitles,
        base_duration=3.0,
        gap_threshold=0.20,
    )

    assert [(item.start, item.end) for item in ranges] == [
        (0.0, 1.65),
        (2.0, 2.5),
    ]
    assert [sub["text"] for sub in ranges[0].subtitles] == ["a", "b"]
    assert subtitles == original
    assert ranges[0].subtitles[0] is not subtitles[0]


def test_merge_clips_to_base_and_ignores_invalid_intervals() -> None:
    ranges = merge_subtitle_ranges(
        [
            _sub(4.5, 2.0, "clipped"),
            _sub(6.0, 1.0, "outside"),
            {"start": "bad", "duration": 1.0},
            _sub(1.0, 0.0, "empty"),
        ],
        base_duration=5.0,
    )

    assert len(ranges) == 1
    assert ranges[0].start == pytest.approx(4.5)
    assert ranges[0].end == pytest.approx(5.0)


def test_chunk_split_respects_limit_at_non_overlapping_boundary() -> None:
    ranges = split_subtitle_ranges_for_png(
        [
            _sub(0.0, 1.0, "a"),
            _sub(0.8, 0.5, "overlap"),
            _sub(1.3, 0.5, "c"),
        ],
        base_duration=3.0,
        gap_threshold=0.20,
        max_subtitles=2,
    )

    assert len(ranges) == 2
    assert [sub["text"] for sub in ranges[0].subtitles] == ["a", "overlap"]
    assert [sub["text"] for sub in ranges[1].subtitles] == ["c"]
    assert ranges[0].end == pytest.approx(1.3)
    assert ranges[1].start == pytest.approx(1.3)


def test_chunk_split_does_not_cut_through_active_overlap() -> None:
    ranges = split_subtitle_ranges_for_png(
        [
            _sub(0.0, 2.0, "a"),
            _sub(0.5, 2.0, "b"),
            _sub(1.0, 2.0, "c"),
        ],
        base_duration=4.0,
        gap_threshold=0.20,
        max_subtitles=1,
    )

    assert len(ranges) == 1
    assert len(ranges[0].subtitles) == 3


def test_edge_absorption_returns_new_ranges_without_mutation() -> None:
    ranges = (
        SubtitleRangePlan(
            start=0.09,
            end=4.0,
            subtitles=(_sub(0.09, 1.0, "a"),),
        ),
        SubtitleRangePlan(
            start=4.0,
            end=9.87,
            subtitles=(_sub(4.0, 1.0, "b"),),
        ),
    )

    adjusted, leading, trailing = absorb_unrenderable_edge_gaps(
        ranges,
        base_duration=10.0,
        min_exact_segment_duration=4.0 / 30.0,
    )

    assert adjusted[0].start == pytest.approx(0.0)
    assert adjusted[-1].end == pytest.approx(10.0)
    assert leading == pytest.approx(0.09)
    assert trailing == pytest.approx(0.13)
    assert ranges[0].start == pytest.approx(0.09)
    assert ranges[-1].end == pytest.approx(9.87)


def test_single_full_range_does_not_use_segment_mode() -> None:
    ranges = (
        SubtitleRangePlan(
            start=0.0,
            end=10.0,
            subtitles=(_sub(0.0, 10.0, "a"),),
        ),
    )

    assert not should_use_subtitle_segment_mode(
        ranges,
        base_duration=10.0,
        gap_threshold=0.20,
        min_exact_segment_duration=4.0 / 30.0,
    )


def test_single_range_with_copyable_edge_uses_segment_mode() -> None:
    ranges = (
        SubtitleRangePlan(
            start=1.0,
            end=9.0,
            subtitles=(_sub(1.0, 8.0, "a"),),
        ),
    )

    assert should_use_subtitle_segment_mode(
        ranges,
        base_duration=10.0,
        gap_threshold=0.20,
        min_exact_segment_duration=4.0 / 30.0,
    )


def test_complete_plan_orders_gap_and_subtitle_segments() -> None:
    plan = build_subtitle_segment_plan(
        [
            _sub(1.0, 1.0, "a"),
            _sub(4.0, 1.0, "b"),
        ],
        base_duration=6.0,
        gap_threshold=0.20,
        max_subtitles=12,
        min_exact_segment_duration=4.0 / 30.0,
    )

    assert plan.use_segment_mode is True
    assert [segment.kind for segment in plan.segments] == [
        "gap",
        "subtitle",
        "gap",
        "subtitle",
        "gap",
    ]
    assert [(segment.start, segment.end) for segment in plan.segments] == [
        (0.0, 1.0),
        (1.0, 2.0),
        (2.0, 4.0),
        (4.0, 5.0),
        (5.0, 6.0),
    ]


def test_complete_plan_reports_absorbed_edges_and_legacy_ranges() -> None:
    plan = build_subtitle_segment_plan(
        [
            _sub(0.09, 1.0, "a"),
            _sub(4.0, 5.87, "b"),
        ],
        base_duration=10.0,
        gap_threshold=0.20,
        max_subtitles=12,
        min_exact_segment_duration=4.0 / 30.0,
    )

    assert plan.absorbed_leading_gap == pytest.approx(0.09)
    assert plan.absorbed_trailing_gap == pytest.approx(0.13)
    legacy = plan.to_legacy_ranges()
    assert legacy[0]["start"] == pytest.approx(0.0)
    assert legacy[-1]["end"] == pytest.approx(10.0)
