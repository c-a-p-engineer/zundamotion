from __future__ import annotations

import asyncio
from pathlib import Path
import wave

from zundamotion.components.video import VideoRenderer
from zundamotion.components.video.wait_clip_runtime import (
    WaitClipRuntimeMixin,
    _silent_frame_count,
    _write_finite_silence_wav,
)
from zundamotion.utils.ffmpeg_params import AudioParams


def test_public_video_renderer_routes_waits_through_finite_runtime() -> None:
    assert VideoRenderer.render_wait_clip is WaitClipRuntimeMixin.render_wait_clip


def test_finite_silence_wav_has_bounded_exact_frame_count(tmp_path: Path) -> None:
    path = tmp_path / "silence.wav"
    _write_finite_silence_wav(
        path,
        duration=0.125,
        sample_rate=48_000,
        channels=2,
    )

    with wave.open(str(path), "rb") as stream:
        assert stream.getframerate() == 48_000
        assert stream.getnchannels() == 2
        assert stream.getsampwidth() == 2
        assert stream.getnframes() == _silent_frame_count(0.125, 48_000)


class _DummyCache:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.key_data = None

    async def get_or_create(self, *, key_data, file_name, extension, creator_func):
        self.key_data = key_data
        path = self.root / f"{file_name}.{extension}"
        return await creator_func(path)


class _DummyRenderer(WaitClipRuntimeMixin):
    def __init__(self, root: Path) -> None:
        self.audio_params = AudioParams(sample_rate=48_000, channels=2)
        self.cache_manager = _DummyCache(root)
        self.render_kwargs = None

    async def render_clip(self, **kwargs):
        self.render_kwargs = kwargs
        return Path("/tmp/wait-output.mp4")


def test_wait_clip_delegates_to_common_clip_pipeline_with_finite_audio(tmp_path: Path) -> None:
    renderer = _DummyRenderer(tmp_path)
    result = asyncio.run(
        renderer.render_wait_clip(
            0.25,
            {"type": "image", "path": "bg.png"},
            "scene_1_2",
            {
                "background_effects": [{"type": "zoom"}],
                "screen_effects": [{"type": "fade"}],
            },
            characters_config=[{"id": "zundamon", "visible": True}],
            image_layer_overlays=[{"path": "overlay.png"}],
            extra_audio_overlays=[{"path": "sfx.wav"}],
        )
    )

    assert result == Path("/tmp/wait-output.mp4")
    assert renderer.render_kwargs is not None
    audio_path = Path(renderer.render_kwargs["audio_path"])
    assert audio_path.exists()
    assert renderer.render_kwargs["duration"] == 0.25
    assert renderer.render_kwargs["output_filename"] == "scene_1_2"
    assert renderer.render_kwargs["subtitle_text"] is None
    assert renderer.render_kwargs["characters_config"][0]["id"] == "zundamon"
    assert renderer.render_kwargs["background_effects"] == [{"type": "zoom"}]
    assert renderer.render_kwargs["screen_effects"] == [{"type": "fade"}]
    assert renderer.cache_manager.key_data["type"] == "finite_wait_silence"
    assert renderer.cache_manager.key_data["duration_us"] == 250_000

    with wave.open(str(audio_path), "rb") as stream:
        assert stream.getnframes() == 12_000
