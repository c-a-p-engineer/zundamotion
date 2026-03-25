import asyncio
from pathlib import Path

import httpx
import pytest

from zundamotion.components.audio.generator import AudioGenerator
from zundamotion.exceptions import CacheError
from zundamotion.utils.ffmpeg_params import AudioParams


class StubCacheManager:
    async def get_or_create(self, *, key_data, file_name, extension, creator_func):
        return await creator_func(Path(f"/tmp/{file_name}.{extension}"))


class StubSilentCacheManager(StubCacheManager):
    def __init__(self) -> None:
        self.calls = []

    async def get_or_create(self, *, key_data, file_name, extension, creator_func):
        self.calls.append((key_data, file_name, extension))
        return await creator_func(Path(f"/tmp/{file_name}.{extension}"))


class StubWrappingCacheManager(StubSilentCacheManager):
    async def get_or_create(self, *, key_data, file_name, extension, creator_func):
        self.calls.append((key_data, file_name, extension))
        try:
            return await creator_func(Path(f"/tmp/{file_name}.{extension}"))
        except Exception as exc:
            raise CacheError(
                f"Failed to generate or cache file {file_name}.{extension}: {exc}"
            )


def test_generate_audio_raises_clear_error_for_unknown_voicevox_speaker(monkeypatch, tmp_path):
    async def _run() -> None:
        generator = AudioGenerator(
            config={"voice": {"enabled": True, "url": "http://voicevox:50021"}},
            temp_dir=tmp_path,
            audio_params=AudioParams(),
            cache_manager=StubCacheManager(),
        )

        async def fake_get_speakers_info(_url):
            return {
                1: {"speaker_name": "ずんだもん", "name": "ノーマル"},
                2: {"speaker_name": "四国めたん", "name": "ノーマル"},
            }

        async def fake_generate_voice(**_kwargs):
            raise AssertionError("generate_voice should not be called for invalid speakers")

        monkeypatch.setattr(
            "zundamotion.components.audio.generator.get_speakers_info",
            fake_get_speakers_info,
        )
        monkeypatch.setattr(
            "zundamotion.components.audio.generator.generate_voice",
            fake_generate_voice,
        )

        with pytest.raises(ValueError, match="speaker_id=3"):
            await generator.generate_audio(
                "こんにちは",
                {"speaker_id": 3, "speaker_name": "copetan"},
                "scene1_1",
            )

    asyncio.run(_run())


def test_generate_audio_falls_back_to_silence_when_voicevox_synthesis_fails(
    monkeypatch, tmp_path
):
    async def _run() -> None:
        cache_manager = StubSilentCacheManager()
        generator = AudioGenerator(
            config={
                "voice": {
                    "enabled": True,
                    "url": "http://voicevox:50021",
                    "estimate_chars_per_second": 4.0,
                    "estimate_min_duration": 1.0,
                }
            },
            temp_dir=tmp_path,
            audio_params=AudioParams(),
            cache_manager=cache_manager,
        )

        async def fake_get_speakers_info(_url):
            return {
                3: {"speaker_name": "ずんだもん", "name": "ノーマル"},
            }

        async def fake_generate_voice(**_kwargs):
            request = httpx.Request(
                "POST", "http://voicevox:50021/audio_query?text=%E3%81%82&speaker=3"
            )
            response = httpx.Response(
                500,
                request=request,
                json={"detail": "Internal Server Error"},
            )
            raise httpx.HTTPStatusError(
                "VOICEVOX synthesis failed",
                request=request,
                response=response,
            )

        async def fake_create_silent_audio(output_path, duration, _audio_params, ffmpeg_path="ffmpeg"):
            Path(output_path).write_bytes(b"RIFF")
            fake_create_silent_audio.calls.append((output_path, duration, ffmpeg_path))

        fake_create_silent_audio.calls = []

        monkeypatch.setattr(
            "zundamotion.components.audio.generator.get_speakers_info",
            fake_get_speakers_info,
        )
        monkeypatch.setattr(
            "zundamotion.components.audio.generator.generate_voice",
            fake_generate_voice,
        )
        monkeypatch.setattr(
            "zundamotion.components.audio.generator.create_silent_audio",
            fake_create_silent_audio,
        )

        audio_path, voice_usage, layer_segments = await generator.generate_audio(
            "こんにちは",
            {"speaker_id": 3, "speaker_name": "copetan"},
            "scene1_1",
        )

        assert audio_path == tmp_path / "scene1_1_speech.wav"
        assert audio_path.exists()
        assert voice_usage == []
        assert layer_segments == []
        assert fake_create_silent_audio.calls
        assert fake_create_silent_audio.calls[0][1] >= 1.0

    asyncio.run(_run())


def test_generate_audio_falls_back_to_silence_when_cache_wraps_voicevox_error(
    monkeypatch, tmp_path
):
    async def _run() -> None:
        cache_manager = StubWrappingCacheManager()
        generator = AudioGenerator(
            config={
                "voice": {
                    "enabled": True,
                    "url": "http://voicevox:50021",
                    "estimate_chars_per_second": 4.0,
                    "estimate_min_duration": 1.0,
                }
            },
            temp_dir=tmp_path,
            audio_params=AudioParams(),
            cache_manager=cache_manager,
        )

        async def fake_get_speakers_info(_url):
            return {
                3: {"speaker_name": "ずんだもん", "name": "ノーマル"},
            }

        async def fake_generate_voice(**_kwargs):
            request = httpx.Request(
                "POST", "http://voicevox:50021/audio_query?text=%E3%81%82&speaker=3"
            )
            response = httpx.Response(
                500,
                request=request,
                json={"detail": "Internal Server Error"},
            )
            raise httpx.HTTPStatusError(
                "VOICEVOX synthesis failed",
                request=request,
                response=response,
            )

        async def fake_create_silent_audio(output_path, duration, _audio_params, ffmpeg_path="ffmpeg"):
            Path(output_path).write_bytes(b"RIFF")
            fake_create_silent_audio.calls.append((output_path, duration, ffmpeg_path))

        fake_create_silent_audio.calls = []

        monkeypatch.setattr(
            "zundamotion.components.audio.generator.get_speakers_info",
            fake_get_speakers_info,
        )
        monkeypatch.setattr(
            "zundamotion.components.audio.generator.generate_voice",
            fake_generate_voice,
        )
        monkeypatch.setattr(
            "zundamotion.components.audio.generator.create_silent_audio",
            fake_create_silent_audio,
        )

        audio_path, voice_usage, layer_segments = await generator.generate_audio(
            "こんにちは",
            {"speaker_id": 3, "speaker_name": "copetan"},
            "scene1_1",
        )

        assert audio_path == tmp_path / "scene1_1_speech.wav"
        assert audio_path.exists()
        assert voice_usage == []
        assert layer_segments == []
        assert fake_create_silent_audio.calls

    asyncio.run(_run())
