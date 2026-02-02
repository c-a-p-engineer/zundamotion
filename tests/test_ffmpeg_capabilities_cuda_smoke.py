import asyncio
import subprocess

from zundamotion.utils import ffmpeg_capabilities as caps


def test_smoke_test_cuda_filters_success(monkeypatch):
    caps._cuda_smoke_result = None

    async def fake_list_filters(_ffmpeg_path: str = "ffmpeg") -> str:
        return " overlay_cuda scale_cuda hwupload_cuda "

    async def fake_run(_cmd, **_kwargs):
        return subprocess.CompletedProcess(_cmd, 0, "", "")

    monkeypatch.setattr(caps, "_list_ffmpeg_filters", fake_list_filters)
    monkeypatch.setattr(caps, "_run_ffmpeg_async", fake_run)

    result = asyncio.run(caps.smoke_test_cuda_filters("ffmpeg"))

    assert result is True


def test_smoke_test_cuda_filters_missing_filters(monkeypatch):
    caps._cuda_smoke_result = None
    ran = {"count": 0}

    async def fake_list_filters(_ffmpeg_path: str = "ffmpeg") -> str:
        return " scale_cuda "

    async def fake_run(_cmd, **_kwargs):
        ran["count"] += 1
        return subprocess.CompletedProcess(_cmd, 0, "", "")

    monkeypatch.setattr(caps, "_list_ffmpeg_filters", fake_list_filters)
    monkeypatch.setattr(caps, "_run_ffmpeg_async", fake_run)

    result = asyncio.run(caps.smoke_test_cuda_filters("ffmpeg"))

    assert result is False
    assert ran["count"] == 0
