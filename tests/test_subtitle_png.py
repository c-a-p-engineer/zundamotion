import asyncio
from pathlib import Path
import sys

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from zundamotion.components.subtitles.png import (
    SubtitlePNGRenderer,
    _estimate_auto_max_chars,
    _read_subtitle_dimensions_meta,
    _load_font_with_fallback,
    _render_subtitle_png,
)


class StubCacheManager:
    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir

    async def get_or_create(self, *, key_data, file_name, extension, creator_func):
        output_path = self.cache_dir / f"{file_name}.png"
        if output_path.exists():
            return output_path
        return await creator_func(output_path)


def test_estimate_auto_max_chars_returns_positive_value_for_cjk_text():
    font = _load_font_with_fallback(
        "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf", 40
    )

    max_chars = _estimate_auto_max_chars("今日は字幕の自動折り返しを確認します", font, 520)

    assert max_chars >= 4
    assert max_chars < len("今日は字幕の自動折り返しを確認します")


def test_render_subtitle_png_accepts_auto_max_chars(tmp_path):
    out_path = tmp_path / "subtitle.png"

    width, height = _render_subtitle_png(
        "これは自動計算された最大文字数で折り返されることを確認するための字幕です",
        {
            "font_path": "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf",
            "font_size": 40,
            "font_color": "white",
            "wrap_mode": "chars",
            "max_chars_per_line": "auto",
            "max_pixel_width": 520,
            "background": {"color": "#000000", "opacity": 0.5, "padding": 12},
        },
        str(out_path),
    )

    assert out_path.exists()
    assert width > 0
    assert height > 40

    with Image.open(out_path) as image:
        assert image.width == width
        assert image.height == height


def test_subtitle_png_renderer_reads_dimensions_from_sidecar_on_cache_hit(
    tmp_path, monkeypatch
):
    async def _run() -> None:
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        renderer = SubtitlePNGRenderer(StubCacheManager(cache_dir))
        style = {
            "font_path": "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf",
            "font_size": 40,
            "font_color": "white",
        }

        png_path, dims = await renderer.render("字幕", style)

        assert _read_subtitle_dimensions_meta(png_path) == dims

        def _raise_if_reopened(*_args, **_kwargs):
            raise AssertionError("subtitle PNG should not be reopened when sidecar exists")

        monkeypatch.setattr("zundamotion.components.subtitles.png.Image.open", _raise_if_reopened)

        cached_path, cached_dims = await renderer.render("字幕", style)

        assert cached_path == png_path
        assert cached_dims == dims

    asyncio.run(_run())


def test_subtitle_png_renderer_reuses_shared_executor(tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    renderer1 = SubtitlePNGRenderer(StubCacheManager(cache_dir))
    renderer2 = SubtitlePNGRenderer(StubCacheManager(cache_dir))

    assert renderer1._executor is renderer2._executor


def test_render_subtitle_png_hides_background_and_padding_when_show_is_false(tmp_path):
    visible_path = tmp_path / "visible.png"
    hidden_path = tmp_path / "hidden.png"
    style = {
        "font_path": "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf",
        "font_size": 40,
        "font_color": "white",
        "background": {
            "show": True,
            "color": "#000000",
            "opacity": 0.6,
            "padding": {"x": 32, "y": 20},
        },
    }

    visible_width, visible_height = _render_subtitle_png("字幕", style, str(visible_path))
    hidden_width, hidden_height = _render_subtitle_png(
        "字幕",
        {
            **style,
            "background": {
                "show": False,
                "color": "#000000",
                "opacity": 0.6,
                "padding": {"x": 32, "y": 20},
            },
        },
        str(hidden_path),
    )

    assert visible_width > hidden_width
    assert visible_height > hidden_height
