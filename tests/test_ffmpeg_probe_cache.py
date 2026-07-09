import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import zundamotion.utils.ffmpeg_probe as ffmpeg_probe
from zundamotion.utils.ffmpeg_audio import has_audio_stream


def test_has_audio_stream_deduplicates_parallel_media_info_probe(
    tmp_path: Path,
    monkeypatch,
) -> None:
    async def _run() -> None:
        media = tmp_path / "clip.mp4"
        media.write_bytes(b"fake-media")
        calls = 0

        async def fake_run_ffmpeg_async(cmd, context=None):
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.05)
            return SimpleNamespace(
                stdout=json.dumps(
                    {
                        "streams": [
                            {
                                "codec_type": "video",
                                "codec_name": "h264",
                                "width": 1920,
                                "height": 1080,
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
                        ]
                    }
                ),
                stderr="",
            )

        ffmpeg_probe.clear_probe_caches()
        monkeypatch.setitem(
            ffmpeg_probe.get_media_info.__globals__,
            "run_ffmpeg_async",
            fake_run_ffmpeg_async,
        )
        monkeypatch.setitem(
            has_audio_stream.__globals__,
            "get_media_info",
            ffmpeg_probe.get_media_info,
        )

        results = await asyncio.gather(
            has_audio_stream(str(media)),
            has_audio_stream(str(media)),
            has_audio_stream(str(media)),
        )

        assert results == [True, True, True]
        assert calls == 1

    asyncio.run(_run())


def test_media_duration_deduplicates_parallel_probe(
    tmp_path: Path,
    monkeypatch,
) -> None:
    async def _run() -> None:
        media = tmp_path / "clip.mp4"
        media.write_bytes(b"fake-media")
        calls = 0

        async def fake_run_ffmpeg_async(cmd, context=None):
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.05)
            return SimpleNamespace(
                stdout=json.dumps({"format": {"duration": "12.34"}}),
                stderr="",
            )

        ffmpeg_probe.clear_probe_caches()
        monkeypatch.setitem(
            ffmpeg_probe.get_media_duration.__globals__,
            "run_ffmpeg_async",
            fake_run_ffmpeg_async,
        )

        results = await asyncio.gather(
            ffmpeg_probe.get_media_duration(str(media)),
            ffmpeg_probe.get_media_duration(str(media)),
            ffmpeg_probe.get_media_duration(str(media)),
        )

        assert results == [12.34, 12.34, 12.34]
        assert calls == 1

    asyncio.run(_run())
