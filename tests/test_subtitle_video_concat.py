import asyncio
from pathlib import Path

import pytest

from zundamotion.components.video import subtitle_video_segments
from zundamotion.components.video.subtitle_video_segments import (
    SubtitleVideoSegmentMixin,
)


class _Harness(SubtitleVideoSegmentMixin):
    def __init__(self, temp_dir: Path) -> None:
        self.temp_dir = temp_dir
        self.ffmpeg_path = "ffmpeg"

    @staticmethod
    def _single_job_thread_flags():
        return ["-threads", "1"]


def test_concat_list_requires_at_least_one_segment(tmp_path: Path) -> None:
    harness = _Harness(tmp_path)

    with pytest.raises(ValueError, match="at least one segment"):
        harness._write_subtitle_video_concat_list(
            [],
            output_path=tmp_path / "out.mp4",
        )


def test_concat_list_preserves_order_and_escapes_quotes(tmp_path: Path) -> None:
    harness = _Harness(tmp_path)
    first = tmp_path / "first.mp4"
    second = tmp_path / "second's.mp4"

    list_path = harness._write_subtitle_video_concat_list(
        [first, second],
        output_path=tmp_path / "joined.mp4",
    )

    assert list_path == tmp_path / "joined_segments.ffconcat"
    assert list_path.read_text(encoding="utf-8").splitlines() == [
        "ffconcat version 1.0",
        f"file '{first.resolve()}'",
        f"file '{str(second.resolve()).replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'",
    ]


def test_concat_command_copies_video_only_and_regenerates_pts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    harness = _Harness(tmp_path)
    first = tmp_path / "first.mp4"
    second = tmp_path / "second.mp4"
    captured = {}

    async def fake_run(cmd, context=None):
        captured["cmd"] = cmd
        captured["context"] = context

    monkeypatch.setattr(subtitle_video_segments, "_run_ffmpeg", fake_run)

    output_path = tmp_path / "joined.mp4"
    result = asyncio.run(
        harness._concat_subtitle_video_segments(
            [first, second],
            output_path,
            scene_id="scene-a",
        )
    )

    assert result == output_path
    cmd = captured["cmd"]
    assert cmd[:4] == ["ffmpeg", "-y", "-nostdin", "-fflags"]
    assert cmd[cmd.index("-fflags") + 1] == "+genpts"
    assert cmd[cmd.index("-f") + 1] == "concat"
    assert cmd[cmd.index("-safe") + 1] == "0"
    assert cmd[cmd.index("-map") + 1] == "0:v:0"
    assert "-an" in cmd
    assert cmd[cmd.index("-c:v") + 1] == "copy"
    assert cmd[cmd.index("-avoid_negative_ts") + 1] == "make_zero"
    assert "-c:a" not in cmd
    assert captured["context"] == {
        "phase": "VideoPhase",
        "operation": "subtitle_video_segment_concat",
        "scene_id": "scene-a",
        "input_paths": [str(first), str(second)],
        "output_path": str(output_path),
    }


def test_concat_context_keeps_caller_order(tmp_path: Path, monkeypatch) -> None:
    harness = _Harness(tmp_path)
    paths = [tmp_path / "03.mp4", tmp_path / "01.mp4", tmp_path / "02.mp4"]
    captured = {}

    async def fake_run(cmd, context=None):
        captured["context"] = context

    monkeypatch.setattr(subtitle_video_segments, "_run_ffmpeg", fake_run)

    asyncio.run(
        harness._concat_subtitle_video_segments(
            paths,
            tmp_path / "joined.mp4",
        )
    )

    assert captured["context"]["input_paths"] == [str(path) for path in paths]
