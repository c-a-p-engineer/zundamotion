from __future__ import annotations

import asyncio
import wave
from pathlib import Path

from zundamotion.components.pipeline_phases.audio_duration_cache import (
    AudioDurationCacheProxy,
)


class FakeCacheManager:
    def __init__(self) -> None:
        self.calls = []
        self.cache_dir = Path("cache")

    async def get_or_create_media_duration(self, file_path, caller=None):
        self.calls.append((Path(file_path), caller))
        return 9.5

    def marker(self):
        return "delegated"


class LegacyCacheManager:
    def __init__(self) -> None:
        self.calls = []

    async def get_or_create_media_duration(self, file_path):
        self.calls.append(Path(file_path))
        return 7.25


def _write_wav(path: Path, *, seconds: float, sample_rate: int = 8000) -> None:
    frames = int(seconds * sample_rate)
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(b"\x00\x00" * frames)


def test_valid_wav_duration_uses_header_without_delegate(tmp_path) -> None:
    wav_path = tmp_path / "voice.wav"
    _write_wav(wav_path, seconds=1.25)
    underlying = FakeCacheManager()
    proxy = AudioDurationCacheProxy(underlying)

    duration = asyncio.run(
        proxy.get_or_create_media_duration(wav_path, caller="audio-test")
    )

    assert duration == 1.25
    assert underlying.calls == []


def test_invalid_wav_falls_back_to_existing_probe_cache(tmp_path) -> None:
    wav_path = tmp_path / "broken.wav"
    wav_path.write_bytes(b"not-a-wave")
    underlying = FakeCacheManager()
    proxy = AudioDurationCacheProxy(underlying)

    duration = asyncio.run(
        proxy.get_or_create_media_duration(wav_path, caller="fallback-test")
    )

    assert duration == 9.5
    assert underlying.calls == [(wav_path, "fallback-test")]


def test_non_wav_delegates_unchanged(tmp_path) -> None:
    media_path = tmp_path / "sound.mp3"
    media_path.write_bytes(b"mp3")
    underlying = FakeCacheManager()
    proxy = AudioDurationCacheProxy(underlying)

    duration = asyncio.run(proxy.get_or_create_media_duration(media_path))

    assert duration == 9.5
    assert underlying.calls == [(media_path, None)]


def test_legacy_delegate_without_caller_keyword_is_supported(tmp_path) -> None:
    media_path = tmp_path / "legacy.mp3"
    media_path.write_bytes(b"mp3")
    underlying = LegacyCacheManager()
    proxy = AudioDurationCacheProxy(underlying)

    duration = asyncio.run(
        proxy.get_or_create_media_duration(media_path, caller="compatibility-test")
    )

    assert duration == 7.25
    assert underlying.calls == [media_path]


def test_other_cache_manager_attributes_are_delegated() -> None:
    underlying = FakeCacheManager()
    proxy = AudioDurationCacheProxy(underlying)

    assert proxy.cache_dir == Path("cache")
    assert proxy.marker() == "delegated"
