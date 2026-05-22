import asyncio
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from zundamotion.cache import CacheManager
from zundamotion.components.video.badge_overlay_cache import BadgeOverlayCache


def test_badge_overlay_cache_renders_png_and_positions_top_right(tmp_path: Path) -> None:
    async def _run() -> None:
        cache = CacheManager(tmp_path / "cache")
        badge_cache = BadgeOverlayCache(cache)

        overlay = await badge_cache.get_badge_overlay(
            {"text": "重要", "position": "top-right"},
            video_width=1920,
            video_height=1080,
            font_path="",
        )

        badge_path = Path(overlay["src"])
        assert badge_path.exists()
        assert overlay["position"]["y"] == 36
        assert overlay["position"]["x"] > 0

        with Image.open(badge_path) as image:
            assert image.size[0] > 0
            assert image.size[1] > 0

    asyncio.run(_run())


def test_badge_overlay_cache_reuses_same_cached_png(tmp_path: Path) -> None:
    async def _run() -> None:
        cache = CacheManager(tmp_path / "cache")
        badge_cache = BadgeOverlayCache(cache)

        first = await badge_cache.get_badge_overlay(
            {"text": "頻出", "position": "top-right"},
            video_width=1280,
            video_height=720,
            font_path="",
        )
        second = await badge_cache.get_badge_overlay(
            {"text": "頻出", "position": "bottom-left"},
            video_width=1280,
            video_height=720,
            font_path="",
        )

        assert first["src"] == second["src"]
        assert first["position"] != second["position"]

    asyncio.run(_run())


def test_badge_overlay_cache_converts_start_end_to_overlay_timing(tmp_path: Path) -> None:
    async def _run() -> None:
        cache = CacheManager(tmp_path / "cache")
        badge_cache = BadgeOverlayCache(cache)

        overlay = await badge_cache.get_badge_overlay(
            {
                "text": "注意",
                "position": "top-left",
                "timing": {"start": 0.5, "end": 1.75},
            },
            video_width=1280,
            video_height=720,
            font_path="",
        )

        assert overlay["timing"] == {"start": 0.5, "duration": 1.25}

    asyncio.run(_run())


def test_badge_overlay_cache_supports_show_hide_line_markers(tmp_path: Path) -> None:
    async def _run() -> None:
        cache = CacheManager(tmp_path / "cache")
        badge_cache = BadgeOverlayCache(cache)

        overlay = await badge_cache.get_badge_overlay(
            {
                "text": "重要",
                "position": "top-right",
                "timing": {"show_on_line": "intro", "hide_on_line": 3},
            },
            video_width=1280,
            video_height=720,
            font_path="",
            line_markers={"intro": 0.75, "3": 2.5},
        )

        assert overlay["timing"] == {"start": 0.75, "duration": 1.75}

    asyncio.run(_run())


def test_badge_overlay_cache_auto_expands_width_for_longer_text(tmp_path: Path) -> None:
    async def _run() -> None:
        cache = CacheManager(tmp_path / "cache")
        badge_cache = BadgeOverlayCache(cache)

        short_overlay = await badge_cache.get_badge_overlay(
            {"text": "重要", "position": "top-left"},
            video_width=1280,
            video_height=720,
            font_path="",
        )
        long_overlay = await badge_cache.get_badge_overlay(
            {
                "text": "これは少し長めのバッジテキストです",
                "position": "top-left",
                "font_size": 42,
                "background": {
                    "show": True,
                    "color": "#111111",
                    "opacity": 0.72,
                    "radius": 24,
                    "border_color": "#FFFFFF",
                    "border_width": 3,
                    "border_opacity": 0.65,
                    "padding": {"left": 48, "right": 48, "top": 18, "bottom": 18},
                },
            },
            video_width=1280,
            video_height=720,
            font_path="",
        )

        with Image.open(short_overlay["src"]) as short_image:
            short_width = short_image.size[0]
        with Image.open(long_overlay["src"]) as long_image:
            long_width = long_image.size[0]

        assert long_width > short_width

    asyncio.run(_run())
