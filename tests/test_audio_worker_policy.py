from __future__ import annotations

from types import SimpleNamespace

from zundamotion.components.pipeline_phases import audio_phase
from zundamotion.components.pipeline_phases.audio_phase import AudioPhase
from zundamotion.components.pipeline_phases.audio_worker_policy import (
    resolve_audio_worker_policy,
)
from zundamotion.utils.ffmpeg_params import AudioParams


def test_auto_workers_are_bounded_to_two() -> None:
    policy = resolve_audio_worker_policy(
        {"parallel_workers": "auto"},
        {},
        cpu_count=16,
    )

    assert policy.requested == "auto"
    assert policy.resolved == 2
    assert policy.source == "voice_config"
    assert policy.automatic is True


def test_auto_workers_follow_small_cpu_count() -> None:
    policy = resolve_audio_worker_policy({}, {}, cpu_count=1)

    assert policy.resolved == 1
    assert policy.source == "default"
    assert policy.automatic is True


def test_environment_overrides_voice_config() -> None:
    policy = resolve_audio_worker_policy(
        {"parallel_workers": 1},
        {"ZUNDAMOTION_AUDIO_WORKERS": "2"},
        cpu_count=8,
    )

    assert policy.requested == "2"
    assert policy.resolved == 2
    assert policy.source == "environment"
    assert policy.automatic is False


def test_explicit_worker_count_is_preserved() -> None:
    policy = resolve_audio_worker_policy(
        {"parallel_workers": 3},
        {},
        cpu_count=2,
    )

    assert policy.resolved == 3
    assert policy.automatic is False


def test_invalid_value_falls_back_with_reason() -> None:
    policy = resolve_audio_worker_policy(
        {"parallel_workers": "invalid"},
        {},
        cpu_count=8,
    )

    assert policy.resolved == 2
    assert policy.automatic is True
    assert policy.fallback_reason == "invalid_value"


def test_audio_phase_init_still_uses_determine_workers_override(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(audio_phase, "AudioGenerator", lambda *args, **kwargs: object())
    monkeypatch.setattr(AudioPhase, "_determine_audio_workers", lambda self: 7)
    cache_manager = SimpleNamespace(cache_dir=tmp_path)

    phase = AudioPhase({}, tmp_path, cache_manager, AudioParams())

    assert phase.audio_workers == 7
    assert phase.audio_worker_policy.resolved == 7
    assert phase.audio_worker_policy.source == "compatibility_override"
    assert phase.audio_worker_policy.fallback_reason == "determine_audio_workers_override"
