from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "tools" / "zundamotion_cold_warm_benchmark.py"
)
SPEC = importlib.util.spec_from_file_location("zundamotion_cold_warm_benchmark", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_metric_snapshot_extracts_comparable_values() -> None:
    summary = {
        "run_id": "run-1",
        "phase_ms": {"VideoPhase": 1200, "AudioPhase": "400.5"},
        "video_line_clip_ms": 800,
        "subtitle_burn_ms": 200,
        "scene_concat_ms": 50,
        "ffmpeg_calls": 12,
        "ffprobe_calls": 18,
        "cache_hit": 3,
        "cache_miss": 4,
        "cache_write": 5,
        "av_warnings": {"total": 0},
        "line_clip": {
            "line_clip_count": 7,
            "line_clip_p50_ms": 100,
            "line_clip_p95_ms": 300,
        },
    }

    snapshot = MODULE.metric_snapshot(summary)

    assert snapshot["run_id"] == "run-1"
    assert snapshot["phase_ms"] == {"AudioPhase": 400.5, "VideoPhase": 1200.0}
    assert snapshot["line_clip_count"] == 7
    assert snapshot["line_clip_p50_ms"] == 100.0
    assert snapshot["line_clip_p95_ms"] == 300.0
    assert snapshot["ffmpeg_calls"] == 12
    assert snapshot["ffprobe_calls"] == 18
    assert snapshot["cache_miss"] == 4
    assert snapshot["av_warnings_total"] == 0


def test_build_comparison_keeps_cold_and_two_warm_trials_distinct() -> None:
    trials = [
        {
            "name": "cold",
            "elapsed_seconds": 30.0,
            "metrics": {"cache_miss": 20, "ffmpeg_calls": 30, "ffprobe_calls": 40},
        },
        {
            "name": "warm1",
            "elapsed_seconds": 10.0,
            "metrics": {"cache_miss": 2, "ffmpeg_calls": 5, "ffprobe_calls": 8},
        },
        {
            "name": "warm2",
            "elapsed_seconds": 9.0,
            "metrics": {"cache_miss": 1, "ffmpeg_calls": 4, "ffprobe_calls": 7},
        },
    ]

    comparison = MODULE.build_comparison(trials)

    assert comparison["warm1_vs_cold_ratio"] == 0.333333
    assert comparison["warm2_vs_cold_ratio"] == 0.3
    assert comparison["warm_stability_ratio"] == 0.9
    assert comparison["cold_cache_miss"] == 20
    assert comparison["warm2_cache_miss"] == 1
    assert comparison["cold_ffmpeg_calls"] == 30
    assert comparison["warm2_ffprobe_calls"] == 7


def test_safe_ratio_returns_none_for_zero_baseline() -> None:
    assert MODULE._safe_ratio(1.0, 0.0) is None
