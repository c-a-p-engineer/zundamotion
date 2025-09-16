from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageColor

from zundamotion.components.subtitles.png import (
    _load_font_with_fallback,
    _render_subtitle_png,
)

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "DejaVuSans.ttf",
]


def _font_path() -> str:
    for candidate in FONT_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    return "DejaVuSans.ttf"


@pytest.fixture(scope="module")
def font_path() -> str:
    return _font_path()


def test_render_subtitle_with_rounded_background_and_border(tmp_path: Path, font_path: str) -> None:
    out_path = tmp_path / "rounded.png"
    style = {
        "font_path": font_path,
        "font_size": 48,
        "max_pixel_width": 640,
        "background": {
            "color": "#0041FF",
            "opacity": 0.75,
            "radius": 48,
            "border_color": "#FFFFFF",
            "border_width": 6,
            "border_opacity": 0.95,
            "padding": {"left": 96, "right": 96, "top": 32, "bottom": 32},
        },
    }

    width, height = _render_subtitle_png("スタイルテスト", style, str(out_path))
    assert out_path.exists()

    with Image.open(out_path) as img:
        assert img.size == (width, height)
        # Rounded corner should be transparent
        assert img.getpixel((0, 0))[3] == 0

        pad_left = style["background"]["padding"]["left"]
        pad_top = style["background"]["padding"]["top"]
        sample_pixel = img.getpixel((pad_left + 10, pad_top // 2))
        expected_rgb = ImageColor.getrgb(style["background"]["color"])
        assert sample_pixel[:3] == expected_rgb
        expected_alpha = int(round(style["background"]["opacity"] * 255))
        assert abs(sample_pixel[3] - expected_alpha) <= 1

        border_alpha = int(round(style["background"]["border_opacity"] * 255))
        top_y = min(
            max(0, style["background"]["border_width"] // 2),
            height - 1,
        )
        top_row = [img.getpixel((x, top_y)) for x in range(img.width)]
        assert any(
            abs(px[0] - 255) <= 1
            and abs(px[1] - 255) <= 1
            and abs(px[2] - 255) <= 1
            and abs(px[3] - border_alpha) <= 1
            for px in top_row
        )


def test_render_subtitle_background_image_masked(tmp_path: Path, font_path: str) -> None:
    image_path = tmp_path / "bg.png"
    Image.new("RGBA", (32, 32), (255, 0, 0, 255)).save(image_path)

    out_path = tmp_path / "image.png"
    style = {
        "font_path": font_path,
        "font_size": 40,
        "box_color": None,
        "background": {
            "image": str(image_path),
            "opacity": 0.5,
            "radius": 30,
            "padding": 40,
        },
    }

    width, height = _render_subtitle_png("画像背景", style, str(out_path))
    assert out_path.exists()

    with Image.open(out_path) as img:
        assert img.size == (width, height)
        assert img.getpixel((0, 0))[3] == 0  # rounded corner is transparent
        sample = img.getpixel((45, 45))
        assert sample[:3] == (255, 0, 0)
        assert abs(sample[3] - int(round(0.5 * 255))) <= 1


def test_line_spacing_offset_per_line_adjusts_height(tmp_path: Path, font_path: str) -> None:
    out_path = tmp_path / "spacing.png"
    style = {
        "font_path": font_path,
        "font_size": 32,
        "background": {
            "color": "#000000",
            "opacity": 1.0,
            "padding": 10,
        },
        "line_spacing_offset_per_line": 40,
    }

    _, height = _render_subtitle_png("line1\nline2", style, str(out_path))

    font = _load_font_with_fallback(font_path, style["font_size"])
    line_heights = []
    for line in ["line1", "line2"]:
        try:
            bbox = font.getbbox(line)
            line_heights.append(bbox[3] - bbox[1])
        except AttributeError:  # pragma: no cover - legacy PIL fallback
            line_heights.append(font.getsize(line)[1])
    text_height = sum(line_heights)
    padding_total = 20  # padding * 2
    expected_height = text_height + padding_total + style["line_spacing_offset_per_line"]
    assert height == expected_height


def test_render_subtitle_without_background_preserves_glyph_extents(
    tmp_path: Path, font_path: str
) -> None:
    text = "背景を完全にオフにしてテキストのみ表示する例です。"
    out_path = tmp_path / "text_only.png"
    style = {
        "font_path": font_path,
        "font_size": 48,
        "stroke_color": "black",
        "stroke_width": 3,
        "box_color": None,
        "background": {
            "color": None,
            "border_width": 0,
            "padding": 0,
        },
    }

    width, height = _render_subtitle_png(text, style, str(out_path))
    assert out_path.exists()

    with Image.open(out_path) as img:
        assert img.size == (width, height)
        bbox = img.getbbox()
        assert bbox is not None
        assert bbox[1] == 0
        assert bbox[3] == height
