from __future__ import annotations

import inspect
from pathlib import Path

from zundamotion.utils import ffmpeg_runner
from zundamotion.utils.ffmpeg_diagnostics import record_av_warnings
from zundamotion.utils.ffmpeg_process import execute_ffmpeg_process
from zundamotion.utils.ffmpeg_progress import watch_ffmpeg_stall


def test_runner_facade_preserves_private_monitoring_exports() -> None:
    assert ffmpeg_runner._StallDetector.__module__.endswith(".ffmpeg_progress")
    assert ffmpeg_runner._extract_av_warning_items.__module__.endswith(".ffmpeg_diagnostics")


def test_ffmpeg_runner_facade_remains_small() -> None:
    path = Path(ffmpeg_runner.__file__)
    assert len(path.read_text(encoding="utf-8").splitlines()) <= 180


def test_runner_and_monitoring_entrypoints_are_bounded() -> None:
    for target in (
        ffmpeg_runner.run_ffmpeg_async,
        execute_ffmpeg_process,
        watch_ffmpeg_stall,
        record_av_warnings,
    ):
        lines, _ = inspect.getsourcelines(target)
        assert len(lines) <= 80, (target.__module__, target.__name__, len(lines))
