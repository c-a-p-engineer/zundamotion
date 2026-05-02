from __future__ import annotations

import asyncio

from zundamotion.utils import ffmpeg_capabilities as caps
from zundamotion.components.pipeline_phases.video_phase.main import VideoPhase


def test_get_hw_encoder_kind_for_video_params_cpu_forces_software(monkeypatch):
    monkeypatch.delenv("DISABLE_HWENC", raising=False)
    result = asyncio.run(
        caps.get_hw_encoder_kind_for_video_params(hw_encoder="cpu")
    )
    assert result is None


def test_get_encoder_options_cpu_does_not_probe_nvenc(monkeypatch):
    def fail_if_called(ffmpeg_path="ffmpeg"):
        raise AssertionError("NVENC should not be probed when hw_encoder=cpu")

    monkeypatch.setattr(caps, "is_nvenc_available", fail_if_called)

    encoder, opts = asyncio.run(caps.get_encoder_options("cpu", "speed"))

    assert encoder == "libx264"
    assert opts == ["-preset", "ultrafast", "-crf", "30"]


def test_get_encoder_options_speed_uses_fastest_nvenc_preset(monkeypatch):
    monkeypatch.setattr(
        caps,
        "is_nvenc_available",
        lambda ffmpeg_path="ffmpeg": asyncio.sleep(0, result=True),
    )

    encoder, opts = asyncio.run(caps.get_encoder_options("auto", "speed"))

    assert encoder == "h264_nvenc"
    assert opts[:2] == ["-preset", "p1"]


def test_get_hw_encoder_kind_for_video_params_gpu_prefers_nvenc(monkeypatch):
    monkeypatch.delenv("DISABLE_HWENC", raising=False)
    monkeypatch.setattr(caps, "is_nvenc_available", lambda ffmpeg_path="ffmpeg": asyncio.sleep(0, result=True))

    result = asyncio.run(
        caps.get_hw_encoder_kind_for_video_params(hw_encoder="gpu")
    )

    assert result == "nvenc"


def test_get_hw_encoder_kind_for_video_params_gpu_falls_back_to_cpu(monkeypatch):
    monkeypatch.delenv("DISABLE_HWENC", raising=False)
    monkeypatch.setattr(caps, "is_nvenc_available", lambda ffmpeg_path="ffmpeg": asyncio.sleep(0, result=False))

    result = asyncio.run(
        caps.get_hw_encoder_kind_for_video_params(hw_encoder="gpu")
    )

    assert result is None


def test_video_phase_auto_nvenc_uses_cpu_when_filters_are_cpu():
    result = VideoPhase._resolve_effective_hw_kind("auto", "nvenc", "cpu")

    assert result is None


def test_video_phase_gpu_nvenc_keeps_nvenc_when_filters_are_cpu():
    result = VideoPhase._resolve_effective_hw_kind("gpu", "nvenc", "cpu")

    assert result == "nvenc"
