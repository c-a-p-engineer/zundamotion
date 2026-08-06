from __future__ import annotations

from pathlib import Path

from zundamotion.components.pipeline_phases.video_phase import scene_cache_latency
from zundamotion.components.pipeline_phases.video_phase.scene_cache_latency import (
    SceneCacheLatencyProxy,
)


class FakeCacheManager:
    def __init__(self, result):
        self.result = result
        self.calls = []
        self.cache_dir = Path("cache")

    def get_cached_path(self, *, key_data, file_name, extension):
        self.calls.append((key_data, file_name, extension))
        return self.result

    def marker(self):
        return "delegated"


def _recorders(monkeypatch):
    counts = []
    timings = []
    monkeypatch.setattr(scene_cache_latency.perf_stats, "incr", counts.append)
    monkeypatch.setattr(
        scene_cache_latency.perf_stats,
        "add_ms",
        lambda name, value: timings.append((name, value)),
    )
    return counts, timings


def test_subtitle_cache_hit_records_layer_and_status(monkeypatch, tmp_path) -> None:
    cached = tmp_path / "scene_sub.mp4"
    cached.write_bytes(b"video")
    manager = FakeCacheManager(cached)
    proxy = SceneCacheLatencyProxy(manager, scene_id="intro")
    counts, timings = _recorders(monkeypatch)

    result = proxy.get_cached_path(
        key_data={"key": 1},
        file_name="scene_intro_sub",
        extension="mp4",
    )

    assert result == cached
    assert manager.calls == [({"key": 1}, "scene_intro_sub", "mp4")]
    assert "scene_cache_lookup_total" in counts
    assert "scene_cache_lookup_hit" in counts
    assert "scene_cache_lookup_sub_hit" in counts
    timing_names = {name for name, _value in timings}
    assert "scene_cache_lookup_ms" in timing_names
    assert "scene_cache_lookup_hit_ms" in timing_names
    assert "scene_cache_lookup_sub_ms" in timing_names


def test_base_cache_miss_records_layer_and_status(monkeypatch) -> None:
    manager = FakeCacheManager(None)
    proxy = SceneCacheLatencyProxy(manager, scene_id="intro")
    counts, timings = _recorders(monkeypatch)

    result = proxy.get_cached_path(
        key_data={"key": 2},
        file_name="scene_intro_base",
        extension="mp4",
    )

    assert result is None
    assert "scene_cache_lookup_miss" in counts
    assert "scene_cache_lookup_base_miss" in counts
    assert any(name == "scene_cache_lookup_miss_ms" for name, _ in timings)
    assert any(name == "scene_cache_lookup_base_ms" for name, _ in timings)


def test_non_lookup_attributes_are_delegated() -> None:
    manager = FakeCacheManager(None)
    proxy = SceneCacheLatencyProxy(manager, scene_id="intro")

    assert proxy.cache_dir == Path("cache")
    assert proxy.marker() == "delegated"
