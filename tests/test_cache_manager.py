import asyncio
import os
from pathlib import Path

import zundamotion.cache as cache_module
from zundamotion.cache import CacheManager


_SHA_A = "a" * 64
_SHA_B = "b" * 64


def _seed_cache(cache: CacheManager, *names: str) -> None:
    for name in names:
        (cache.cache_dir / name).write_bytes(b"cache")


def _cache_names(cache: CacheManager) -> set[str]:
    return {path.name for path in cache.cache_dir.iterdir() if not path.name.startswith(".")}


def test_invalidate_scene_removes_only_requested_scene(tmp_path: Path) -> None:
    cache = CacheManager(tmp_path / "cache")
    _seed_cache(
        cache,
        f"scene_demo_base_{_SHA_A}.mp4",
        f"scene_demo_sub_{_SHA_A}.mp4",
        f"demo_1_{_SHA_A}.mp4",
        f"scene_demo2_base_{_SHA_A}.mp4",
    )

    cache.invalidate_scene("demo", {"base", "subtitle", "line_clips"})

    assert _cache_names(cache) == {
        f"scene_demo2_base_{_SHA_A}.mp4"
    }


def test_invalidate_scene_keeps_other_scene_cache(tmp_path: Path) -> None:
    cache = CacheManager(tmp_path / "cache")
    _seed_cache(cache, f"scene_one_base_{_SHA_A}.mp4", f"scene_two_base_{_SHA_A}.mp4")

    cache.invalidate_scene("one", {"base"})

    assert (cache.cache_dir / f"scene_two_base_{_SHA_A}.mp4").exists()


def test_invalidate_scene_subtitle_only(tmp_path: Path) -> None:
    cache = CacheManager(tmp_path / "cache")
    _seed_cache(cache, f"scene_demo_base_{_SHA_A}.mp4", f"scene_demo_sub_{_SHA_A}.mp4")

    cache.invalidate_scene("demo", {"subtitle"})

    assert (cache.cache_dir / f"scene_demo_base_{_SHA_A}.mp4").exists()
    assert not (cache.cache_dir / f"scene_demo_sub_{_SHA_A}.mp4").exists()


def test_invalidate_scene_base_only(tmp_path: Path) -> None:
    cache = CacheManager(tmp_path / "cache")
    _seed_cache(cache, f"scene_demo_base_{_SHA_A}.mp4", f"scene_demo_sub_{_SHA_A}.mp4")

    cache.invalidate_scene("demo", {"base"})

    assert not (cache.cache_dir / f"scene_demo_base_{_SHA_A}.mp4").exists()
    assert (cache.cache_dir / f"scene_demo_sub_{_SHA_A}.mp4").exists()


def test_invalidate_scene_line_clips_only(tmp_path: Path) -> None:
    cache = CacheManager(tmp_path / "cache")
    _seed_cache(cache, f"demo_1_{_SHA_A}.mp4", f"demo_20_{_SHA_B}.mp4", f"scene_demo_base_{_SHA_A}.mp4")

    cache.invalidate_scene("demo", {"line_clips"})

    assert _cache_names(cache) == {
        f"scene_demo_base_{_SHA_A}.mp4"
    }


def test_invalidate_transition_only(tmp_path: Path) -> None:
    cache = CacheManager(tmp_path / "cache")
    _seed_cache(
        cache,
        f"finalize_transition_000_001_{_SHA_A}.mp4",
        f"finalize_transition_000_001_{_SHA_A}_boundary.mp4",
        f"finalize_transition_001_002_{_SHA_B}.mp4",
        f"finalize_concat_{_SHA_A}.mp4",
    )

    cache.invalidate_transition("opening", "main", transition_index=0)

    assert _cache_names(cache) == {
        f"finalize_transition_001_002_{_SHA_B}.mp4",
        f"finalize_concat_{_SHA_A}.mp4",
    }


def test_invalidate_finalize_only(tmp_path: Path) -> None:
    cache = CacheManager(tmp_path / "cache")
    _seed_cache(cache, f"finalize_concat_{_SHA_A}.mp4", f"finalize_transition_000_001_{_SHA_A}.mp4")

    cache.invalidate_finalize()

    assert _cache_names(cache) == {
        f"finalize_transition_000_001_{_SHA_A}.mp4"
    }


def test_invalidate_missing_target_is_safe(tmp_path: Path) -> None:
    cache = CacheManager(tmp_path / "cache")

    assert cache.invalidate_scene("missing", {"base", "subtitle", "line_clips"}) == []
    assert cache.invalidate_transition("missing", "other", transition_index=99) == []
    assert cache.invalidate_finalize() == []


def test_cache_refresh_invalidates_each_key_only_once(tmp_path: Path) -> None:
    async def _run() -> None:
        cache = CacheManager(tmp_path / "cache", cache_refresh=True)
        created: list[str] = []

        async def creator(out_path: Path) -> Path:
            created.append(out_path.name)
            out_path.write_text(f"gen-{len(created)}", encoding="utf-8")
            return out_path

        key_data = {"kind": "face_overlay", "src": "demo.png"}
        first = await cache.get_or_create(
            key_data=key_data,
            file_name="face_overlay",
            extension="png",
            creator_func=creator,
        )
        second = await cache.get_or_create(
            key_data=key_data,
            file_name="face_overlay",
            extension="png",
            creator_func=creator,
        )

        assert first == second
        assert first.read_text(encoding="utf-8") == "gen-1"
        assert len(created) == 1

    asyncio.run(_run())


