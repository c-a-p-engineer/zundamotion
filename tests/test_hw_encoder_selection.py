from __future__ import annotations

import asyncio

from zundamotion.utils import ffmpeg_capabilities as caps


def test_get_hw_encoder_kind_for_video_params_cpu_forces_software(monkeypatch):
    monkeypatch.delenv("DISABLE_HWENC", raising=False)
    result = asyncio.run(
        caps.get_hw_encoder_kind_for_video_params(hw_encoder="cpu")
    )
    assert result is None


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
