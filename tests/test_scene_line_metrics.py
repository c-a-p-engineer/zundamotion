from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from zundamotion.components.pipeline_phases.video_phase import scene_line_metrics
from zundamotion.components.pipeline_phases.video_phase.scene_line_context import (
    SceneLineContext,
)
from zundamotion.components.pipeline_phases.video_phase.scene_line_metrics import (
    SceneLineMetricsMixin,
    summarize_line_elapsed,
)
from zundamotion.components.pipeline_phases.video_phase.scene_talk_plan import (
    SceneTalkPlan,
)
from zundamotion.components.pipeline_phases.video_phase.scene_talk_renderer import (
    TalkRenderOutcome,
)


class _Subject(SceneLineMetricsMixin):
    def __init__(self, tmp_path: Path) -> None:
        self.phase = SimpleNamespace(
            auto_tune_enabled=True,
            parallel_scene_rendering=False,
            _profile_samples=[],
            profile_limit=2,
            _clip_samples_all=[],
            _retuned=False,
            clip_workers=1,
        )
        self.video_renderer = SimpleNamespace(clip_workers=1)
        self.cache_manager = SimpleNamespace(cache_dir=tmp_path)
        self.hw_kind = "cpu"
        self.saved_hint = None

    async def _write_line_autotune_hint(self, **kwargs):
        self.saved_hint = kwargs
        return self.cache_manager.cache_dir / "autotune_hint.json"


def _context() -> SceneLineContext:
    return SceneLineContext(
        line_index=3,
        line_id="demo_3",
        visual_container={},
        line_data={"type": "talk"},
        line_type="talk",
        duration=1.0,
        pre_duration=0.0,
        post_duration=0.0,
        scene_start_time=2.0,
        line_config={},
        text="hello",
        audio_path=Path("voice.wav"),
        extra_audio_overlays=(),
        image_layer_overlays=(),
        background_layout={},
        background_source="background.mp4",
        background_is_video=True,
        uses_scene_background=True,
        run_base=None,
        background_config={"type": "video", "path": "background.mp4"},
    )


def _plan(*, cpu_overlay: bool = True) -> SceneTalkPlan:
    return SceneTalkPlan(
        effective_characters=(),
        effective_insert=None,
        face_animations=({"mouth": []},),
        animation_meta={},
        has_subtitle=cpu_overlay,
        has_visible_characters=False,
        insert_is_image=False,
        has_move=True,
        has_effect=False,
    )


def _outcome(tmp_path: Path) -> TalkRenderOutcome:
    return TalkRenderOutcome(
        path=tmp_path / "clip.mp4",
        cache_started_at=10.1,
        cache_finished_at=10.8,
        finished_at=11.0,
        creator_started_at=10.2,
        creator_finished_at=10.7,
        render_ms=500.0,
    )


def test_summarize_line_elapsed_reports_requested_percentiles() -> None:
    summary = summarize_line_elapsed([0, "bad", 1, 2, 3, 4, 5])

    assert summary.average == 3.0
    assert summary.p50 == 3.0
    assert summary.p90 == 4.0
    assert summary.p95 == 4.0
    assert summary.maximum == 5.0


def test_summarize_line_elapsed_empty_values_are_zero() -> None:
    assert summarize_line_elapsed([0, -1, None]).average == 0.0
    assert summarize_line_elapsed([]).maximum == 0.0


