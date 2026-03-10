from pathlib import Path
import sys

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from zundamotion.components.subtitles.png import _estimate_auto_max_chars, _load_font_with_fallback, _render_subtitle_png


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
