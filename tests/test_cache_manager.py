import asyncio
from pathlib import Path

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
