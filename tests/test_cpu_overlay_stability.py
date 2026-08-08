from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "smoke_minimal.yaml"
ITERATIONS = 3
PER_RUN_TIMEOUT_SECONDS = 60


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is required")
@pytest.mark.skipif(shutil.which("ffprobe") is None, reason="ffprobe is required")
def test_cpu_overlay_render_is_bounded_across_repeated_runs(tmp_path: Path) -> None:
    """Exercise the exact character/mouth overlay graph that previously stalled."""
    env = os.environ.copy()
    env["DISABLE_HWENC"] = "1"
    env["HW_FILTER_MODE"] = "cpu"
    env["USE_RAMDISK"] = "0"
    env["FFMPEG_RUN_TIMEOUT_SEC"] = "45"
    env["FFMPEG_STALL_TIMEOUT_SEC"] = "30"
    env["FFMPEG_PROGRESS_LOG_INTERVAL_SEC"] = "5"
    env.pop("FFMPEG_FILTER_COMPLEX_THREADS", None)

    for iteration in range(ITERATIONS):
        output_path = tmp_path / f"cpu-overlay-{iteration}.mp4"
        command = [
            sys.executable,
            "-m",
            "zundamotion.main",
            str(SCRIPT.relative_to(ROOT)),
            "--project-root",
            str(ROOT),
            "--no-voice",
            "--no-cache",
            "--hw-encoder",
            "cpu",
            "--jobs",
            "auto",
            "--quality",
            "speed",
            "-o",
            str(output_path),
        ]
        result = subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=PER_RUN_TIMEOUT_SECONDS,
            check=False,
        )
        assert result.returncode == 0, (
            f"iteration={iteration}\nstdout:\n{result.stdout[-6000:]}\n"
            f"stderr:\n{result.stderr[-6000:]}"
        )
        assert output_path.is_file() and output_path.stat().st_size > 0
        assert "filter_complex_threads=1" in result.stderr or "filter_complex_threads=1" in result.stdout
