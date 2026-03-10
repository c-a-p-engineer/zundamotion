import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from zundamotion.cache import CacheManager
from zundamotion.components.subtitles.generator import SubtitleGenerator


def test_build_subtitle_overlay_ignores_non_subtitle_xy_in_line_config(tmp_path):
    generator = SubtitleGenerator(
        {"subtitle": {"x": "(w-text_w)/2", "y": "h-100-text_h/2"}},
        CacheManager(tmp_path / "cache"),
    )

    async def fake_render(*_args, **_kwargs):
        return tmp_path / "subtitle.png", {"w": 320, "h": 96}

    generator.png_renderer.render = fake_render  # type: ignore[method-assign]

    extra_input, snippet = asyncio.run(
        generator.build_subtitle_overlay(
            text="字幕",
            duration=1.5,
            line_config={"x": 330, "y": 700},
            in_label="0:v",
            index=1,
            allow_cuda=False,
        )
    )

    assert extra_input["-i"].endswith("subtitle.png")
    assert "overlay=x='(W-w)/2':y='H-100-h/2'" in snippet


def test_build_subtitle_overlay_accepts_numeric_subtitle_xy(tmp_path):
    generator = SubtitleGenerator(
        {"subtitle": {"x": "(w-text_w)/2", "y": "h-100-text_h/2"}},
        CacheManager(tmp_path / "cache"),
    )

    async def fake_render(*_args, **_kwargs):
        return tmp_path / "subtitle.png", {"w": 320, "h": 96}

    generator.png_renderer.render = fake_render  # type: ignore[method-assign]

    _extra_input, snippet = asyncio.run(
        generator.build_subtitle_overlay(
            text="字幕",
            duration=1.5,
            line_config={"subtitle": {"x": 48, "y": 96}},
            in_label="0:v",
            index=1,
            allow_cuda=False,
        )
    )

    assert "overlay=x='48':y='96'" in snippet
