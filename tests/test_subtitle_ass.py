import asyncio
from pathlib import Path
import subprocess
import sys

import pysubs2

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from zundamotion.components.subtitles.generator import SubtitleGenerator
from zundamotion.components.video.overlays import OverlayMixin
from zundamotion.utils.ffmpeg_params import VideoParams


class StubCacheManager:
    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)


class DummyOverlayRenderer(OverlayMixin):
    def __init__(self, temp_dir: Path, cache_dir: Path):
        self.ffmpeg_path = "ffmpeg"
        self.temp_dir = temp_dir
        self.video_params = VideoParams(width=320, height=180, fps=30)
        self.hw_kind = None
        self.gpu_overlay_backend = None
        self.scale_flags = "lanczos"
        self.subtitle_gen = SubtitleGenerator(
            {
                "subtitle": {
                    "render_mode": "ass",
                    "font_path": "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf",
                    "font_size": 32,
                    "font_color": "white",
                    "stroke_color": "black",
                    "stroke_width": 2,
                }
            },
            StubCacheManager(cache_dir),
        )

    def _thread_flags(self):
        return []


def test_build_ass_subtitle_file_writes_events_and_styles(tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    gen = SubtitleGenerator(
        {
            "video": {
                "width": 1920,
                "height": 1080,
            },
            "subtitle": {
                "font_path": "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf",
                "font_size": 64,
                "size": 42,
                "font_color": "white",
                "stroke_color": "black",
                "stroke_width": 2,
                "wrap_mode": "chars",
                "max_chars_per_line": 10,
                "x": "(w-text_w)/2",
                "y": "h-100-text_h/2",
            }
        },
        StubCacheManager(cache_dir),
    )

    out_path = tmp_path / "sample.ass"
    gen.build_ass_subtitle_file(
        [
            {
                "text": "これは1行目の字幕です。長いので折り返します。",
                "start": 0.0,
                "duration": 1.5,
                "line_config": {},
            },
            {
                "text": "2行目\n改行あり",
                "start": 2.0,
                "duration": 1.8,
                "line_config": {
                    "subtitle": {
                        "size": 48,
                        "color": "#90EE90",
                        "outline": "#143d14",
                    }
                },
            },
        ],
        out_path,
    )

    assert out_path.exists()
    raw_text = out_path.read_text(encoding="utf-8")
    assert r"{\an5\pos(960,980)}" in raw_text
    assert r"これは1行目の字幕で\Nす。長いので折り返し\Nます。" in raw_text
    assert r"{\an5\pos(960,980)}2行目\N改行あり" in raw_text

    subs = pysubs2.load(str(out_path))
    assert len(subs) == 2
    assert subs.info["PlayResX"] == "1920"
    assert subs.info["PlayResY"] == "1080"
    assert subs[0].text == r"{\an5\pos(960,980)}これは1行目の字幕で\Nす。長いので折り返し\Nます。"
    assert subs[1].text == r"{\an5\pos(960,980)}2行目\N改行あり"
    assert len(subs.styles) >= 2
    assert subs[0].style != subs[1].style
    assert subs.styles[subs[0].style].fontsize == 42.0
    assert subs.styles[subs[1].style].fontsize == 48.0
    assert (subs.styles[subs[1].style].primarycolor.r, subs.styles[subs[1].style].primarycolor.g, subs.styles[subs[1].style].primarycolor.b) == (144, 238, 144)
    assert (subs.styles[subs[1].style].outlinecolor.r, subs.styles[subs[1].style].outlinecolor.g, subs.styles[subs[1].style].outlinecolor.b) == (20, 61, 20)


def test_build_ass_subtitle_file_maps_background_visibility_and_opacity(tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    gen = SubtitleGenerator(
        {
            "subtitle": {
                "font_path": "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf",
                "font_size": 40,
                "font_color": "white",
                "stroke_color": "black",
                "stroke_width": 2,
                "background": {
                    "show": True,
                    "color": "#224466",
                    "opacity": 0.4,
                },
            }
        },
        StubCacheManager(cache_dir),
    )

    out_path = tmp_path / "background.ass"
    gen.build_ass_subtitle_file(
        [
            {
                "text": "背景あり",
                "start": 0.0,
                "duration": 1.0,
                "line_config": {},
            },
            {
                "text": "背景なし",
                "start": 1.2,
                "duration": 1.0,
                "line_config": {"subtitle": {"background": {"show": False}}},
            },
        ],
        out_path,
    )

    subs = pysubs2.load(str(out_path))
    style_with_bg = subs.styles[subs[0].style]
    style_without_bg = subs.styles[subs[1].style]

    assert style_with_bg.borderstyle == 3
    assert (style_with_bg.backcolor.r, style_with_bg.backcolor.g, style_with_bg.backcolor.b) == (
        34,
        68,
        102,
    )
    assert style_with_bg.backcolor.a == 153
    assert (style_with_bg.outlinecolor.r, style_with_bg.outlinecolor.g, style_with_bg.outlinecolor.b) == (
        34,
        68,
        102,
    )
    assert style_with_bg.outlinecolor.a == 153
    assert style_without_bg.borderstyle == 1


def test_apply_subtitle_overlays_ass_renders_output(tmp_path):
    base_video = tmp_path / "base.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=320x180:d=1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(base_video),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    renderer = DummyOverlayRenderer(tmp_path, tmp_path / "cache")
    out_path = asyncio.run(
        renderer.apply_subtitle_overlays(
            base_video,
            [
                {
                    "text": "ASS 字幕テスト",
                    "start": 0.0,
                    "duration": 0.9,
                    "line_config": {},
                }
            ],
        )
    )

    assert out_path.exists()
    assert out_path.stat().st_size > 0
