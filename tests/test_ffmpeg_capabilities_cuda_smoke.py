import asyncio
import subprocess

from zundamotion.utils import ffmpeg_filter_smoke as smoke


def test_smoke_test_cuda_filters_success(monkeypatch):
    smoke._cuda_smoke_result = None

    async def fake_list_filters(_ffmpeg_path: str = "ffmpeg") -> str:
        return " overlay_cuda scale_cuda hwupload_cuda "

    async def fake_run(_cmd, **_kwargs):
        return subprocess.CompletedProcess(_cmd, 0, "", "")

    monkeypatch.setattr(smoke, "_list_ffmpeg_filters", fake_list_filters)
    monkeypatch.setattr(smoke, "_run_ffmpeg_async", fake_run)

    result = asyncio.run(smoke.smoke_test_cuda_filters("ffmpeg"))

    assert result is True


def test_smoke_test_cuda_filters_missing_filters(monkeypatch):
    smoke._cuda_smoke_result = None
    ran = {"count": 0}

    async def fake_list_filters(_ffmpeg_path: str = "ffmpeg") -> str:
        return " scale_cuda "

    async def fake_run(_cmd, **_kwargs):
        ran["count"] += 1
        return subprocess.CompletedProcess(_cmd, 0, "", "")

    monkeypatch.setattr(smoke, "_list_ffmpeg_filters", fake_list_filters)
    monkeypatch.setattr(smoke, "_run_ffmpeg_async", fake_run)

    result = asyncio.run(smoke.smoke_test_cuda_filters("ffmpeg"))

    assert result is False
    assert ran["count"] == 0
