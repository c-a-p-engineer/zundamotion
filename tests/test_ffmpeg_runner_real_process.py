from __future__ import annotations

import asyncio
from pathlib import Path
import stat
import subprocess

import pytest

from zundamotion.utils.ffmpeg_runner import run_ffmpeg_async


def _fake_ffmpeg(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "ffmpeg-fake"
    path.write_text("#!/usr/bin/env python3\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def test_real_process_timeout_terminates_child(tmp_path: Path) -> None:
    exe = _fake_ffmpeg(tmp_path, "import time\ntime.sleep(30)\n")
    with pytest.raises(subprocess.TimeoutExpired):
        asyncio.run(run_ffmpeg_async([str(exe)], timeout=0.2))


def test_real_process_stall_detector_terminates_child(tmp_path: Path, monkeypatch) -> None:
    exe = _fake_ffmpeg(
        tmp_path,
        "import sys,time\n"
        "print('out_time_ms=1000000', flush=True)\n"
        "time.sleep(30)\n",
    )
    monkeypatch.setenv("FFMPEG_STALL_TIMEOUT_SEC", "1")
    monkeypatch.setenv("FFMPEG_PROGRESS_LOG_INTERVAL_SEC", "1")
    with pytest.raises(subprocess.TimeoutExpired):
        asyncio.run(run_ffmpeg_async([str(exe)], timeout=6))


def test_real_process_cancellation_cleans_up_child(tmp_path: Path) -> None:
    exe = _fake_ffmpeg(tmp_path, "import time\ntime.sleep(30)\n")

    async def _run() -> None:
        task = asyncio.create_task(run_ffmpeg_async([str(exe)]))
        await asyncio.sleep(0.2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(_run())
