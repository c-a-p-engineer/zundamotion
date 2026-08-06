from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from zundamotion.utils import ffmpeg_probe


def _combined_payload(*, duration="12.34") -> str:
    return json.dumps(
        {
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1280,
                    "height": 720,
                    "pix_fmt": "yuv420p",
                    "r_frame_rate": "30/1",
                },
                {
                    "codec_type": "audio",
                    "codec_name": "aac",
                    "sample_rate": "48000",
                    "channels": 2,
                    "channel_layout": "stereo",
                },
            ],
            "format": {} if duration is None else {"duration": duration},
        }
    )


def test_media_info_then_duration_uses_one_probe(monkeypatch, tmp_path) -> None:
    media_path = tmp_path / "sample.mp4"
    media_path.write_bytes(b"media")
    calls = []

    async def fake_run(command, context=None):
        calls.append((command, context))
        return SimpleNamespace(stdout=_combined_payload())

    monkeypatch.setattr(ffmpeg_probe, "run_ffmpeg_async", fake_run)
    ffmpeg_probe.clear_probe_caches()

    info = asyncio.run(ffmpeg_probe.get_media_info(str(media_path), caller="info"))
    duration = asyncio.run(
        ffmpeg_probe.get_media_duration(str(media_path), caller="duration")
    )

    assert info["video"]["width"] == 1280
    assert info["audio"]["sample_rate"] == 48000
    assert info["duration"] == 12.34
    assert duration == 12.34
    assert len(calls) == 1
    assert "-show_streams" in calls[0][0]
    assert "-show_format" in calls[0][0]


def test_duration_then_media_info_uses_one_probe(monkeypatch, tmp_path) -> None:
    media_path = tmp_path / "sample.mp4"
    media_path.write_bytes(b"media")
    calls = []

    async def fake_run(command, context=None):
        calls.append(command)
        return SimpleNamespace(stdout=_combined_payload(duration="7.895"))

    monkeypatch.setattr(ffmpeg_probe, "run_ffmpeg_async", fake_run)
    ffmpeg_probe.clear_probe_caches()

    duration = asyncio.run(ffmpeg_probe.get_audio_duration(str(media_path)))
    info = asyncio.run(ffmpeg_probe.get_media_info(str(media_path)))

    assert duration == 7.89
    assert info["duration"] == 7.89
    assert len(calls) == 1


def test_probe_asset_reuses_combined_duration(monkeypatch, tmp_path) -> None:
    media_path = tmp_path / "sample.mp4"
    media_path.write_bytes(b"media")
    calls = []

    async def fake_run(command, context=None):
        calls.append(command)
        return SimpleNamespace(stdout=_combined_payload(duration="3.25"))

    monkeypatch.setattr(ffmpeg_probe, "run_ffmpeg_async", fake_run)
    ffmpeg_probe.clear_probe_caches()

    metadata = asyncio.run(ffmpeg_probe.probe_asset(str(media_path)))

    assert metadata["duration"] == 3.25
    assert metadata["video"]["codec_name"] == "h264"
    assert len(calls) == 1


def test_missing_format_duration_falls_back_once(monkeypatch, tmp_path) -> None:
    media_path = tmp_path / "sample.mp4"
    media_path.write_bytes(b"media")
    calls = []

    async def fake_run(command, context=None):
        calls.append(command)
        if "-show_streams" in command:
            return SimpleNamespace(stdout=_combined_payload(duration=None))
        return SimpleNamespace(stdout=json.dumps({"format": {"duration": "4.56"}}))

    monkeypatch.setattr(ffmpeg_probe, "run_ffmpeg_async", fake_run)
    ffmpeg_probe.clear_probe_caches()

    duration = asyncio.run(ffmpeg_probe.get_media_duration(str(media_path)))
    info = asyncio.run(ffmpeg_probe.get_media_info(str(media_path)))

    assert duration == 4.56
    assert info["duration"] is None
    assert len(calls) == 2
