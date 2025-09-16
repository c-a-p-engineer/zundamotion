import asyncio
from pathlib import Path

import pytest
from PIL import Image

from zundamotion.cache import CacheManager
from zundamotion.components.video import VideoRenderer


def test_mouth_animation_delayed_until_after_enter(monkeypatch, tmp_path):
    # 作業ディレクトリをテスト用に切り替え
    monkeypatch.chdir(tmp_path)

    assets_dir = tmp_path / "assets"
    char_dir = assets_dir / "characters" / "hero" / "default"
    mouth_dir = char_dir / "mouth"
    eyes_dir = char_dir / "eyes"
    bg_dir = assets_dir / "bg"

    for directory in [char_dir, mouth_dir, eyes_dir, bg_dir]:
        directory.mkdir(parents=True, exist_ok=True)

    def make_png(path: Path, color: tuple[int, int, int, int]) -> None:
        Image.new("RGBA", (32, 32), color=color).save(path)

    make_png(char_dir / "base.png", (0, 200, 0, 255))
    make_png(mouth_dir / "half.png", (0, 150, 0, 255))
    make_png(mouth_dir / "open.png", (0, 100, 0, 255))
    make_png(eyes_dir / "open.png", (255, 255, 255, 255))
    make_png(eyes_dir / "close.png", (0, 0, 0, 255))

    bg_path = bg_dir / "room.png"
    make_png(bg_path, (120, 120, 120, 255))

    audio_path = tmp_path / "speech.wav"
    audio_path.write_bytes(b"")

    temp_dir = tmp_path / "temp"
    temp_dir.mkdir()

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    cache = CacheManager(cache_dir)

    config = {"video": {}}
    renderer = VideoRenderer(config, temp_dir, cache, jobs="1", hw_kind=None, has_cuda_filters=False)

    monkeypatch.setenv("CHAR_CACHE_DISABLE", "1")
    monkeypatch.setenv("FACE_CACHE_DISABLE", "1")

    async def fake_has_audio_stream(_path: str) -> bool:
        return False

    monkeypatch.setattr(
        "zundamotion.components.video.renderer.has_audio_stream",
        fake_has_audio_stream,
    )

    captured: dict[str, list[str]] = {}

    async def fake_run(cmd, *args, **kwargs):  # type: ignore[override]
        captured["cmd"] = cmd

        class DummyProcess:
            returncode = 0
            stderr = ""
            stdout = ""

        return DummyProcess()

    monkeypatch.setattr(
        "zundamotion.components.video.renderer._run_ffmpeg_async",
        fake_run,
    )

    background_config = {"path": str(bg_path), "type": "image"}
    characters_config = [
        {
            "visible": True,
            "name": "hero",
            "expression": "default",
            "enter": "slide_left",
            "enter_duration": 0.5,
            "anchor": "bottom_center",
            "scale": 1.0,
        }
    ]

    face_anim = {
        "target_name": "hero",
        "mouth": [
            {"start": 0.0, "end": 0.2, "state": "half"},
            {"start": 0.2, "end": 0.4, "state": "open"},
            {"start": 0.4, "end": 0.8, "state": "open"},
        ],
        "eyes": [],
    }

    asyncio.run(
        renderer.render_clip(
            audio_path=audio_path,
            duration=1.0,
            background_config=background_config,
            characters_config=characters_config,
            output_filename="test_clip",
            face_anim=face_anim,
        )
    )

    cmd = captured["cmd"]
    filter_complex = cmd[cmd.index("-filter_complex") + 1]

    assert "mouth_open_scaled" in filter_complex
    assert "mouth_half_scaled" not in filter_complex

    mouth_segments = [
        part
        for part in filter_complex.split(";")
        if "mouth_open_scaled" in part and "overlay=" in part
    ]
    assert mouth_segments, "expected mouth overlay segment in filter_complex"
    for segment in mouth_segments:
        assert "between(t,0.500,0.800)" in segment
        assert "between(t,0.200" not in segment
