from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "smoke_wait_stability.yaml"
ITERATIONS = 5
PER_RUN_TIMEOUT_SECONDS = 60


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is required")
@pytest.mark.skipif(shutil.which("ffprobe") is None, reason="ffprobe is required")
def test_cpu_wait_render_is_bounded_across_repeated_runs(tmp_path: Path) -> None:
    assert SCRIPT.is_file()
    env = os.environ.copy()
    env["DISABLE_HWENC"] = "1"
    env["HW_FILTER_MODE"] = "cpu"
    env["USE_RAMDISK"] = "0"
    env["FFMPEG_RUN_TIMEOUT_SEC"] = "45"
    env["FFMPEG_STALL_TIMEOUT_SEC"] = "30"

    for iteration in range(ITERATIONS):
        output_path = tmp_path / f"wait-stability-{iteration}.mp4"
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
            f"iteration={iteration}\nstdout:\n{result.stdout[-4000:]}\n"
            f"stderr:\n{result.stderr[-4000:]}"
        )
        assert output_path.is_file() and output_path.stat().st_size > 0

        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-show_streams",
                "-of",
                "json",
                str(output_path),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert probe.returncode == 0, probe.stderr
        metadata = json.loads(probe.stdout)
        streams = metadata.get("streams") or []
        assert any(item.get("codec_type") == "video" for item in streams)
        assert any(item.get("codec_type") == "audio" for item in streams)
        duration = float((metadata.get("format") or {}).get("duration") or 0.0)
        assert 0.6 <= duration <= 1.2
