from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from zundamotion.pipeline_diagnostics import DiagnosticGenerationPipeline
from zundamotion.utils import perf_stats


def _pipeline(tmp_path: Path) -> DiagnosticGenerationPipeline:
    pipeline = DiagnosticGenerationPipeline.__new__(DiagnosticGenerationPipeline)
    pipeline.config = {
        "system": {
            "performance": {
                "summary_json": str(tmp_path / "perf-summary.json"),
            }
        }
    }
    pipeline.stats = {
        "phases": {},
        "total_duration": 0.0,
        "clips_processed": 0,
        "clip_durations": [],
    }
    pipeline.current_phase = None
    pipeline.failure_context = None
    return pipeline


def test_failed_phase_keeps_status_duration_and_error(tmp_path: Path) -> None:
    pipeline = _pipeline(tmp_path)
    perf = perf_stats.start_perf_stats()

    async def fail() -> None:
        raise RuntimeError("render exploded")

    with pytest.raises(RuntimeError, match="render exploded"):
        asyncio.run(pipeline._run_phase("VideoPhase", fail))

    phase = pipeline.stats["phases"]["VideoPhase"]
    assert phase["status"] == "failed"
    assert phase["duration"] >= 0
    assert phase["error_type"] == "RuntimeError"
    assert phase["error_message"] == "render exploded"
    assert pipeline.current_phase == "VideoPhase"
    assert pipeline.failure_context == {
        "phase": "VideoPhase",
        "status": "failed",
        "error_type": "RuntimeError",
        "error_message": "render exploded",
    }
    assert perf.to_dict()["phase_ms"]["VideoPhase"] >= 0


def test_failure_summary_contains_partial_perf_and_history(tmp_path: Path) -> None:
    pipeline = _pipeline(tmp_path)
    perf = perf_stats.start_perf_stats()
    perf.incr("ffmpeg_calls", 3)
    pipeline.stats["phases"]["AudioPhase"] = {
        "duration": 1.25,
        "status": "success",
    }
    pipeline.current_phase = "VideoPhase"
    pipeline.failure_context = {
        "phase": "VideoPhase",
        "status": "failed",
        "error_type": "RuntimeError",
        "error_message": "render exploded",
    }

    summary_path = pipeline.write_failure_summary(
        tmp_path / "output.mp4",
        RuntimeError("render exploded"),
    )

    assert summary_path == tmp_path / "perf-summary.json"
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["failure"]["phase"] == "VideoPhase"
    assert payload["failure"]["error_type"] == "RuntimeError"
    assert payload["phase_results"]["AudioPhase"]["status"] == "success"
    assert payload["ffmpeg_calls"] == 3

    history = tmp_path / f"perf-summary.{perf.run_id}.json"
    assert history.is_file()
    assert json.loads(history.read_text(encoding="utf-8")) == payload
