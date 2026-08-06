from __future__ import annotations

import hashlib
import json
from pathlib import Path

from zundamotion.components.subtitles import instrumented_generator
from zundamotion.components.subtitles.instrumented_generator import (
    SubtitleGenerator,
    SubtitlePNGMetricsProxy,
)
from zundamotion.components.subtitles.generator import SubtitleGenerator as BaseSubtitleGenerator


class FakeCacheManager:
    def __init__(self, root: Path, *, no_cache: bool = False) -> None:
        self.cache_dir = root
        self.ephemeral_dir = root / "ephemeral"
        self.ephemeral_dir.mkdir(exist_ok=True)
        self.no_cache = no_cache

    def _generate_hash(self, key_data):
        payload = json.dumps(key_data, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def get_cache_path(self, *, key_data, file_name, extension):
        key = self._generate_hash(key_data)
        return self.cache_dir / f"{file_name}_{key}.{extension}"


class FakeRenderer:
    def __init__(self, cache_manager: FakeCacheManager) -> None:
        self.cache_manager = cache_manager
        self.calls = 0

    async def render(self, text, style):
        self.calls += 1
        key_data = {"text": text, "style": style}
        key = self.cache_manager._generate_hash(key_data)
        if self.cache_manager.no_cache:
            path = self.cache_manager.ephemeral_dir / f"temp_subtitle_{key}.png"
        else:
            path = self.cache_manager.get_cache_path(
                key_data=key_data,
                file_name="subtitle",
                extension="png",
            )
        path.write_bytes(b"png")
        return path, {"w": 10, "h": 5}


def _capture_counts(monkeypatch):
    counts = []
    monkeypatch.setattr(instrumented_generator.perf_stats, "incr", counts.append)
    return counts


def test_first_missing_request_is_generated_and_second_is_repeat(
    monkeypatch,
    tmp_path,
) -> None:
    manager = FakeCacheManager(tmp_path)
    renderer = FakeRenderer(manager)
    proxy = SubtitlePNGMetricsProxy(renderer, manager)
    counts = _capture_counts(monkeypatch)

    import asyncio

    asyncio.run(proxy.render("hello", {"font_size": 64}))
    asyncio.run(proxy.render("hello", {"font_size": 64}))

    assert renderer.calls == 2
    assert counts.count("subtitle_png_request") == 2
    assert counts.count("subtitle_png_unique") == 1
    assert counts.count("subtitle_png_run_repeat") == 1
    assert counts.count("subtitle_png_generated") == 1
    assert "subtitle_png_persistent_hit" not in counts


def test_existing_persistent_png_is_counted_as_hit(monkeypatch, tmp_path) -> None:
    manager = FakeCacheManager(tmp_path)
    renderer = FakeRenderer(manager)
    proxy = SubtitlePNGMetricsProxy(renderer, manager)
    key_data = {"text": "hello", "style": {}}
    manager.get_cache_path(
        key_data=key_data,
        file_name="subtitle",
        extension="png",
    ).write_bytes(b"cached")
    counts = _capture_counts(monkeypatch)

    import asyncio

    asyncio.run(proxy.render("hello", {}))

    assert "subtitle_png_unique" in counts
    assert "subtitle_png_persistent_hit" in counts
    assert "subtitle_png_generated" not in counts


def test_no_cache_existing_ephemeral_png_is_separate(monkeypatch, tmp_path) -> None:
    manager = FakeCacheManager(tmp_path, no_cache=True)
    renderer = FakeRenderer(manager)
    proxy = SubtitlePNGMetricsProxy(renderer, manager)
    key_data = {"text": "hello", "style": {}}
    key = manager._generate_hash(key_data)
    (manager.ephemeral_dir / f"temp_subtitle_{key}.png").write_bytes(b"cached")
    counts = _capture_counts(monkeypatch)

    import asyncio

    asyncio.run(proxy.render("hello", {}))

    assert "subtitle_png_ephemeral_hit" in counts
    assert "subtitle_png_persistent_hit" not in counts


def test_exported_generator_preserves_base_generator_contract() -> None:
    assert issubclass(SubtitleGenerator, BaseSubtitleGenerator)
