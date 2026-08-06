from __future__ import annotations

from zundamotion.components.pipeline_phases.audio_worker_policy import (
    resolve_audio_worker_policy,
)


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
