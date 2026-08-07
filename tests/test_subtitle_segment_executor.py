import asyncio
from pathlib import Path

import pytest

from zundamotion.components.video.subtitle_segment_executor import (
    SubtitleSegmentExecutorMixin,
)
from zundamotion.components.video.subtitle_segment_plan import (
    SubtitleRangePlan,
    SubtitleSegment,
    SubtitleSegmentPlan,
)


def _plan() -> SubtitleSegmentPlan:
    subtitle_a = {"start": 1.0, "duration": 1.0, "text": "a"}
    subtitle_b = {"start": 3.0, "duration": 1.0, "text": "b"}
    ranges = (
        SubtitleRangePlan(1.0, 2.0, (subtitle_a,)),
        SubtitleRangePlan(3.0, 4.0, (subtitle_b,)),
    )
    return SubtitleSegmentPlan(
        ranges=ranges,
        segments=(
            SubtitleSegment("gap", 0.0, 1.0),
            SubtitleSegment("subtitle", 1.0, 2.0, 0, (subtitle_a,)),
            SubtitleSegment("gap", 2.0, 3.0),
            SubtitleSegment("subtitle", 3.0, 4.0, 1, (subtitle_b,)),
        ),
        use_segment_mode=True,
        edge_threshold=0.2,
        absorbed_leading_gap=0.0,
        absorbed_trailing_gap=0.0,
    )


class _Harness(SubtitleSegmentExecutorMixin):
    def __init__(self, tmp_path: Path) -> None:
        self.temp_dir = tmp_path
        self.jobs = "0"
        self.hw_kind = None
        self.active = 0
        self.max_active = 0
        self.calls = []
        self.fail_index = None

    async def _enter(self, label: str, index: int) -> None:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.calls.append((label, index, "start"))
        await asyncio.sleep(0.01)
        if self.fail_index == index:
            self.active -= 1
            raise RuntimeError(f"boom-{index}")
        self.active -= 1
        self.calls.append((label, index, "end"))

    async def _cut_subtitle_video_segment(
        self,
        base_video,
        output_path,
        *,
        start,
        duration,
        scene_id=None,
        segment_index=None,
        worker_count=None,
    ):
        await self._enter("cut", int(segment_index))
        return Path(output_path)

    async def _burn_subtitle_video_segment(
        self,
        base_video,
        subtitles,
        output_path,
        *,
        scene_id=None,
        segment_index=None,
        worker_count=None,
    ):
        await self._enter("burn", int(segment_index))
        return Path(output_path)

    async def _concat_subtitle_video_segments(
        self,
        segment_paths,
        output_path,
        *,
        scene_id=None,
    ):
        self.calls.append(("concat", tuple(segment_paths), Path(output_path)))
        return Path(output_path)

    async def _mux_subtitle_video_with_source_audio(
        self,
        video_only_path,
        source_media_path,
        output_path,
        *,
        duration=None,
        scene_id=None,
    ):
        self.calls.append(
            (
                "mux",
                Path(video_only_path),
                Path(source_media_path),
                Path(output_path),
                duration,
            )
        )
        return Path(output_path)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, 1), ("1", 1), ("2", 2), ("0", 1), ("3", 1), ("bad", 1)],
)
def test_subtitle_segment_worker_count_is_bounded(monkeypatch, raw, expected) -> None:
    if raw is None:
        monkeypatch.delenv("ZUNDAMOTION_SUBTITLE_SEGMENT_WORKERS", raising=False)
    else:
        monkeypatch.setenv("ZUNDAMOTION_SUBTITLE_SEGMENT_WORKERS", raw)
    assert _Harness._subtitle_segment_worker_count() == expected


def test_adjust_subtitles_rebases_start_without_mutating_source() -> None:
    source = {"start": 3.25, "duration": 0.5, "text": "hello"}
    segment = SubtitleSegment("subtitle", 3.0, 4.0, 0, (source,))

    adjusted = _Harness._adjust_subtitles_for_segment(segment)

    assert adjusted[0]["start"] == pytest.approx(0.25)
    assert source["start"] == pytest.approx(3.25)


def test_executor_preserves_plan_order_and_caps_parallelism(tmp_path: Path) -> None:
    harness = _Harness(tmp_path)

    result = asyncio.run(
        harness._execute_subtitle_segment_plan(
            Path("base.mp4"),
            _plan(),
            scene_id="scene-a",
            worker_count=2,
        )
    )

    assert result.worker_count == 2
    assert result.gap_segments == 2
    assert result.subtitle_segments == 2
    assert result.ffmpeg_calls == 6
    assert harness.max_active <= 2
    assert [path.name for path in result.paths] == [
        "base_sub_gap_v_000.mp4",
        "base_sub_burn_v_001.mp4",
        "base_sub_gap_v_002.mp4",
        "base_sub_burn_v_003.mp4",
    ]


def test_pipeline_concats_video_then_muxes_original_audio_once(tmp_path: Path) -> None:
    harness = _Harness(tmp_path)

    result = asyncio.run(
        harness._render_subtitle_segment_pipeline(
            Path("source.mp4"),
            _plan(),
            Path("final.mp4"),
            base_duration=4.0,
            scene_id="scene-a",
            worker_count=1,
        )
    )

    assert result == Path("final.mp4")
    concat_calls = [call for call in harness.calls if call[0] == "concat"]
    mux_calls = [call for call in harness.calls if call[0] == "mux"]
    assert len(concat_calls) == 1
    assert len(mux_calls) == 1
    assert mux_calls[0][1].name == "source_sub_video_concat.mp4"
    assert mux_calls[0][2] == Path("source.mp4")
    assert mux_calls[0][3] == Path("final.mp4")
    assert mux_calls[0][4] == pytest.approx(4.0)


def test_executor_propagates_failure_before_concat(tmp_path: Path) -> None:
    harness = _Harness(tmp_path)
    harness.fail_index = 1

    with pytest.raises(RuntimeError, match="boom-1"):
        asyncio.run(
            harness._render_subtitle_segment_pipeline(
                Path("source.mp4"),
                _plan(),
                Path("final.mp4"),
                base_duration=4.0,
                scene_id="scene-a",
                worker_count=2,
            )
        )

    assert not any(call[0] == "concat" for call in harness.calls)
    assert not any(call[0] == "mux" for call in harness.calls)
