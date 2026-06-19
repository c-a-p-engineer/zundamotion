from __future__ import annotations

import asyncio
import subprocess

import pytest

from zundamotion.utils.ffmpeg_runner import (
    _StallDetector,
    _StallSnapshot,
    _extract_av_warning_items,
    run_ffmpeg_async,
)


def test_extract_av_warning_items_classifies_known_timestamp_warnings() -> None:
    stderr_text = """
    [mp4 @ 0x123] Non-monotonic DTS in output stream
    [aac @ 0x456] Queue input is backward in time
    Past duration 0.123 too large
    invalid dropping
    """

    items = _extract_av_warning_items(stderr_text)

    assert [item["type"] for item in items] == [
        "non_monotonic_dts",
        "queue_input_backward",
        "past_duration",
        "invalid_dropping",
    ]


def test_stall_detector_reports_unchanged_progress_after_timeout() -> None:
    detector = _StallDetector(timeout_sec=10)
    snapshot = _StallSnapshot(marker=12.5, output_size=1024)

    assert detector.update(snapshot, 100.0) is None
    assert detector.update(snapshot, 109.9) is None
    assert detector.update(snapshot, 110.0) == 10.0


def test_stall_detector_resets_when_progress_changes() -> None:
    detector = _StallDetector(timeout_sec=10)

    assert detector.update(_StallSnapshot(marker=1.0, output_size=1024), 100.0) is None
    assert detector.update(_StallSnapshot(marker=2.0, output_size=1024), 109.0) is None
    assert detector.update(_StallSnapshot(marker=2.0, output_size=1024), 118.0) is None
    assert detector.update(_StallSnapshot(marker=2.0, output_size=1024), 119.0) == 10.0


def test_stall_detector_ignores_empty_snapshot() -> None:
    detector = _StallDetector(timeout_sec=10)
    snapshot = _StallSnapshot(marker=None, output_size=None)

    assert detector.update(snapshot, 100.0) is None
    assert detector.update(snapshot, 200.0) is None


def test_run_ffmpeg_async_terminates_when_progress_stalls(tmp_path, monkeypatch) -> None:
    fake_ffmpeg = tmp_path / "ffmpeg-fake"
    fake_ffmpeg.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import time",
                "print('out_time_ms=1000000', flush=True)",
                "time.sleep(4)",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    fake_ffmpeg.chmod(0o755)

    monkeypatch.setenv("FFMPEG_STALL_TIMEOUT_SEC", "1")
    monkeypatch.setenv("FFMPEG_PROGRESS_LOG_INTERVAL_SEC", "1")

    with pytest.raises(subprocess.TimeoutExpired):
        asyncio.run(run_ffmpeg_async([str(fake_ffmpeg), str(tmp_path / "out.mp4")]))
