from __future__ import annotations

import inspect
import subprocess
from pathlib import Path

from zundamotion.components.video.clip_command import build_clip_command
from zundamotion.components.video.clip_executor import _is_gpu_failure
from zundamotion.components.video.clip_image_input import append_looped_image_input
from zundamotion.components.video.clip_renderer import render_clip


class _VideoParams:
    def to_ffmpeg_opts(self, hw_kind):
        return ["-vcodec", "libx264" if hw_kind is None else str(hw_kind)]


class _AudioParams:
    def to_ffmpeg_opts(self):
        return ["-acodec", "aac"]


class _Renderer:
    video_params = _VideoParams()
    audio_params = _AudioParams()
    hw_kind = "nvenc"


def test_render_clip_is_only_an_orchestrator() -> None:
    lines, _start = inspect.getsourcelines(render_clip)
    assert len(lines) <= 80


def test_clip_command_generation_preserves_map_duration_and_output() -> None:
    command = build_clip_command(
        renderer=_Renderer(),
        input_command=["ffmpeg", "-i", "input.mp4"],
        filter_complex_parts=["[0:v]null[final_v]", "anullsrc[final_a]"],
        audio_map="[final_a]",
        duration=1.25,
        output_path=Path("out.mp4"),
        force_cpu=True,
    )

    assert command[:3] == ["ffmpeg", "-i", "input.mp4"]
    assert command[command.index("-filter_complex") + 1] == (
        "[0:v]null[final_v];anullsrc[final_a]"
    )
    assert command[command.index("-map") + 1] == "[final_v]"
    assert command[command.index("-t") + 1] == "1.25"
    assert command[-2:] == ["-shortest", "out.mp4"]
    assert "libx264" in command


def test_gpu_failure_classifier_keeps_legacy_fallback_signals() -> None:
    nvenc = subprocess.CalledProcessError(234, ["ffmpeg"], stderr="h264_nvenc failed")
    generic = subprocess.CalledProcessError(1, ["ffmpeg"], stderr="invalid input")

    assert _is_gpu_failure(nvenc) is True
    assert _is_gpu_failure(generic) is False


def test_clip_image_input_is_bounded_by_fps_and_duration() -> None:
    command = ["ffmpeg"]

    append_looped_image_input(
        command, Path("still.png"), duration=0.533333333, fps=30
    )

    assert command == [
        "ffmpeg",
        "-loop",
        "1",
        "-framerate",
        "30",
        "-t",
        "0.533333333",
        "-i",
        "still.png",
    ]
