from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from zundamotion.cache import CacheManager
from zundamotion.components.video import renderer as renderer_module
from zundamotion.components.video.renderer import VideoRenderer
from zundamotion.utils import perf_stats
from zundamotion.utils.ffmpeg_hw import get_hw_filter_mode, set_hw_filter_mode


def test_cpu_fixed_skips_gpu_filter_smokes(tmp_path: Path, monkeypatch, caplog) -> None:
    previous = get_hw_filter_mode()
    set_hw_filter_mode("cpu")
    monkeypatch.setenv("DISABLE_HWENC", "1")
    calls = 0

    async def unexpected_diag(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("GPU filter diagnostics must be skipped")

    monkeypatch.setattr(renderer_module, "get_filter_diagnostics", unexpected_diag)
    stats = perf_stats.start_perf_stats()
    caplog.set_level(logging.INFO, logger="zundamotion")
    try:
        asyncio.run(
            VideoRenderer.create(
                {}, tmp_path / "temp", CacheManager(tmp_path / "cache"),
                hw_encoder="cpu",
            )
        )
    finally:
        set_hw_filter_mode(previous)

    assert calls == 0
    assert "[FilterDiag] skipped reason=cpu_mode" in caplog.messages
    assert stats.to_dict()["filter_diag"] == {
        "status": "skipped",
        "reason": "cpu_mode",
    }


def test_cuda_mode_keeps_gpu_filter_diagnostics(monkeypatch) -> None:
    previous = get_hw_filter_mode()
    monkeypatch.delenv("DISABLE_HWENC", raising=False)
    try:
        set_hw_filter_mode("cuda")
        assert not VideoRenderer._skip_gpu_filter_smokes("gpu")
    finally:
        set_hw_filter_mode(previous)


def test_opencl_candidate_keeps_gpu_filter_diagnostics(monkeypatch) -> None:
    previous = get_hw_filter_mode()
    monkeypatch.delenv("DISABLE_HWENC", raising=False)
    try:
        set_hw_filter_mode("auto")
        assert not VideoRenderer._skip_gpu_filter_smokes("gpu")
    finally:
        set_hw_filter_mode(previous)


def test_auto_mode_keeps_diagnostics_before_fallback(monkeypatch) -> None:
    previous = get_hw_filter_mode()
    monkeypatch.delenv("DISABLE_HWENC", raising=False)
    try:
        set_hw_filter_mode("cpu")
        assert not VideoRenderer._skip_gpu_filter_smokes("auto")
    finally:
        set_hw_filter_mode(previous)


def test_cpu_encoder_alone_is_enough_to_skip(monkeypatch) -> None:
    monkeypatch.delenv("DISABLE_HWENC", raising=False)
    assert VideoRenderer._skip_gpu_filter_smokes("cpu")


def test_disable_hwenc_and_cpu_filter_mode_skip_auto(monkeypatch) -> None:
    previous = get_hw_filter_mode()
    monkeypatch.setenv("DISABLE_HWENC", "1")
    try:
        set_hw_filter_mode("cpu")
        assert VideoRenderer._skip_gpu_filter_smokes("auto")
    finally:
        set_hw_filter_mode(previous)
