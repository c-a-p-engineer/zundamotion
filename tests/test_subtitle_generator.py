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


def test_resolve_render_mode_for_line_configs_defaults_to_png_for_simple_style(tmp_path):
    generator = SubtitleGenerator(
        {"subtitle": {"background": {"show": True, "color": "#000000"}}},
        CacheManager(tmp_path / "cache"),
    )

    mode = generator.resolve_render_mode_for_line_configs(
        [
            {"subtitle": {"background": {"show": True, "color": "#0041FF", "opacity": 0.7}}},
            {"subtitle": {"color": "#7CFF4F"}},
        ]
    )

    assert mode == "png"


def test_resolve_render_mode_for_line_configs_auto_uses_ass_for_simple_style(tmp_path):
    generator = SubtitleGenerator(
        {"subtitle": {"render_mode": "auto", "background": {"show": True, "color": "#000000"}}},
        CacheManager(tmp_path / "cache"),
    )

    mode = generator.resolve_render_mode_for_line_configs(
        [
            {"subtitle": {"background": {"show": True, "color": "#0041FF", "opacity": 0.7}}},
            {"subtitle": {"color": "#7CFF4F"}},
        ]
    )

    assert mode == "ass"


def test_resolve_render_mode_for_line_configs_line_auto_overrides_root_png(tmp_path):
    generator = SubtitleGenerator(
        {"subtitle": {"render_mode": "png", "background": {"show": True, "color": "#000000"}}},
        CacheManager(tmp_path / "cache"),
    )

    mode = generator.resolve_render_mode_for_line_configs(
        [
            {
                "subtitle": {
                    "render_mode": "auto",
                    "background": {"show": True, "color": "#0041FF", "opacity": 0.7},
                }
            }
        ]
    )

    assert mode == "ass"


def test_resolve_render_mode_for_line_configs_uses_png_when_background_is_decorated(tmp_path):
    generator = SubtitleGenerator(
        {"subtitle": {}},
        CacheManager(tmp_path / "cache"),
    )

    mode = generator.resolve_render_mode_for_line_configs(
        [
            {
                "subtitle": {
                    "background": {
                        "show": True,
                        "color": "#0041FF",
                        "radius": 24,
                    }
                }
            }
        ]
    )

    assert mode == "png"


def test_resolve_render_mode_for_line_configs_auto_uses_png_when_background_is_decorated(tmp_path):
    generator = SubtitleGenerator(
        {"subtitle": {"render_mode": "auto"}},
        CacheManager(tmp_path / "cache"),
    )

    mode = generator.resolve_render_mode_for_line_configs(
        [
            {
                "subtitle": {
                    "background": {
                        "show": True,
                        "color": "#0041FF",
                        "radius": 24,
                    }
                }
            }
        ]
    )

    assert mode == "png"


def test_resolve_render_mode_for_line_configs_ignores_legacy_prefer_ass_option(tmp_path):
    generator = SubtitleGenerator(
        {
            "subtitle": {
                "prefer_ass_for_static_background": True,
                "background": {"show": True, "color": "#000000", "radius": 24},
            }
        },
        CacheManager(tmp_path / "cache"),
    )

    mode = generator.resolve_render_mode_for_line_configs([{"subtitle": {}}])

    assert mode == "png"


def test_resolve_render_mode_for_line_configs_ass_falls_back_to_png_for_image_background(tmp_path):
    generator = SubtitleGenerator(
        {"subtitle": {"render_mode": "ass"}},
        CacheManager(tmp_path / "cache"),
    )

    mode = generator.resolve_render_mode_for_line_configs(
        [{"subtitle": {"background": {"show": True, "image_path": "subtitle-bg.png"}}}]
    )

    assert mode == "png"


def test_resolve_render_mode_for_line_configs_uses_png_when_background_image_is_present(tmp_path):
    generator = SubtitleGenerator(
        {"subtitle": {}},
        CacheManager(tmp_path / "cache"),
    )

    mode = generator.resolve_render_mode_for_line_configs(
        [{"subtitle": {"background": {"show": True, "image_path": "subtitle-bg.png"}}}]
    )

    assert mode == "png"


def test_resolve_render_mode_for_line_configs_uses_png_when_subtitle_effects_are_present(tmp_path):
    generator = SubtitleGenerator(
        {"subtitle": {}},
        CacheManager(tmp_path / "cache"),
    )

    mode = generator.resolve_render_mode_for_line_configs(
        [{"subtitle": {"effects": [{"type": "text:bounce_text", "amplitude": 24}]}}]
    )

    assert mode == "png"