def test_cache_manager_creates_nested_cache_dir(tmp_path: Path) -> None:
    cache_dir = tmp_path / "missing" / "nested" / "cache"

    CacheManager(cache_dir)

    assert cache_dir.is_dir()


def test_cache_manager_accepts_existing_cache_dir(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    CacheManager(cache_dir)

    assert cache_dir.is_dir()


def test_cache_refresh_deduplicates_parallel_generation(tmp_path: Path) -> None:
    async def _run() -> None:
        cache = CacheManager(tmp_path / "cache", cache_refresh=True)
        started = 0

        async def creator(out_path: Path) -> Path:
            nonlocal started
            started += 1
            await asyncio.sleep(0.05)
            out_path.write_text("shared", encoding="utf-8")
            return out_path

        key_data = {"kind": "face_overlay", "src": "demo.png"}
        results = await asyncio.gather(
            cache.get_or_create(
                key_data=key_data,
                file_name="face_overlay",
                extension="png",
                creator_func=creator,
            ),
            cache.get_or_create(
                key_data=key_data,
                file_name="face_overlay",
                extension="png",
                creator_func=creator,
            ),
        )

        assert results[0] == results[1]
        assert results[0].read_text(encoding="utf-8") == "shared"
        assert started == 1

    asyncio.run(_run())


def test_get_cached_path_respects_cache_refresh(tmp_path: Path) -> None:
    cache = CacheManager(tmp_path / "cache", cache_refresh=True)
    key_data = {"kind": "scene", "id": "demo"}
    cached_path = cache.get_cache_path(key_data, "scene_demo", "mp4")
    cached_path.write_text("cached", encoding="utf-8")

    resolved = cache.get_cached_path(key_data, "scene_demo", "mp4")

    assert resolved is None
    assert not cached_path.exists()


def test_image_content_changes_cache_key_for_same_path(tmp_path: Path) -> None:
    cache = CacheManager(tmp_path / "cache")
    image_path = tmp_path / "13-redesign.png"

    image_path.write_bytes(b"old-image")
    first = cache.get_cache_path(
        {"kind": "scene", "background": {"path": str(image_path)}},
        "scene_demo",
        "mp4",
    )

    image_path.write_bytes(b"new-image")
    second = cache.get_cache_path(
        {"kind": "scene", "background": {"path": str(image_path)}},
        "scene_demo",
        "mp4",
    )

    assert first != second


def test_image_rewrite_with_same_content_keeps_cache_key(tmp_path: Path) -> None:
    cache = CacheManager(tmp_path / "cache")
    image_path = tmp_path / "slide.png"

    image_path.write_bytes(b"same-image")
    first = cache.get_cache_path(
        {"kind": "scene", "background": {"path": str(image_path)}},
        "scene_demo",
        "mp4",
    )

    original_stat = image_path.stat()
    image_path.write_bytes(b"same-image")
    os.utime(
        image_path,
        ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns + 1_000_000_000),
    )
    second = cache.get_cache_path(
        {"kind": "scene", "background": {"path": str(image_path)}},
        "scene_demo",
        "mp4",
    )

    assert first == second


def test_non_image_rewrite_changes_cache_key_by_mtime(tmp_path: Path) -> None:
    cache = CacheManager(tmp_path / "cache")
    video_path = tmp_path / "clip.mp4"

    video_path.write_bytes(b"same-video")
    first = cache.get_cache_path(
        {"kind": "scene", "insert": {"path": str(video_path)}},
        "scene_demo",
        "mp4",
    )

    original_stat = video_path.stat()
    os.utime(
        video_path,
        ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns + 1_000_000_000),
    )
    second = cache.get_cache_path(
        {"kind": "scene", "insert": {"path": str(video_path)}},
        "scene_demo",
        "mp4",
    )

    assert first != second


def test_file_name_field_is_not_treated_as_asset_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    cache = CacheManager(tmp_path / "cache")
    media_name = tmp_path / "clip.mp4"

    media_name.write_bytes(b"old")
    first = cache.get_cache_path({"file_name": "clip.mp4"}, "duration", "json")

    media_name.write_bytes(b"new")
    second = cache.get_cache_path({"file_name": "clip.mp4"}, "duration", "json")

    assert first == second


def test_no_cache_reuses_duration_within_ephemeral_dir(tmp_path: Path, monkeypatch) -> None:
    async def _run() -> None:
        media = tmp_path / "clip.mp4"
        media.write_bytes(b"fake-media")
        cache = CacheManager(tmp_path / "cache", no_cache=True)
        cache.set_ephemeral_dir(tmp_path / "ephemeral")
        calls = 0

        async def fake_get_media_duration(_path: str, caller: str | None = None) -> float:
            nonlocal calls
            calls += 1
            return 12.34

        monkeypatch.setattr(cache_module, "get_media_duration", fake_get_media_duration)

        first = await cache.get_or_create_media_duration(media)
        second = await cache.get_or_create_media_duration(media)

        assert first == second == 12.34
        assert calls == 1
        assert list((tmp_path / "ephemeral").glob("duration_*.json"))
        assert not list((tmp_path / "cache").glob("duration_*.json"))

    asyncio.run(_run())
