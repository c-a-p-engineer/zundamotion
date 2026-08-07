import asyncio
from pathlib import Path

from zundamotion.components.video import subtitle_video_segments
from zundamotion.components.video.subtitle_video_segments import (
    SubtitleVideoSegmentMixin,
)


class _Harness(SubtitleVideoSegmentMixin):
    def __init__(self) -> None:
        self.ffmpeg_path = "ffmpeg"

    @staticmethod
    def _single_job_thread_flags():
        return ["-threads", "1"]


def test_final_mux_maps_video_and_original_audio_once(monkeypatch) -> None:
    harness = _Harness()
    captured = {}

    async def fake_run(cmd, context=None):
        captured["cmd"] = cmd
        captured["context"] = context

    monkeypatch.setattr(subtitle_video_segments, "_run_ffmpeg", fake_run)

    result = asyncio.run(
        harness._mux_subtitle_video_with_source_audio(
            Path("video-only.mp4"),
            Path("source.mp4"),
            Path("final.mp4"),
            duration=12.5,
            scene_id="scene-a",
        )
    )

    assert result == Path("final.mp4")
    cmd = captured["cmd"]
    assert cmd[:7] == [
        "ffmpeg",
        "-y",
        "-nostdin",
        "-i",
        "video-only.mp4",
        "-i",
        "source.mp4",
    ]
    map_pairs = [
        cmd[index + 1]
        for index, value in enumerate(cmd[:-1])
        if value == "-map"
    ]
    assert map_pairs == ["0:v:0", "1:a?"]
    assert cmd.count("-c:a") == 1
    assert cmd[cmd.index("-c:a") + 1] == "copy"
    assert cmd[cmd.index("-c:v") + 1] == "copy"
    assert cmd[cmd.index("-t") + 1] == "12.500000"
    assert "-shortest" not in cmd
    assert captured["context"] == {
        "phase": "VideoPhase",
        "operation": "subtitle_final_audio_mux",
        "scene_id": "scene-a",
        "input_paths": ["video-only.mp4", "source.mp4"],
        "output_path": "final.mp4",
    }


def test_final_mux_without_duration_omits_time_limit(monkeypatch) -> None:
    harness = _Harness()
    captured = {}

    async def fake_run(cmd, context=None):
        captured["cmd"] = cmd

    monkeypatch.setattr(subtitle_video_segments, "_run_ffmpeg", fake_run)

    asyncio.run(
        harness._mux_subtitle_video_with_source_audio(
            Path("video-only.mp4"),
            Path("source.mp4"),
            Path("final.mp4"),
        )
    )

    assert "-t" not in captured["cmd"]


def test_final_mux_uses_optional_audio_map_for_silent_sources(monkeypatch) -> None:
    harness = _Harness()
    captured = {}

    async def fake_run(cmd, context=None):
        captured["cmd"] = cmd

    monkeypatch.setattr(subtitle_video_segments, "_run_ffmpeg", fake_run)

    asyncio.run(
        harness._mux_subtitle_video_with_source_audio(
            Path("video-only.mp4"),
            Path("silent-source.mp4"),
            Path("final.mp4"),
        )
    )

    cmd = captured["cmd"]
    assert "1:a?" in cmd
    assert "-an" not in cmd
    assert cmd[cmd.index("-avoid_negative_ts") + 1] == "make_zero"
    assert cmd[cmd.index("-movflags") + 1] == "+faststart"
