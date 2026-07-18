#!/usr/bin/env python3
"""Render a fixed short script in CPU and GPU modes and save measured results."""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT_DIR / "output" / "benchmarks"
MODES = (
    ("cpu", "cpu", "cpu"),
    ("gpu_cpu_filter", "gpu", "cpu"),
    ("gpu", "gpu", "cuda"),
)


def probe(path: Path) -> list[dict[str, object]]:
    completed = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)],
        check=True,
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
    )
    return json.loads(completed.stdout)["streams"]


def gpu_utilization() -> int | None:
    completed = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=utilization.gpu",
            "--format=csv,noheader,nounits",
        ],
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    if completed.returncode:
        return None
    try:
        return int(completed.stdout.strip().splitlines()[0])
    except (IndexError, ValueError):
        return None


def process_cpu_percent(pid: int) -> float | None:
    completed = subprocess.run(
        ["ps", "-o", "%cpu=", "-p", str(pid)],
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    try:
        return float(completed.stdout.strip())
    except ValueError:
        return None


def ffmpeg_process_count() -> int:
    completed = subprocess.run(
        ["pgrep", "-x", "ffmpeg"],
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    return len(completed.stdout.splitlines()) if completed.returncode == 0 else 0


def stream_timing(streams: list[dict[str, object]]) -> dict[str, float | None]:
    result: dict[str, float | None] = {}
    for kind in ("audio", "video"):
        stream = next((item for item in streams if item.get("codec_type") == kind), {})
        for field in ("start_time", "duration"):
            value = stream.get(field)
            try:
                result[f"{kind}_{field}_seconds"] = float(value)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                result[f"{kind}_{field}_seconds"] = None
    audio_start = result["audio_start_time_seconds"]
    video_start = result["video_start_time_seconds"]
    result["av_start_offset_seconds"] = (
        round(float(audio_start) - float(video_start), 6)
        if audio_start is not None and video_start is not None
        else None
    )
    return result


def run_mode(name: str, encoder: str, filter_mode: str) -> dict[str, object]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output = OUTPUT_DIR / f"smoke-{name}.mp4"
    env = {**os.environ, "HW_FILTER_MODE": filter_mode, "FFMPEG_PROFILE_MODE": "1"}
    command = [
        "zundamotion",
        "scripts/smoke_minimal.yaml",
        "-o",
        str(output),
        "--no-cache",
        "--hw-encoder",
        encoder,
        "--quality",
        "speed",
        "--jobs",
        "1",
        "--log-kv",
    ]
    started = time.monotonic()
    process = subprocess.Popen(
        command,
        cwd=ROOT_DIR,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
    )
    samples: list[dict[str, float | int | None]] = []
    stop_sampling = threading.Event()

    def sample() -> None:
        while not stop_sampling.wait(0.5):
            samples.append(
                {
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    "gpu_utilization_percent": gpu_utilization(),
                    "renderer_cpu_percent": process_cpu_percent(process.pid),
                    "ffmpeg_processes": ffmpeg_process_count(),
                }
            )

    sampler = threading.Thread(target=sample, daemon=True)
    sampler.start()
    stdout, _ = process.communicate()
    stop_sampling.set()
    sampler.join(timeout=2)
    log_path = output.with_suffix(".log")
    log_path.write_text(stdout, encoding="utf-8")
    if process.returncode:
        return {
            "mode": name,
            "encoder_request": encoder,
            "filter_mode_request": filter_mode,
            "success": False,
            "exit_code": process.returncode,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "log": str(log_path),
            "gpu_utilization_percent_peak": max(
                (int(item["gpu_utilization_percent"]) for item in samples if item["gpu_utilization_percent"] is not None),
                default=None,
            ),
            "renderer_cpu_percent_peak": max(
                (float(item["renderer_cpu_percent"]) for item in samples if item["renderer_cpu_percent"] is not None),
                default=None,
            ),
            "ffmpeg_process_count_peak": max(
                (int(item["ffmpeg_processes"]) for item in samples), default=0
            ),
            "resource_samples": samples,
        }
    streams = probe(output)
    gpu_samples = [item["gpu_utilization_percent"] for item in samples]
    cpu_samples = [item["renderer_cpu_percent"] for item in samples]
    return {
        "mode": name,
        "encoder_request": encoder,
        "filter_mode_request": filter_mode,
        "success": True,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "output": str(output),
        "size_bytes": output.stat().st_size,
        "streams": streams,
        "stream_timing": stream_timing(streams),
        "gpu_utilization_percent_peak": max(
            (int(value) for value in gpu_samples if value is not None), default=None
        ),
        "renderer_cpu_percent_peak": max(
            (float(value) for value in cpu_samples if value is not None), default=None
        ),
        "ffmpeg_process_count_peak": max(
            (int(item["ffmpeg_processes"]) for item in samples), default=0
        ),
        "resource_samples": samples,
        "dts_warnings": sum(
            token in stdout.lower()
            for token in ("non-monotonic dts", "non monotonically increasing dts")
        ),
        "log": str(log_path),
    }


def main() -> int:
    results = [run_mode(*mode) for mode in MODES]
    result_path = OUTPUT_DIR / "cpu-gpu-fixed-benchmark.json"
    result_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Benchmark results: {result_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
