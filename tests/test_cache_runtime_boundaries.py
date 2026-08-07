from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path

import zundamotion.cache as cache_module
from zundamotion.cache import CacheManager
from zundamotion.cache_base import CacheManager as BaseCacheManager


def test_runtime_hash_matches_legacy_cache_key_for_image(tmp_path: Path) -> None:
    image = tmp_path / "asset.png"
    image.write_bytes(b"same-image-content")
    legacy = BaseCacheManager(tmp_path / "legacy")
    runtime = CacheManager(tmp_path / "runtime")
    key_data = {"asset": str(image), "value": 1}

    assert runtime._generate_hash(key_data) == legacy._generate_hash(key_data)


def test_image_signature_sha_is_memoized_and_stat_change_invalidates(tmp_path: Path) -> None:
    image = tmp_path / "asset.png"
    image.write_bytes(b"first")
    manager = CacheManager(tmp_path / "cache")

    first = manager._cache_key_file_signature(image.resolve())
    second = manager._cache_key_file_signature(image.resolve())
    assert second == first
    assert len(manager._signature_memo._sha256_by_stat) == 1

    image.write_bytes(b"second-content")
    os.utime(image, None)
    third = manager._cache_key_file_signature(image.resolve())

    assert third["sha256"] != first["sha256"]
    assert len(manager._signature_memo._sha256_by_stat) == 1


def test_same_run_and_persistent_hits_are_distinguished(tmp_path: Path, monkeypatch) -> None:
    cache_dir = tmp_path / "cache"
    source = tmp_path / "source.bin"
    source.write_bytes(b"payload")
    key_data = {"value": "x"}

    writer = CacheManager(cache_dir)
    writer_statuses: list[str] = []
    monkeypatch.setattr(writer._cache_diagnostics, "record_status", writer_statuses.append)
    written = writer.cache_file(source, key_data, "sample", "bin")
    assert written.is_file()
    assert writer.get_cached_path(key_data, "sample", "bin") == written
    assert "write" in writer_statuses
    assert "same_run_hit" in writer_statuses

    reader = CacheManager(cache_dir)
    reader_statuses: list[str] = []
    monkeypatch.setattr(reader._cache_diagnostics, "record_status", reader_statuses.append)
    assert reader.get_cached_path(key_data, "sample", "bin") == written
    assert "persistent_hit" in reader_statuses


def test_no_cache_and_inflight_wait_statuses_are_visible(tmp_path: Path, monkeypatch) -> None:
    disabled = CacheManager(tmp_path / "disabled", no_cache=True)
    disabled_statuses: list[str] = []
    monkeypatch.setattr(
        disabled._cache_diagnostics, "record_status", disabled_statuses.append
    )
    assert disabled.get_cached_path({"x": 1}, "sample", "bin") is None
    assert disabled_statuses == ["disabled"]

    manager = CacheManager(tmp_path / "cache")
    statuses: list[str] = []
    monkeypatch.setattr(manager._cache_diagnostics, "record_status", statuses.append)
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def creator(path: Path) -> Path:
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        path.write_bytes(b"generated")
        return path

    async def run_two() -> tuple[Path, Path]:
        first = asyncio.create_task(
            manager.get_or_create({"k": 1}, "item", "bin", creator)
        )
        await started.wait()
        second = asyncio.create_task(
            manager.get_or_create({"k": 1}, "item", "bin", creator)
        )
        await asyncio.sleep(0)
        release.set()
        return await first, await second

    first_path, second_path = asyncio.run(run_two())
    assert first_path == second_path
    assert calls == 1
    assert "miss" in statuses
    assert "in_flight_wait" in statuses
    assert "write" in statuses


def test_cache_latency_stages_are_recorded(tmp_path: Path, monkeypatch) -> None:
    image = tmp_path / "asset.png"
    image.write_bytes(b"image")
    source = tmp_path / "source.bin"
    source.write_bytes(b"payload")
    manager = CacheManager(tmp_path / "cache")
    stages: list[str] = []

    monkeypatch.setattr(
        manager._cache_diagnostics,
        "record_latency",
        lambda stage, _elapsed: stages.append(stage),
    )
    manager._generate_hash({"asset": str(image)})
    manager.cache_file(source, {"asset": str(image)}, "sample", "bin")
    manager.get_cached_path({"asset": str(image)}, "sample", "bin")

    assert "file_fingerprint" in stages
    assert "key_serialization_hash" in stages
    assert "copy_store" in stages
    assert "path_existence" in stages


def test_unified_probe_bundle_reuses_one_media_info_probe(tmp_path: Path, monkeypatch) -> None:
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"not-real-media")
    manager = CacheManager(tmp_path / "cache")
    calls = 0

    async def fake_info(_path: str, caller=None):
        nonlocal calls
        calls += 1
        return {
            "duration": 1.25,
            "video": {"codec_name": "h264", "width": 320, "height": 180},
            "audio": {"codec_name": "aac", "sample_rate": 48000, "channels": 2},
        }

    async def unexpected_duration(_path: str, caller=None):
        raise AssertionError("duration must come from the unified media-info probe")

    monkeypatch.setattr(cache_module, "get_media_info", fake_info)
    monkeypatch.setattr(cache_module, "get_media_duration", unexpected_duration)

    info = asyncio.run(manager.get_or_create_media_info(media, caller="test"))
    duration = asyncio.run(manager.get_or_create_media_duration(media, caller="test"))

    assert info["duration"] == 1.25
    assert duration == 1.25
    assert calls == 1
    bundles = list(manager.cache_dir.glob("probe_*.json"))
    assert len(bundles) == 1
    payload = json.loads(bundles[0].read_text(encoding="utf-8"))
    assert payload["media_info"]["duration"] == 1.25
    assert payload["duration"] == 1.25


