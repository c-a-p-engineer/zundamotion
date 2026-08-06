from __future__ import annotations

import asyncio
from pathlib import Path

from zundamotion.components.video.face_overlay_cache import FaceOverlayCache


class FakePersistentCache:
    def __init__(self, output: Path) -> None:
        self.output = output
        self.calls = 0

    async def get_or_create(self, *, creator_func, **kwargs):
        self.calls += 1
        if not self.output.exists():
            await creator_func(self.output)
        return self.output


def _subject(tmp_path: Path) -> tuple[FaceOverlayCache, FakePersistentCache, Path]:
    source = tmp_path / "mouth.png"
    source.write_bytes(b"source")
    output = tmp_path / "cached.png"
    persistent = FakePersistentCache(output)
    subject = FaceOverlayCache(persistent)

    async def fake_resolve(**kwargs):
        persistent.calls += 1
        await asyncio.sleep(0)
        output.write_bytes(b"cached")
        return output

    subject._resolve_scaled_overlay = fake_resolve
    return subject, persistent, source


def test_sequential_requests_reuse_run_memo(tmp_path) -> None:
    subject, persistent, source = _subject(tmp_path)

    async def run():
        first = await subject.get_scaled_overlay(source, 1.0)
        second = await subject.get_scaled_overlay(source, 1.0)
        return first, second

    first, second = asyncio.run(run())

    assert first == second
    assert persistent.calls == 1


def test_concurrent_requests_share_inflight_task(tmp_path) -> None:
    subject, persistent, source = _subject(tmp_path)

    async def run():
        return await asyncio.gather(
            subject.get_scaled_overlay(source, 1.0),
            subject.get_scaled_overlay(source, 1.0),
            subject.get_scaled_overlay(source, 1.0),
        )

    results = asyncio.run(run())

    assert results[0] == results[1] == results[2]
    assert persistent.calls == 1


def test_scale_change_creates_distinct_run_entry(tmp_path) -> None:
    subject, persistent, source = _subject(tmp_path)

    async def run():
        await subject.get_scaled_overlay(source, 1.0)
        await subject.get_scaled_overlay(source, 1.5)

    asyncio.run(run())

    assert persistent.calls == 2


def test_source_change_invalidates_run_memo(tmp_path) -> None:
    subject, persistent, source = _subject(tmp_path)

    async def first():
        return await subject.get_scaled_overlay(source, 1.0)

    asyncio.run(first())
    source.write_bytes(b"source-changed")

    async def second():
        return await subject.get_scaled_overlay(source, 1.0)

    asyncio.run(second())

    assert persistent.calls == 2
