from __future__ import annotations

import asyncio
from types import SimpleNamespace

from zundamotion.components.pipeline_phases import bgm_phase
from zundamotion.components.pipeline_phases.bgm_phase import BGMPhase
from zundamotion.utils.ffmpeg_params import AudioParams


def _config(cache_dir, bgm_file):
    return {
        "system": {"cache_dir": str(cache_dir), "cache_bgm_mix": True},
        "script": {
            "bgm_layers": [
                {"id": "main", "file": str(bgm_file), "loop": True, "gain": -6}
            ]
        },
    }


def test_bgm_mix_cache_reuses_same_final_and_segments(monkeypatch, tmp_path) -> None:
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    final_video = cache_dir / "finalize_concat_key.mp4"
    final_video.write_bytes(b"video")
    bgm_file = tmp_path / "bgm.wav"
    bgm_file.write_bytes(b"audio")
    temp_dir = tmp_path / "work"
    temp_dir.mkdir()
    timeline = SimpleNamespace(
        bgm_events=[{"id": "main", "action": "start", "time": 0.0}]
    )
    calls = []

    async def fake_media_duration(path):
        return 10.0

    async def fake_audio_duration(path):
        return 3.0

    async def fake_add_bgm(input_path, output_path, **kwargs):
        calls.append((input_path, output_path))
        with open(output_path, "wb") as stream:
            stream.write(b"mixed")
        return "filter"

    monkeypatch.setattr(bgm_phase, "get_media_duration", fake_media_duration)
    monkeypatch.setattr(bgm_phase, "get_audio_duration", fake_audio_duration)
    monkeypatch.setattr(bgm_phase, "add_bgm_segments_to_video", fake_add_bgm)

    phase = BGMPhase(_config(cache_dir, bgm_file), temp_dir, AudioParams())
    first = asyncio.run(phase.run(final_video, timeline))
    second = asyncio.run(phase.run(final_video, timeline))

    assert first == second
    assert first.parent == cache_dir
    assert first.name.startswith("bgm_mix_")
    assert first.read_bytes() == b"mixed"
    assert len(calls) == 1


def test_bgm_mix_cache_key_changes_when_source_asset_changes(tmp_path) -> None:
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    final_video = cache_dir / "final.mp4"
    final_video.write_bytes(b"video")
    bgm_file = tmp_path / "bgm.wav"
    bgm_file.write_bytes(b"first")
    phase = BGMPhase(_config(cache_dir, bgm_file), tmp_path, AudioParams())
    segments = [
        {
            "id": "main",
            "timeline_start": 0.0,
            "timeline_end": 1.0,
            "source_start_pos": 0.0,
            "duration": 1.0,
            "fade_in": 0.0,
            "fade_out": 0.0,
            "gain": -6,
        }
    ]
    layers = phase.config["script"]["bgm_layers"]

    before = phase._bgm_mix_cache_path(
        final_video_path=final_video,
        bgm_layers=layers,
        segments=segments,
    )
    bgm_file.write_bytes(b"second-content")
    after = phase._bgm_mix_cache_path(
        final_video_path=final_video,
        bgm_layers=layers,
        segments=segments,
    )

    assert before is not None
    assert after is not None
    assert before != after


def test_bgm_mix_cache_is_disabled_for_temporary_final(monkeypatch, tmp_path) -> None:
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    final_video = tmp_path / "temporary-final.mp4"
    final_video.write_bytes(b"video")
    bgm_file = tmp_path / "bgm.wav"
    bgm_file.write_bytes(b"audio")
    temp_dir = tmp_path / "work"
    temp_dir.mkdir()
    timeline = SimpleNamespace(
        bgm_events=[{"id": "main", "action": "start", "time": 0.0}]
    )
    calls = []

    async def fake_media_duration(path):
        return 10.0

    async def fake_audio_duration(path):
        return 3.0

    async def fake_add_bgm(input_path, output_path, **kwargs):
        calls.append(output_path)
        with open(output_path, "wb") as stream:
            stream.write(b"mixed")
        return "filter"

    monkeypatch.setattr(bgm_phase, "get_media_duration", fake_media_duration)
    monkeypatch.setattr(bgm_phase, "get_audio_duration", fake_audio_duration)
    monkeypatch.setattr(bgm_phase, "add_bgm_segments_to_video", fake_add_bgm)

    phase = BGMPhase(_config(cache_dir, bgm_file), temp_dir, AudioParams())
    first = asyncio.run(phase.run(final_video, timeline))
    second = asyncio.run(phase.run(final_video, timeline))

    assert first == temp_dir / "final_with_bgm.mp4"
    assert second == first
    assert len(calls) == 2
    assert not list(cache_dir.glob("bgm_mix_*.mp4"))
