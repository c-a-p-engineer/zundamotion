from __future__ import annotations

from types import SimpleNamespace

from zundamotion.components.pipeline_phases.video_phase import VideoPhase
from zundamotion.components.pipeline_phases.video_phase.reliability import ReliableVideoPhase
from zundamotion.components.pipeline_phases.video_phase import reliability


def _phase(*, jobs: str = "auto", hw_kind=None, clip_workers: int = 2) -> ReliableVideoPhase:
    phase = ReliableVideoPhase.__new__(ReliableVideoPhase)
    phase.jobs = jobs
    phase.hw_kind = hw_kind
    phase.clip_workers = clip_workers
    phase.video_renderer = SimpleNamespace(clip_workers=clip_workers)
    return phase


def _overlay_scene() -> list[dict]:
    return [
        {
            "id": "overlay",
            "lines": [
                {
                    "characters": [
                        {"name": "copetan", "visible": True},
                    ]
                }
            ],
        }
    ]


def test_public_video_phase_uses_reliability_policy() -> None:
    assert VideoPhase is ReliableVideoPhase


def test_auto_cpu_overlay_scene_serializes_clip_processes(monkeypatch) -> None:
    monkeypatch.setattr(reliability, "get_hw_filter_mode", lambda: "cpu")
    phase = _phase()

    phase._apply_initial_worker_backoff(_overlay_scene())

    assert phase.clip_workers == 1
    assert phase.video_renderer.clip_workers == 1


def test_auto_cpu_simple_scene_keeps_existing_parallelism(monkeypatch) -> None:
    monkeypatch.setattr(reliability, "get_hw_filter_mode", lambda: "cpu")
    phase = _phase()

    phase._apply_initial_worker_backoff([{"id": "simple", "lines": [{"wait": 1.0}]}])

    assert phase.clip_workers == 2
    assert phase.video_renderer.clip_workers == 2


def test_explicit_jobs_remains_user_controlled(monkeypatch) -> None:
    monkeypatch.setattr(reliability, "get_hw_filter_mode", lambda: "cpu")
    phase = _phase(jobs="2")

    phase._apply_initial_worker_backoff(_overlay_scene())

    assert phase.clip_workers == 2


def test_nvenc_encoder_keeps_cpu_overlay_process_parallelism(monkeypatch) -> None:
    monkeypatch.setattr(reliability, "get_hw_filter_mode", lambda: "cpu")
    phase = _phase(hw_kind="nvenc")

    phase._apply_initial_worker_backoff(_overlay_scene())

    assert phase.clip_workers == 2
