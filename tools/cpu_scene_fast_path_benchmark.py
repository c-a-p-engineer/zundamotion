#!/usr/bin/env python3
"""Compare the standard CPU scene renderer with the opt-in simple fast path."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_SCRIPT = ROOT_DIR / "scripts" / "benchmark_cpu_scene_fast_path.yaml"
DEFAULT_SUMMARY = ROOT_DIR / "output" / "perf" / "perf_summary.json"
SCHEMA_VERSION = 1
CPU_FAST_PATH_ENV = "ZUNDAMOTION_CPU_SCENE_FAST_PATH"


def _run(command: list[str], *, env: dict[str, str], binary: bool = False) -> bytes | str:
    completed = subprocess.run(
        command,
        cwd=ROOT_DIR,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace")[-5000:]
        stdout = completed.stdout.decode("utf-8", errors="replace")[-5000:]
        raise RuntimeError(
            f"command failed ({completed.returncode}): {' '.join(command)}\n{stdout}\n{stderr}"
        )
    if binary:
        return completed.stdout
    return completed.stdout.decode("utf-8", errors="replace")


def _semantic_probe(path: Path, env: dict[str, str]) -> dict[str, Any]:
    raw = _run(
        [
            "ffprobe", "-v", "error", "-show_entries",
            "format=duration:stream=index,codec_type,codec_name,width,height,avg_frame_rate,"
            "r_frame_rate,sample_rate,channels,channel_layout,duration,nb_frames",
            "-of", "json", str(path),
        ],
        env=env,
    )
    return json.loads(str(raw))


def _decoded_hash(path: Path, stream: str, env: dict[str, str]) -> str:
    if stream == "video":
        command = [
            "ffmpeg", "-v", "error", "-i", str(path), "-map", "0:v:0",
            "-f", "framemd5", "-",
        ]
    else:
        command = [
            "ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0",
            "-f", "s16le", "-acodec", "pcm_s16le", "-",
        ]
    payload = _run(command, env=env, binary=True)
    return hashlib.sha256(payload).hexdigest()


def _number(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _perf_snapshot(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "total_wall_ms": _number(summary.get("total_wall_ms")),
        "video_phase_ms": _number((summary.get("phase_ms") or {}).get("VideoPhase")),
        "ffmpeg_calls": int(summary.get("ffmpeg_calls", 0) or 0),
        "ffprobe_calls": int(summary.get("ffprobe_calls", 0) or 0),
        "cache_hit": int(summary.get("cache_hit", 0) or 0),
        "cache_miss": int(summary.get("cache_miss", 0) or 0),
        "cache_write": int(summary.get("cache_write", 0) or 0),
        "av_warnings_total": int(((summary.get("av_warnings") or {}).get("total", 0)) or 0),
    }


def _run_trial(
    *, name: str, mode: str, iteration: int, script: Path,
    output_dir: Path, summary_path: Path,
) -> dict[str, Any]:
    output = output_dir / f"{name}.mp4"
    log_path = output_dir / f"{name}.log"
    perf_path = output_dir / f"{name}-perf-summary.json"
    command = [
        sys.executable, "-m", "zundamotion.main", str(script), "-o", str(output),
        "--hw-encoder", "cpu", "--quality", "speed", "--jobs", "1",
        "--no-cache", "--no-voice", "--log-kv",
    ]
    env = dict(os.environ)
    env.update(
        {
            "DISABLE_HWENC": "1",
            "HW_FILTER_MODE": "cpu",
            "USE_RAMDISK": "0",
            CPU_FAST_PATH_ENV: "1" if mode == "fast" else "0",
        }
    )
    started = time.monotonic()
    completed = subprocess.run(
        command,
        cwd=ROOT_DIR,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    elapsed = round(time.monotonic() - started, 4)
    log_path.write_text(completed.stdout, encoding="utf-8")
    if completed.returncode != 0:
        raise RuntimeError(
            f"trial {name!r} failed with exit code {completed.returncode}; see {log_path}"
        )
    if not summary_path.is_file():
        raise FileNotFoundError(f"PerfSummary was not written: {summary_path}")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    perf_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    if mode == "standard":
        path_evidence = "skipping simple fast path (cpu_encoder)" in completed.stdout
    else:
        path_evidence = "rendered via simple fast path" in completed.stdout
    return {
        "name": name,
        "mode": mode,
        "iteration": iteration,
        "elapsed_seconds": elapsed,
        "path_selection_verified": path_evidence,
        "output": str(output),
        "output_size_bytes": output.stat().st_size,
        "log": str(log_path),
        "perf_summary": str(perf_path),
        "metrics": _perf_snapshot(summary),
    }


def _median(trials: list[dict[str, Any]], field: str) -> float:
    values = []
    for trial in trials:
        if field == "elapsed_seconds":
            values.append(float(trial[field]))
        else:
            values.append(float(trial["metrics"].get(field, 0.0) or 0.0))
    return round(statistics.median(values), 4) if values else 0.0


def _ratio(fast: float, standard: float) -> float | None:
    if standard <= 0:
        return None
    return round(fast / standard, 6)


def run_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    script = args.script.resolve()
    output_dir = args.output_dir.resolve()
    summary_path = args.summary_json.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    if not script.is_file():
        raise FileNotFoundError(script)

    trials: list[dict[str, Any]] = []
    for iteration in range(1, args.runs + 1):
        for mode in ("standard", "fast"):
            trials.append(
                _run_trial(
                    name=f"{iteration:02d}-{mode}", mode=mode, iteration=iteration,
                    script=script, output_dir=output_dir, summary_path=summary_path,
                )
            )

    standard_trials = [item for item in trials if item["mode"] == "standard"]
    fast_trials = [item for item in trials if item["mode"] == "fast"]
    standard_output = Path(standard_trials[-1]["output"])
    fast_output = Path(fast_trials[-1]["output"])
    probe_env = dict(os.environ)
    probe_env.setdefault("USE_RAMDISK", "0")
    semantic_standard = _semantic_probe(standard_output, probe_env)
    semantic_fast = _semantic_probe(fast_output, probe_env)
    standard_video_hash = _decoded_hash(standard_output, "video", probe_env)
    fast_video_hash = _decoded_hash(fast_output, "video", probe_env)
    standard_audio_hash = _decoded_hash(standard_output, "audio", probe_env)
    fast_audio_hash = _decoded_hash(fast_output, "audio", probe_env)

    standard_elapsed = _median(standard_trials, "elapsed_seconds")
    fast_elapsed = _median(fast_trials, "elapsed_seconds")
    standard_video_phase = _median(standard_trials, "video_phase_ms")
    fast_video_phase = _median(fast_trials, "video_phase_ms")
    elapsed_ratio = _ratio(fast_elapsed, standard_elapsed)
    video_phase_ratio = _ratio(fast_video_phase, standard_video_phase)
    path_selection_verified = all(bool(item["path_selection_verified"]) for item in trials)
    semantic_equal = semantic_standard == semantic_fast
    decoded_video_equal = standard_video_hash == fast_video_hash
    decoded_audio_equal = standard_audio_hash == fast_audio_hash
    media_exact_equal = semantic_equal and decoded_video_equal and decoded_audio_equal
    meaningful_improvement = bool(
        elapsed_ratio is not None and elapsed_ratio <= 0.90
        and video_phase_ratio is not None and video_phase_ratio <= 0.90
    )
    adopt = path_selection_verified and media_exact_equal and meaningful_improvement

    runtime_lock = ROOT_DIR / ".devcontainer" / "runtime.lock.json"
    result = {
        "schema_version": SCHEMA_VERSION,
        "script": str(script),
        "runtime_lock": str(runtime_lock),
        "conditions": {
            "runs_per_mode": args.runs,
            "hw_encoder": "cpu",
            "quality": "speed",
            "jobs": 1,
            "no_cache": True,
            "no_voice": True,
            "cpu_fast_path_flag_default": "0",
        },
        "trials": trials,
        "comparison": {
            "standard_median_elapsed_seconds": standard_elapsed,
            "fast_median_elapsed_seconds": fast_elapsed,
            "elapsed_fast_vs_standard_ratio": elapsed_ratio,
            "standard_median_video_phase_ms": standard_video_phase,
            "fast_median_video_phase_ms": fast_video_phase,
            "video_phase_fast_vs_standard_ratio": video_phase_ratio,
            "path_selection_verified": path_selection_verified,
            "semantic_probe_equal": semantic_equal,
            "decoded_video_framemd5_equal": decoded_video_equal,
            "decoded_audio_pcm_equal": decoded_audio_equal,
            "standard_video_framemd5_sha256": standard_video_hash,
            "fast_video_framemd5_sha256": fast_video_hash,
            "standard_audio_pcm_sha256": standard_audio_hash,
            "fast_audio_pcm_sha256": fast_audio_hash,
            "meaningful_improvement_threshold": "<=0.90 for wall and VideoPhase medians",
            "meaningful_improvement": meaningful_improvement,
            "media_exact_equal": media_exact_equal,
            "decision": "adopt" if adopt else "keep_standard",
        },
    }
    result_path = output_dir / "cpu-scene-fast-path-benchmark.json"
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--script", type=Path, default=DEFAULT_SCRIPT)
    parser.add_argument(
        "--output-dir", type=Path,
        default=ROOT_DIR / "output" / "benchmarks" / "cpu-scene-fast-path",
    )
    parser.add_argument("--summary-json", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--runs", type=int, default=3)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.runs < 1:
        raise SystemExit("--runs must be >= 1")
    result = run_benchmark(args)
    print(args.output_dir.resolve() / "cpu-scene-fast-path-benchmark.json")
    comparison = result["comparison"]
    # Slower-but-valid experiments are successful measurements with keep_standard.
    if not comparison["path_selection_verified"] or not comparison["semantic_probe_equal"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
