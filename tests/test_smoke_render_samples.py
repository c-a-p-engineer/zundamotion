from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SMOKE_SCRIPTS = [
    "scripts/smoke_minimal.yaml",
]

FULL_SMOKE_SCRIPTS = [
    "scripts/sample.yaml",
    "scripts/sample_character_enter.yaml",
    "scripts/sample_character_move.yaml",
    "scripts/sample_transitions.yaml",
    "scripts/sample_badge.yaml",
    "scripts/sample_subtitle_render_modes.yaml",
    "scripts/sample_vertical.yaml",
    "scripts/refactor_validation_check.yaml",
]


def _smoke_enabled() -> bool:
    return os.getenv("ZUNDAMOTION_RUN_SMOKE", "").strip() == "1"


def _smoke_scripts() -> list[str]:
    scripts = list(SMOKE_SCRIPTS)
    if os.getenv("ZUNDAMOTION_RUN_FULL_SMOKE", "").strip() == "1":
        scripts.extend(FULL_SMOKE_SCRIPTS)
    return scripts


def _smoke_timeout_seconds() -> int:
    try:
        return max(60, int(os.getenv("ZUNDAMOTION_SMOKE_TIMEOUT", "600")))
    except Exception:
        return 600


def _tail_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")[-4000:]
    return str(value)[-4000:]


def _valid_output(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size <= 0:
        return False
    try:
        metadata = _run_ffprobe(path)
    except Exception:
        return False
    duration = float(metadata.get("format", {}).get("duration") or 0.0)
    streams = metadata.get("streams") or []
    return (
        duration > 0.0
        and any(stream.get("codec_type") == "video" for stream in streams)
        and any(stream.get("codec_type") == "audio" for stream in streams)
    )


def _stop_process(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def _run_ffprobe(output_path: Path) -> dict:
    proc = subprocess.run(
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
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


@pytest.mark.smoke
@pytest.mark.skipif(not _smoke_enabled(), reason="set ZUNDAMOTION_RUN_SMOKE=1")
@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is required")
@pytest.mark.skipif(shutil.which("ffprobe") is None, reason="ffprobe is required")
@pytest.mark.parametrize("script_path", _smoke_scripts())
def test_sample_script_renders_valid_mp4(script_path: str, tmp_path: Path) -> None:
    script = ROOT / script_path
    assert script.is_file(), f"missing smoke sample: {script_path}"

    output_dir = ROOT / "output" / "test_smoke"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{script.stem}.mp4"
    if output_path.exists():
        output_path.unlink()

    env = os.environ.copy()
    env.setdefault("DISABLE_HWENC", "1")
    env.setdefault("HW_FILTER_MODE", "cpu")
    env.setdefault("USE_RAMDISK", "0")
    env.setdefault("MPLCONFIGDIR", str(tmp_path / "mplconfig"))

    command = [
        sys.executable,
        "-m",
        "zundamotion.main",
        script_path,
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
    proc = subprocess.Popen(
        command,
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + _smoke_timeout_seconds()
    output_valid = False
    while time.monotonic() < deadline:
        if _valid_output(output_path):
            output_valid = True
            _stop_process(proc)
            break
        if proc.poll() is not None:
            break
        time.sleep(1.0)

    if proc.poll() is None:
        _stop_process(proc)
    if not output_valid:
        if proc.returncode != 0:
            assert False, f"render failed: {script_path}"
        assert _valid_output(output_path), f"output was not valid: {output_path}"

    metadata = _run_ffprobe(output_path)
    duration = float(metadata.get("format", {}).get("duration") or 0.0)
    streams = metadata.get("streams") or []
    assert duration > 0.0
    assert any(stream.get("codec_type") == "video" for stream in streams)
    assert any(stream.get("codec_type") == "audio" for stream in streams)