def test_record_talk_line_metrics_preserves_payload_and_profile_sample(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject = _Subject(tmp_path)
    recorded = []
    monkeypatch.setattr(scene_line_metrics.perf_stats, "record_line_clip", recorded.append)

    async def run():
        subject._record_talk_line_metrics(
            scene_id="demo",
            context=_context(),
            plan=_plan(),
            outcome=_outcome(tmp_path),
            line_total_started=10.0,
        )

    asyncio.run(run())

    assert subject.phase._profile_samples == [
        {"cpu_overlay": True, "elapsed": 1.0}
    ]
    assert len(recorded) == 1
    assert recorded[0]["scene_id"] == "demo"
    assert recorded[0]["line_index"] == 3
    assert recorded[0]["duration_ms"] == pytest.approx(1000.0)
    assert recorded[0]["cache_status"] == "miss"
    assert recorded[0]["cache_lookup_ms"] == pytest.approx(100.0)
    assert recorded[0]["render_ms"] == 500.0
    assert recorded[0]["prepare_ms"] == pytest.approx(100.0)
    assert recorded[0]["cache_store_ms"] == pytest.approx(100.0)
    assert recorded[0]["worker_id"].startswith("Task-")
    assert subject.phase._clip_samples_all == [
        {
            "scene": "demo",
            "line": 3,
            "elapsed": 1.0,
            "subtitle": True,
            "chars": False,
            "insert_img": False,
            "is_bg_video": True,
            "cache": "miss",
        }
    ]


def test_cpu_dominant_profile_applies_caps_workers_and_hint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject = _Subject(tmp_path)
    subject.phase._profile_samples = [
        {"cpu_overlay": True, "elapsed": 2.0},
        {"cpu_overlay": True, "elapsed": 4.0},
    ]
    modes = []
    monkeypatch.setattr(scene_line_metrics.os, "cpu_count", lambda: 16)
    monkeypatch.setattr(scene_line_metrics, "set_hw_filter_mode", modes.append)
    monkeypatch.delenv("FFMPEG_FILTER_THREADS_CAP", raising=False)
    monkeypatch.delenv("FFMPEG_FILTER_COMPLEX_THREADS_CAP", raising=False)

    asyncio.run(subject._maybe_retune_line_workers())

    assert modes == ["cpu"]
    assert subject.phase.clip_workers == 4
    assert subject.video_renderer.clip_workers == 4
    assert subject.phase._retuned is True
    assert subject.saved_hint["cpu_ratio"] == 1.0
    assert subject.saved_hint["decision_mode"] == "cpu"
    assert subject.saved_hint["summary"].average == 3.0
    assert scene_line_metrics.os.environ["FFMPEG_FILTER_THREADS_CAP"] == "2"
    assert scene_line_metrics.os.environ["FFMPEG_FILTER_COMPLEX_THREADS_CAP"] == "2"
    assert scene_line_metrics.os.environ["FFMPEG_PROFILE_MODE"] == "0"


def test_non_cpu_dominant_profile_keeps_workers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject = _Subject(tmp_path)
    subject.phase.clip_workers = 2
    subject.video_renderer.clip_workers = 2
    subject.phase._profile_samples = [
        {"cpu_overlay": False, "elapsed": 1.0},
        {"cpu_overlay": True, "elapsed": 3.0},
        {"cpu_overlay": False, "elapsed": 2.0},
    ]
    subject.phase.profile_limit = 3
    modes = []
    monkeypatch.setattr(scene_line_metrics, "set_hw_filter_mode", modes.append)

    asyncio.run(subject._maybe_retune_line_workers())

    assert modes == []
    assert subject.phase.clip_workers == 2
    assert subject.phase._retuned is True
    assert subject.saved_hint["decision_mode"] == "auto"


def test_parallel_scene_rendering_skips_retune(tmp_path: Path) -> None:
    subject = _Subject(tmp_path)
    subject.phase.parallel_scene_rendering = True
    subject.phase._profile_samples = [
        {"cpu_overlay": True, "elapsed": 1.0},
        {"cpu_overlay": True, "elapsed": 1.0},
    ]

    asyncio.run(subject._maybe_retune_line_workers())

    assert subject.phase._retuned is False
    assert subject.saved_hint is None


def test_hint_file_contains_extended_statistics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _RealSubject(SceneLineMetricsMixin):
        def __init__(self):
            self.phase = SimpleNamespace(clip_workers=3)
            self.cache_manager = SimpleNamespace(cache_dir=tmp_path)
            self.hw_kind = "cpu"

    async def fake_version():
        return "ffmpeg-test"

    monkeypatch.setattr(scene_line_metrics, "get_ffmpeg_version", fake_version)
    subject = _RealSubject()
    summary = summarize_line_elapsed([1, 2, 3, 4, 5])

    path = asyncio.run(
        subject._write_line_autotune_hint(
            cpu_ratio=0.75,
            decision_mode="cpu",
            summary=summary,
        )
    )

    assert path == tmp_path / "autotune_hint.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["clip_workers"] == 3
    assert payload["p50_elapsed"] == 3.0
    assert payload["p90_elapsed"] == 4.0
    assert payload["p95_elapsed"] == 4.0
    assert payload["max_elapsed"] == 5.0
    assert payload["ffmpeg"] == "ffmpeg-test"
