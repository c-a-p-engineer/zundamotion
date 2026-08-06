#!/usr/bin/env python3
"""Run one cold and two warm Zundamotion renders under fixed conditions.

The cold run uses ``--cache-refresh`` so only cache entries touched by the
selected script are regenerated. The following two runs reuse those entries.
Each run's raw PerfSummary and a compact comparison are written as JSON.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_SUMMARY_PATH = ROOT_DIR / "output" / "perf" / "perf_summary.json"
SCHEMA_VERSION = 1


def _safe_ratio(numerator: float, denominator: float) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 6)


def _number(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def metric_snapshot(summary: dict[str, Any]) -> dict[str, Any]:
    """Extract stable comparison fields from a PerfSummary payload."""

    line_clip = summary.get("line_clip") or {}
    phase_ms = summary.get("phase_ms") or {}
    return {
        "run_id": summary.get("run_id"),
        "phase_ms": {
            str(name): _number(elapsed_ms)
            for name, elapsed_ms in sorted(phase_ms.items())
        },
        "video_line_clip_ms": _number(summary.get("video_line_clip_ms")),
        "subtitle_burn_ms": _number(summary.get("subtitle_burn_ms")),
        "scene_concat_ms": _number(summary.get("scene_concat_ms")),
        "line_clip_count": int(line_clip.get("line_clip_count", 0) or 0),
        "line_clip_p50_ms": _number(line_clip.get("line_clip_p50_ms")),
        "line_clip_p95_ms": _number(line_clip.get("line_clip_p95_ms")),
        "ffmpeg_calls": int(summary.get("ffmpeg_calls", 0) or 0),
        "ffprobe_calls": int(summary.get("ffprobe_calls", 0) or 0),
        "cache_hit": int(summary.get("cache_hit", 0) or 0),
        "cache_miss": int(summary.get("cache_miss", 0) or 0),
        "cache_write": int(summary.get("cache_write", 0) or 0),
        "av_warnings_total": int(
            ((summary.get("av_warnings") or {}).get("total", 0)) or 0
        ),
    }


def build_comparison(trials: list[dict[str, Any]]) -> dict[str, Any]:
    """Build deterministic cold/warm comparison values."""

    by_name = {str(item["name"]): item for item in trials}
    cold = by_name["cold"]
    warm1 = by_name["warm1"]
    warm2 = by_name["warm2"]
    cold_elapsed = _number(cold.get("elapsed_seconds"))
    warm1_elapsed = _number(warm1.get("elapsed_seconds"))
    warm2_elapsed = _number(warm2.get("elapsed_seconds"))
    return {
        "cold_elapsed_seconds": cold_elapsed,
        "warm1_elapsed_seconds": warm1_elapsed,
        "warm2_elapsed_seconds": warm2_elapsed,
        "warm1_vs_cold_ratio": _safe_ratio(warm1_elapsed, cold_elapsed),
        "warm2_vs_cold_ratio": _safe_ratio(warm2_elapsed, cold_elapsed),
        "warm_stability_ratio": _safe_ratio(warm2_elapsed, warm1_elapsed),
        "cold_cache_miss": int(cold["metrics"].get("cache_miss", 0)),
        "warm1_cache_miss": int(warm1["metrics"].get("cache_miss", 0)),
        "warm2_cache_miss": int(warm2["metrics"].get("cache_miss", 0)),
        "cold_ffmpeg_calls": int(cold["metrics"].get("ffmpeg_calls", 0)),
        "warm2_ffmpeg_calls": int(warm2["metrics"].get("ffmpeg_calls", 0)),
        "cold_ffprobe_calls": int(cold["metrics"].get("ffprobe_calls", 0)),
        "warm2_ffprobe_calls": int(warm2["metrics"].get("ffprobe_calls", 0)),
    }


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run_trial(
    *,
    name: str,
    script_path: Path,
    output_dir: Path,
    summary_path: Path,
    hw_encoder: str,
    quality: str,
    jobs: str,
    no_voice: bool,
    refresh_cache: bool,
) -> dict[str, Any]:
    output_path = output_dir / f"{name}.mp4"
    log_path = output_dir / f"{name}.log"
    raw_summary_path = output_dir / f"{name}-perf-summary.json"
    command = [
        sys.executable,
        "-m",
        "zundamotion.main",
        str(script_path),
        "-o",
        str(output_path),
        "--hw-encoder",
        hw_encoder,
        "--quality",
        quality,
        "--jobs",
        jobs,
        "--log-kv",
    ]
    if no_voice:
        command.append("--no-voice")
    if refresh_cache:
        command.append("--cache-refresh")

    env = dict(os.environ)
    env.setdefault("USE_RAMDISK", "0")
    if hw_encoder == "cpu":
        env["DISABLE_HWENC"] = "1"
        env["HW_FILTER_MODE"] = "cpu"

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
    elapsed = round(time.monotonic() - started, 3)
    log_path.write_text(completed.stdout, encoding="utf-8")
    if completed.returncode != 0:
        raise RuntimeError(
            f"Benchmark trial {name!r} failed with exit code "
            f"{completed.returncode}. See {log_path}."
        )
    if not summary_path.is_file():
        raise FileNotFoundError(
            f"PerfSummary was not written after trial {name!r}: {summary_path}"
        )

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    raw_summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return {
        "name": name,
        "cache_mode": "refresh" if refresh_cache else "reuse",
        "success": True,
        "elapsed_seconds": elapsed,
        "command": command,
        "output": str(output_path),
        "output_size_bytes": output_path.stat().st_size,
        "log": str(log_path),
        "raw_perf_summary": str(raw_summary_path),
        "metrics": metric_snapshot(summary),
    }


def run_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    script_path = Path(args.script)
    if not script_path.is_absolute():
        script_path = (ROOT_DIR / script_path).resolve()
    if not script_path.is_file():
        raise FileNotFoundError(f"Script does not exist: {script_path}")

    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = (ROOT_DIR / output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    summary_path = Path(args.summary_json)
    if not summary_path.is_absolute():
        summary_path = (ROOT_DIR / summary_path).resolve()

    common = {
        "script_path": script_path,
        "output_dir": output_dir,
        "summary_path": summary_path,
        "hw_encoder": args.hw_encoder,
        "quality": args.quality,
        "jobs": args.jobs,
        "no_voice": args.no_voice,
    }
    trials = [
        _run_trial(name="cold", refresh_cache=True, **common),
        _run_trial(name="warm1", refresh_cache=False, **common),
        _run_trial(name="warm2", refresh_cache=False, **common),
    ]
    runtime_lock = ROOT_DIR / ".devcontainer" / "runtime.lock.json"
    result = {
        "schema_version": SCHEMA_VERSION,
        "script": str(script_path),
        "script_sha256": _sha256(script_path),
        "runtime_lock": str(runtime_lock),
        "runtime_lock_sha256": _sha256(runtime_lock),
        "conditions": {
            "hw_encoder": args.hw_encoder,
            "quality": args.quality,
            "jobs": args.jobs,
            "no_voice": bool(args.no_voice),
            "python": sys.version,
        },
        "trials": trials,
        "comparison": build_comparison(trials),
    }
    result_path = output_dir / "cold-warm-benchmark.json"
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("script", help="YAML script path relative to the repository root")
    parser.add_argument(
        "--output-dir",
        default="output/benchmarks/cold-warm",
        help="Directory for rendered videos, logs, summaries, and comparison JSON",
    )
    parser.add_argument(
        "--summary-json",
        default=str(DEFAULT_SUMMARY_PATH.relative_to(ROOT_DIR)),
        help="PerfSummary JSON path configured by the selected script",
    )
    parser.add_argument("--hw-encoder", default="cpu", choices=("auto", "cpu", "gpu"))
    parser.add_argument(
        "--quality", default="speed", choices=("speed", "balanced", "quality")
    )
    parser.add_argument("--jobs", default="1")
    parser.add_argument("--no-voice", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = run_benchmark(args)
    output_dir = Path(args.output_dir)
    print(output_dir / "cold-warm-benchmark.json")
    return 0 if all(item["success"] for item in result["trials"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