def test_duration_only_public_monkeypatch_contract_is_preserved(tmp_path: Path, monkeypatch) -> None:
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"not-real-media")
    manager = CacheManager(tmp_path / "cache", no_cache=True)
    calls = 0

    async def fake_duration(_path: str, caller=None):
        nonlocal calls
        calls += 1
        return 12.34

    monkeypatch.setattr(cache_module, "get_media_duration", fake_duration)
    assert asyncio.run(manager.get_or_create_media_duration(media)) == 12.34
    assert asyncio.run(manager.get_or_create_media_duration(media)) == 12.34
    assert calls == 1


def test_legacy_probe_metadata_is_migrated_without_ffprobe(tmp_path: Path, monkeypatch) -> None:
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"legacy")
    manager = CacheManager(tmp_path / "cache")
    info_path, duration_path = manager._legacy_probe_paths(media)
    info_path.write_text(
        json.dumps({"media_info": {"duration": 2.5, "video": {}, "audio": {}}}),
        encoding="utf-8",
    )
    duration_path.write_text(json.dumps({"duration": 2.5}), encoding="utf-8")

    async def fail(*_args, **_kwargs):
        raise AssertionError("legacy metadata should migrate without probing")

    monkeypatch.setattr(cache_module, "get_media_info", fail)
    monkeypatch.setattr(cache_module, "get_media_duration", fail)

    assert asyncio.run(manager.get_or_create_media_duration(media)) == 2.5
    assert asyncio.run(manager.get_or_create_media_info(media))["duration"] == 2.5
    assert len(list(manager.cache_dir.glob("probe_*.json"))) == 1


def test_corrupted_probe_bundle_is_deleted_and_regenerated(tmp_path: Path, monkeypatch) -> None:
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"corrupt-test")
    manager = CacheManager(tmp_path / "cache")
    _key, bundle_path = manager._probe_bundle_path(media)
    bundle_path.write_text("{broken", encoding="utf-8")
    deletions: list[str] = []
    monkeypatch.setattr(
        manager._cache_diagnostics,
        "record_deletion",
        lambda reason, count=1: deletions.extend([reason] * count),
    )

    async def fake_info(_path: str, caller=None):
        return {"duration": 3.0, "video": {}, "audio": {}}

    monkeypatch.setattr(cache_module, "get_media_info", fake_info)
    info = asyncio.run(manager.get_or_create_media_info(media))
    assert info["duration"] == 3.0
    assert "corrupted" in deletions
    assert json.loads(bundle_path.read_text(encoding="utf-8"))["duration"] == 3.0


def test_ttl_cleanup_physically_deletes_expired_file_and_manifest(tmp_path: Path, monkeypatch) -> None:
    manager = CacheManager(tmp_path / "cache", ttl_hours=1)
    video = manager.cache_dir / "temp_normalized_deadbeef.mp4"
    manifest = manager.cache_dir / "temp_normalized_deadbeef.meta.json"
    video.write_bytes(b"video")
    manifest.write_text("{}", encoding="utf-8")
    old = 1_600_000_000
    os.utime(video, (old, old))
    os.utime(manifest, (old, old))
    reasons: list[str] = []
    monkeypatch.setattr(
        manager._cache_diagnostics,
        "record_deletion",
        lambda reason, count=1: reasons.extend([reason] * count),
    )

    manager._clean_cache()
    assert not video.exists()
    assert not manifest.exists()
    assert "ttl_expired" in reasons


def test_size_eviction_and_manual_invalidation_report_reasons(tmp_path: Path, monkeypatch) -> None:
    manager = CacheManager(tmp_path / "cache", max_size_mb=0.000001)
    reasons: list[str] = []
    monkeypatch.setattr(
        manager._cache_diagnostics,
        "record_deletion",
        lambda reason, count=1: reasons.extend([reason] * count),
    )
    oversized = manager.cache_dir / "oversized.bin"
    oversized.write_bytes(b"x" * 1024)
    manager._clean_cache()
    assert not oversized.exists()
    assert "size_evicted" in reasons

    target = manager.cache_dir / ("finalize_concat_" + "a" * 64 + ".mp4")
    target.write_bytes(b"final")
    removed = manager._invalidate_exact_patterns(
        [re.compile(r"finalize_concat_[0-9a-f]{64}\.mp4")]
    )
    assert removed == [target]
    assert "manual_refresh_clear" in reasons


def test_duration_mismatch_has_explicit_deletion_reason(tmp_path: Path, monkeypatch) -> None:
    manager = CacheManager(tmp_path / "cache")
    cached = manager.cache_dir / "scene.mp4"
    cached.write_bytes(b"bad-duration")
    reasons: list[str] = []
    monkeypatch.setattr(
        manager._cache_diagnostics,
        "record_deletion",
        lambda reason, count=1: reasons.extend([reason] * count),
    )

    assert manager.record_duration_mismatch_deletion(cached) is True
    assert not cached.exists()
    assert reasons == ["duration_mismatch"]
