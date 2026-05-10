import asyncio
from pathlib import Path

import zundamotion.cache as cache_module
from zundamotion.cache import CacheManager


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

        async def fake_get_media_duration(_path: str) -> float:
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
