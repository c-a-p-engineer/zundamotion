from tools.zundamotion_audio_worker_benchmark import _comparison, _worker_schedule


def _trial(index: int, workers: int, elapsed: float, fingerprint: dict):
    return {
        "trial_index": index,
        "workers": workers,
        "success": True,
        "elapsed_seconds": elapsed,
        "provider_failures": 0,
        "fingerprint": fingerprint,
    }


def test_worker_schedule_counterbalances_order() -> None:
    assert _worker_schedule(1) == [1, 2]
    assert _worker_schedule(2) == [1, 2, 2, 1]
    assert _worker_schedule(3) == [1, 2, 2, 1, 1, 2]


def test_comparison_reports_median_speedup_and_equivalence() -> None:
    fingerprint = {"line_order": ["scene_1"], "lines": [{"pcm_sha256": "same"}]}
    result = _comparison(
        [
            _trial(1, 1, 10.0, fingerprint),
            _trial(2, 2, 6.0, fingerprint),
            _trial(3, 2, 5.0, fingerprint),
            _trial(4, 1, 11.0, fingerprint),
        ]
    )

    assert result["median_elapsed_seconds"] == {"1": 10.5, "2": 5.5}
    assert result["worker2_speedup_vs_worker1"] == 1.909091
    assert result["worker2_improvement_percent"] == 47.619
    assert result["all_successful_trials_equivalent"] is True
    assert result["provider_failures"] == 0


def test_comparison_rejects_different_audio_or_timeline_fingerprint() -> None:
    result = _comparison(
        [
            _trial(1, 1, 10.0, {"pcm": "a", "timeline": ["a"]}),
            _trial(2, 2, 6.0, {"pcm": "b", "timeline": ["a"]}),
        ]
    )

    assert result["all_successful_trials_equivalent"] is False
