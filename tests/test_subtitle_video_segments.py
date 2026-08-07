import asyncio
from pathlib import Path

from zundamotion.components.video import overlays as overlay_module
from zundamotion.components.video import subtitle_video_segments
from zundamotion.components.video.overlays import OverlayMixin
from zundamotion.components.video.subtitle_video_segments import (
    SubtitleVideoSegmentMixin,
)


class _VideoParams:
    fps = 30

    @staticmethod
    def to_ffmpeg_opts(hw_kind):
        return [
            "-fps_mode",
            "cfr",
            "-r",
            "30",
            "-s",
            "320x180",
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
        ]


class _Harness(SubtitleVideoSegmentMixin):
    def __init__(self) -> None:
        self.ffmpeg_path = "ffmpeg"
        self.video_params = _VideoParams()
        self.hw_kind = None
        self.burn_calls = []

    @staticmethod
    def _min_exact_segment_duration() -> float:
        return 4.0 / 30.0

    @staticmethod
    def _single_job_thread_flags():
        return ["-threads", "1"]

    async def _apply_subtitle_overlays_full(self, *args, **kwargs):
        self.burn_calls.append((args, kwargs))
        return args[2]


class _SubtitleGen:
    subtitle_config = {}

    @staticmethod
    def subtitle_render_mode() -> str:
        return "ass"

    @staticmethod
    def build_ass_subtitle_file(subtitles, output_path: Path) -> Path:
        return output_path


class _OverlayHarness(OverlayMixin):
    def __init__(self, tmp_path: Path) -> None:
        self.ffmpeg_path = "ffmpeg"
        self.temp_dir = tmp_path
        self.subtitle_gen = _SubtitleGen()
        self.video_params = _VideoParams()
        self.hw_kind = None

    @staticmethod
    def _single_job_thread_flags():
        return ["-threads", "1"]

    @staticmethod
    def _subtitle_burn_video_opts(subtitle_mode: str):
        return ["-c:v", "libx264", "-r", "30", "-fps_mode", "cfr"]


def test_video_segment_filter_normalizes_fps_timebase_and_pts() -> None:
    harness = _Harness()

    filter_graph = harness._subtitle_video_segment_filter(
        start=1.25,
        duration=2.5,
    )

    assert "trim=start=1.250000:duration=2.500000" in filter_graph
    assert "setpts=PTS-STARTPTS" in filter_graph
    assert "fps=30" in filter_graph
    assert "settb=expr=1/30" in filter_graph
    assert filter_graph.endswith("setpts=N[v]")


def test_short_video_segment_is_not_emitted() -> None:
    harness = _Harness()

    result = asyncio.run(
        harness._cut_subtitle_video_segment(
            Path("base.mp4"),
            Path("out.mp4"),
            start=0.0,
            duration=0.1,
        )
    )

    assert result is None


def test_video_segment_command_maps_video_only(monkeypatch) -> None:
    harness = _Harness()
    captured = {}

    async def fake_run(cmd, context=None):
        captured["cmd"] = cmd
        captured["context"] = context

    monkeypatch.setattr(subtitle_video_segments, "_run_ffmpeg", fake_run)

    result = asyncio.run(
        harness._cut_subtitle_video_segment(
            Path("base.mp4"),
            Path("out.mp4"),
            start=1.0,
            duration=2.0,
            scene_id="scene-a",
            segment_index=3,
        )
    )

    assert result == Path("out.mp4")
    cmd = captured["cmd"]
    assert cmd[:5] == ["ffmpeg", "-y", "-nostdin", "-i", "base.mp4"]
    assert cmd[cmd.index("-map") + 1] == "[v]"
    assert "-an" in cmd
    assert "-map" not in cmd[cmd.index("-an") + 1 :]
    assert "-c:a" not in cmd
    assert "-avoid_negative_ts" in cmd
    assert captured["context"]["operation"] == "subtitle_video_segment_cut"
    assert captured["context"]["scene_id"] == "scene-a"
    assert captured["context"]["segment_index"] == 3


def test_subtitle_burn_requests_explicit_video_only_mode() -> None:
    harness = _Harness()
    subtitles = [{"start": 0.0, "duration": 1.0, "text": "hello"}]

    result = asyncio.run(
        harness._burn_subtitle_video_segment(
            Path("base.mp4"),
            subtitles,
            Path("burned.mp4"),
            scene_id="scene-a",
            segment_index=2,
        )
    )

    assert result == Path("burned.mp4")
    args, kwargs = harness.burn_calls[0]
    assert args == (Path("base.mp4"), subtitles, Path("burned.mp4"))
    assert kwargs == {
        "scene_id": "scene-a",
        "chunk_index": 2,
        "video_only": True,
        "segment_workers": None,
    }


def test_full_burn_video_only_command_has_no_audio_mapping(
    tmp_path: Path,
    monkeypatch,
) -> None:
    harness = _OverlayHarness(tmp_path)
    captured = {}

    async def fake_duration(*args, **kwargs):
        return 2.0

    async def fake_run(cmd, context=None):
        captured["cmd"] = cmd

    monkeypatch.setattr(overlay_module, "get_media_duration", fake_duration)
    monkeypatch.setattr(overlay_module, "_run_ffmpeg", fake_run)

    result = asyncio.run(
        harness._apply_subtitle_overlays_full(
            Path("base.mp4"),
            [{"start": 0.0, "duration": 1.0, "text": "hello"}],
            Path("burned.mp4"),
            video_only=True,
        )
    )

    assert result == Path("burned.mp4")
    cmd = captured["cmd"]
    assert "-an" in cmd
    assert "0:a?" not in cmd
    assert "-c:a" not in cmd


def test_full_burn_default_command_preserves_audio_copy(
    tmp_path: Path,
    monkeypatch,
) -> None:
    harness = _OverlayHarness(tmp_path)
    captured = {}

    async def fake_duration(*args, **kwargs):
        return 2.0

    async def fake_run(cmd, context=None):
        captured["cmd"] = cmd

    monkeypatch.setattr(overlay_module, "get_media_duration", fake_duration)
    monkeypatch.setattr(overlay_module, "_run_ffmpeg", fake_run)

    asyncio.run(
        harness._apply_subtitle_overlays_full(
            Path("base.mp4"),
            [{"start": 0.0, "duration": 1.0, "text": "hello"}],
            Path("burned.mp4"),
        )
    )

    cmd = captured["cmd"]
    assert "0:a?" in cmd
    assert cmd[cmd.index("-c:a") + 1] == "copy"
    assert "-an" not in cmd
