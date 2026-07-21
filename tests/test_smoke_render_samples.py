from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

from zundamotion.utils.export_presets import EXPORT_PRESETS


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


def _stop_process(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def _read_tail(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")[-4000:]
    except Exception as exc:
        return f"<failed to read {path}: {exc}>"


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


def _first_line(command: list[str]) -> str:
    return subprocess.check_output(command, cwd=ROOT, text=True).splitlines()[0]


def _write_performance_baseline(
    *, script_path: str, output_path: Path, metadata: dict, elapsed_seconds: float
) -> None:
    perf_path = ROOT / "output" / "perf" / "perf_summary.json"
    perf = json.loads(perf_path.read_text(encoding="utf-8")) if perf_path.is_file() else {}
    video = next(stream for stream in metadata["streams"] if stream.get("codec_type") == "video")
    baseline = {
        "run_id": perf.get("run_id"),
        "python_version": sys.version.split()[0],
        "ffmpeg_version": _first_line(["ffmpeg", "-version"]),
        "render_path": "cpu",
        "input_script": script_path,
        "output": {
            "width": video.get("width"),
            "height": video.get("height"),
            "fps": video.get("avg_frame_rate"),
            "duration": float(metadata.get("format", {}).get("duration") or 0.0),
            "size_bytes": output_path.stat().st_size,
        },
        "total_wall_seconds": round(elapsed_seconds, 3),
        "phase_ms": perf.get("phase_ms", {}),
        "ffmpeg_calls": perf.get("ffmpeg_calls", 0),
        "ffprobe_calls": perf.get("ffprobe_calls", 0),
        "cache_hit": perf.get("cache_hit", 0),
        "cache_miss": perf.get("cache_miss", 0),
        "subtitle_burn_ms": perf.get("subtitle_burn_ms", 0.0),
        "line_clips": perf.get("line_clips", 0),
        "scene_concat_ms": perf.get("scene_concat_ms", 0.0),
        "ffprobe": metadata,
    }
    (ROOT / "output" / "test_smoke" / "performance-baseline.json").write_text(
        json.dumps(baseline, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _expected_video(script: Path) -> tuple[int, int, int]:
    data = yaml.safe_load(script.read_text(encoding="utf-8")) or {}
    video = dict(EXPORT_PRESETS.get(str(data.get("export_preset", "")).lower(), {}).get("video", {}))
    video.update(data.get("video", {}) or {})
    return int(video.get("width", 1920)), int(video.get("height", 1080)), int(video.get("fps", 30))


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
    stdout_path = output_dir / f"{script.stem}.stdout.log"
    stderr_path = output_dir / f"{script.stem}.stderr.log"

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
    started_at = time.perf_counter()
    with stdout_path.open("w", encoding="utf-8") as stdout_f, stderr_path.open(
        "w", encoding="utf-8"
    ) as stderr_f:
        proc = subprocess.Popen(
            command,
            cwd=ROOT,
            env=env,
            stdout=stdout_f,
            stderr=stderr_f,
            text=True,
        )
        try:
            proc.wait(timeout=_smoke_timeout_seconds())
        except subprocess.TimeoutExpired:
            _stop_process(proc)
            pytest.fail(
                f"render timed out: {script_path}\n"
                f"stdout tail:\n{_read_tail(stdout_path)}\n"
                f"stderr tail:\n{_read_tail(stderr_path)}"
            )
    if proc.returncode != 0:
        details = (
            f"command: {' '.join(command)}\n"
            f"returncode: {proc.returncode}\n"
            f"stdout tail:\n{_read_tail(stdout_path)}\n"
            f"stderr tail:\n{_read_tail(stderr_path)}"
        )
        pytest.fail(f"render failed: {script_path}\n{details}")

    assert output_path.is_file() and output_path.stat().st_size > 0
    metadata = _run_ffprobe(output_path)
    (output_dir / "ffprobe-result.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _write_performance_baseline(
        script_path=script_path,
        output_path=output_path,
        metadata=metadata,
        elapsed_seconds=time.perf_counter() - started_at,
    )
    duration = float(metadata.get("format", {}).get("duration") or 0.0)
    streams = metadata.get("streams") or []
    assert duration > 0.0
    assert any(stream.get("codec_type") == "video" for stream in streams)
    assert any(stream.get("codec_type") == "audio" for stream in streams)
    video_stream = next(stream for stream in streams if stream.get("codec_type") == "video")
    audio_stream = next(stream for stream in streams if stream.get("codec_type") == "audio")
    expected_width, expected_height, expected_fps = _expected_video(script)
    assert (video_stream["width"], video_stream["height"]) == (
        expected_width,
        expected_height,
    )
    assert video_stream["avg_frame_rate"] == f"{expected_fps}/1"
    assert audio_stream["codec_name"] == "aac"
    assert int(audio_stream["sample_rate"]) == 48000
    assert int(audio_stream["channels"]) == 2
    video_start = float(video_stream.get("start_time") or 0.0)
    audio_start = float(audio_stream.get("start_time") or 0.0)
    assert abs(video_start - audio_start) <= 0.1
    video_duration = float(video_stream.get("duration") or duration)
    audio_duration = float(audio_stream.get("duration") or duration)
    assert abs(video_duration - audio_duration) <= 0.1
    stderr_text = stderr_path.read_text(encoding="utf-8", errors="replace").lower()
    assert "non-monotonic dts" not in stderr_text
    assert "non monotonically increasing dts" not in stderr_text
