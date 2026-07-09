from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

import zundamotion.utils.ffmpeg_probe as ffmpeg_probe


def test_probe_asset_reads_image_metadata_and_uses_memo(tmp_path: Path, monkeypatch) -> None:
    image_path = tmp_path / "slide.png"
    Image.new("RGB", (320, 180), "#ffffff").save(image_path)
    opened = 0
    original_open = Image.open

    def counting_open(*args, **kwargs):
        nonlocal opened
        opened += 1
        return original_open(*args, **kwargs)

    ffmpeg_probe.clear_probe_caches()
    monkeypatch.setattr(Image, "open", counting_open)

    first = ffmpeg_probe.get_image_info(str(image_path))
    second = ffmpeg_probe.get_image_info(str(image_path))

    assert first == second
    assert first["width"] == 320
    assert first["height"] == 180
    assert opened == 1


def test_probe_asset_collects_media_info_and_duration(tmp_path: Path, monkeypatch) -> None:
    async def _run() -> None:
        media = tmp_path / "clip.mp4"
        media.write_bytes(b"fake-media")
        calls = 0

        async def fake_run_ffmpeg_async(cmd, context=None):
            nonlocal calls
            calls += 1
            if "-show_streams" in cmd:
                stdout = json.dumps(
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
                            },
                        ]
                    }
                )
            else:
                stdout = json.dumps({"format": {"duration": "3.5"}})
            return SimpleNamespace(stdout=stdout, stderr="")

        ffmpeg_probe.clear_probe_caches()
        monkeypatch.setattr(ffmpeg_probe, "run_ffmpeg_async", fake_run_ffmpeg_async)

        metadata = await ffmpeg_probe.probe_asset(str(media))
        assert metadata["kind"] == "media"
        assert metadata["video"]["width"] == 1920
        assert metadata["audio"]["channels"] == 2
        assert metadata["duration"] == 3.5
        assert calls == 2

    asyncio.run(_run())
