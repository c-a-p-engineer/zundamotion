"""Pure planning for subtitle ranges, chunks, and segment execution."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Dict, Iterable, List, Literal, Optional, Sequence, Tuple


SubtitleEntry = Dict[str, Any]
SegmentKind = Literal["gap", "subtitle"]
GAP_EMIT_EPSILON_SECONDS = 0.02


@dataclass(frozen=True)
class SubtitleRangePlan:
    """One contiguous subtitle-burn range in source-video time."""

    start: float
    end: float
    subtitles: Tuple[SubtitleEntry, ...]

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    def to_legacy_dict(self) -> Dict[str, Any]:
        return {
            "start": self.start,
            "end": self.end,
            "subtitles": [dict(item) for item in self.subtitles],
        }


@dataclass(frozen=True)
class SubtitleSegment:
    """Ordered source interval to copy or subtitle-burn."""

    kind: SegmentKind
    start: float
    end: float
    range_index: Optional[int] = None
    subtitles: Tuple[SubtitleEntry, ...] = ()

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass(frozen=True)
class SubtitleSegmentPlan:
    """Deterministic subtitle segmentation decision and ordered intervals."""

    ranges: Tuple[SubtitleRangePlan, ...]
    segments: Tuple[SubtitleSegment, ...]
    use_segment_mode: bool
    edge_threshold: float
    absorbed_leading_gap: float
    absorbed_trailing_gap: float

    def to_legacy_ranges(self) -> List[Dict[str, Any]]:
        return [item.to_legacy_dict() for item in self.ranges]


def _parse_interval(
    subtitle: SubtitleEntry,
    *,
    base_duration: Optional[float],
) -> Optional[tuple[float, float]]:
    try:
        start = max(0.0, float(subtitle.get("start", 0.0)))
        duration = max(0.0, float(subtitle.get("duration", 0.0)))
    except (TypeError, ValueError):
        return None
    end = start + duration
    if base_duration is not None:
        end = min(float(base_duration), end)
    if end <= start:
        return None
    return start, end


def merge_subtitle_ranges(
    subtitles: Sequence[SubtitleEntry],
    *,
    base_duration: Optional[float],
    gap_threshold: float = 0.20,
) -> Tuple[SubtitleRangePlan, ...]:
    """Merge overlapping or near-adjacent subtitle intervals.

    Input order is preserved to retain the existing renderer contract.
    Invalid and zero-length entries are ignored. Input dictionaries are copied.
    """
    mutable: List[Dict[str, Any]] = []
    for subtitle in subtitles:
        interval = _parse_interval(
            subtitle,
            base_duration=base_duration,
        )
        if interval is None:
            continue
        start, end = interval
        copied = dict(subtitle)
        if mutable and start <= float(mutable[-1]["end"]) + gap_threshold:
            mutable[-1]["end"] = max(float(mutable[-1]["end"]), end)
            mutable[-1]["subtitles"].append(copied)
        else:
            mutable.append(
                {
                    "start": start,
                    "end": end,
                    "subtitles": [copied],
                }
            )
    return tuple(
        SubtitleRangePlan(
            start=float(item["start"]),
            end=float(item["end"]),
            subtitles=tuple(item["subtitles"]),
        )
        for item in mutable
    )


def split_subtitle_ranges_for_png(
    subtitles: Sequence[SubtitleEntry],
    *,
    base_duration: Optional[float],
    gap_threshold: float = 0.20,
    max_subtitles: int = 12,
) -> Tuple[SubtitleRangePlan, ...]:
    """Split merged ranges at safe non-overlapping subtitle boundaries."""
    merged = merge_subtitle_ranges(
        subtitles,
        base_duration=base_duration,
        gap_threshold=gap_threshold,
    )
    limit = max_subtitles if max_subtitles > 0 else 12
    chunks: List[SubtitleRangePlan] = []

    for item in merged:
        current_subtitles: List[SubtitleEntry] = []
        current_start: Optional[float] = None
        current_end = 0.0
        for subtitle in item.subtitles:
            interval = _parse_interval(
                subtitle,
                base_duration=base_duration,
            )
            if interval is None:
                continue
            start, end = interval
            can_split = (
                bool(current_subtitles)
                and len(current_subtitles) >= limit
                and start >= current_end - 0.001
            )
            if can_split:
                chunks.append(
                    SubtitleRangePlan(
                        start=float(current_start or 0.0),
                        end=current_end,
                        subtitles=tuple(current_subtitles),
                    )
                )
                current_subtitles = []
                current_start = None
                current_end = 0.0

            if not current_subtitles:
                current_start = start
                current_end = end
            else:
                current_end = max(current_end, end)
            current_subtitles.append(dict(subtitle))

        if current_subtitles:
            chunks.append(
                SubtitleRangePlan(
                    start=float(current_start or 0.0),
                    end=current_end,
                    subtitles=tuple(current_subtitles),
                )
            )
    return tuple(chunks)


def absorb_unrenderable_edge_gaps(
    ranges: Sequence[SubtitleRangePlan],
    *,
    base_duration: float,
    min_exact_segment_duration: float,
) -> tuple[Tuple[SubtitleRangePlan, ...], float, float]:
    """Return copied ranges with sub-frame edge gaps absorbed."""
    if not ranges:
        return (), 0.0, 0.0

    copied = list(ranges)
    threshold = max(0.0, float(min_exact_segment_duration))
    absorbed_leading = 0.0
    absorbed_trailing = 0.0

    first_start = max(0.0, float(copied[0].start))
    if 0.0 < first_start <= threshold:
        absorbed_leading = first_start
        copied[0] = replace(copied[0], start=0.0)

    trailing_gap = max(0.0, float(base_duration) - float(copied[-1].end))
    if 0.0 < trailing_gap <= threshold:
        absorbed_trailing = trailing_gap
        copied[-1] = replace(copied[-1], end=float(base_duration))

    return tuple(copied), absorbed_leading, absorbed_trailing


def should_use_subtitle_segment_mode(
    ranges: Sequence[SubtitleRangePlan],
    *,
    base_duration: float,
    gap_threshold: float,
    min_exact_segment_duration: float,
) -> bool:
    """Decide whether segment rendering has meaningful copyable intervals."""
    if not ranges:
        return False
    if len(ranges) > 1:
        return True
    edge_threshold = max(
        float(gap_threshold),
        float(min_exact_segment_duration),
    )
    leading_gap = max(0.0, float(ranges[0].start))
    trailing_gap = max(0.0, float(base_duration) - float(ranges[-1].end))
    return leading_gap >= edge_threshold or trailing_gap >= edge_threshold


def build_subtitle_segment_plan(
    subtitles: Sequence[SubtitleEntry],
    *,
    base_duration: float,
    gap_threshold: float,
    max_subtitles: int,
    min_exact_segment_duration: float,
) -> SubtitleSegmentPlan:
    """Build the complete immutable range/chunk/segment plan."""
    split_ranges = split_subtitle_ranges_for_png(
        subtitles,
        base_duration=base_duration,
        gap_threshold=gap_threshold,
        max_subtitles=max_subtitles,
    )
    ranges, absorbed_leading, absorbed_trailing = (
        absorb_unrenderable_edge_gaps(
            split_ranges,
            base_duration=base_duration,
            min_exact_segment_duration=min_exact_segment_duration,
        )
    )
    use_segment_mode = should_use_subtitle_segment_mode(
        ranges,
        base_duration=base_duration,
        gap_threshold=gap_threshold,
        min_exact_segment_duration=min_exact_segment_duration,
    )

    segments: List[SubtitleSegment] = []
    cursor = 0.0
    for range_index, item in enumerate(ranges):
        if item.start > cursor + GAP_EMIT_EPSILON_SECONDS:
            segments.append(
                SubtitleSegment(
                    kind="gap",
                    start=cursor,
                    end=item.start,
                )
            )
        segments.append(
            SubtitleSegment(
                kind="subtitle",
                start=item.start,
                end=item.end,
                range_index=range_index,
                subtitles=item.subtitles,
            )
        )
        cursor = item.end

    if float(base_duration) > cursor + float(min_exact_segment_duration):
        segments.append(
            SubtitleSegment(
                kind="gap",
                start=cursor,
                end=float(base_duration),
            )
        )

    return SubtitleSegmentPlan(
        ranges=ranges,
        segments=tuple(segments),
        use_segment_mode=use_segment_mode,
        edge_threshold=max(
            float(gap_threshold),
            float(min_exact_segment_duration),
        ),
        absorbed_leading_gap=absorbed_leading,
        absorbed_trailing_gap=absorbed_trailing,
    )
