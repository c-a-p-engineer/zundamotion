import asyncio
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from zundamotion.cache import CacheManager
from zundamotion.components.video.character_image_resolver import CharacterImageResolver
from zundamotion.components.video.image_color_filter_cache import ImageColorFilterCache
from zundamotion.components.video.clip.characters import collect_character_inputs


class _FaceCache:
    async def get_scaled_overlay(self, path: Path, *_args, **_kwargs) -> Path:
        return path


def _make_character(root: Path, color=(255, 0, 0, 255)) -> Path:
    image_path = root / "assets" / "characters" / "hero" / "default" / "base.png"
    image_path.parent.mkdir(parents=True)
    Image.new("RGBA", (2, 1), color).save(image_path)
    return image_path


def _save_test_rgba(
    path: Path,
    pixels: list[tuple[int, int, int, int]],
    size: tuple[int, int],
) -> None:
    image = Image.new("RGBA", size)
    image.putdata(pixels)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def test_color_filter_preserves_alpha_and_reuses_cache(tmp_path: Path, monkeypatch) -> None:
    async def _run() -> None:
        source_path = _make_character(tmp_path, (255, 0, 0, 77))
        monkeypatch.chdir(tmp_path)
        cache = CharacterImageResolver(ImageColorFilterCache(CacheManager(tmp_path / "cache")))

        first = await cache.resolve_image(
            "hero",
            "default",
            {"hue": 120, "saturation": 1.0, "brightness": 1.0},
        )
        second = await cache.resolve_image(
            "hero",
            "default",
            {"hue": 120, "saturation": 1.0, "brightness": 1.0},
        )

        assert first == second
        assert first != source_path
        with Image.open(first) as filtered:
            red, green, blue, alpha = filtered.convert("RGBA").getpixel((0, 0))
        assert green > red
        assert green > blue
        assert alpha == 77

    asyncio.run(_run())


def test_color_filter_cache_changes_when_source_changes(
    tmp_path: Path, monkeypatch
) -> None:
    async def _run() -> None:
        source_path = _make_character(tmp_path)
        monkeypatch.chdir(tmp_path)
        cache = CharacterImageResolver(ImageColorFilterCache(CacheManager(tmp_path / "cache")))
        settings = {"hue": 20, "saturation": 1.0, "brightness": 1.0}

        first = await cache.resolve_image("hero", "default", settings)
        Image.new("RGBA", (2, 1), (0, 0, 255, 255)).save(source_path)
        second = await cache.resolve_image("hero", "default", settings)

        assert first != second

    asyncio.run(_run())


def test_collect_character_inputs_uses_filtered_png(tmp_path: Path, monkeypatch) -> None:
    async def _run() -> None:
        source_path = _make_character(tmp_path)
        monkeypatch.chdir(tmp_path)
        cache_manager = CacheManager(tmp_path / "cache")
        renderer = SimpleNamespace(
            character_image_resolver=CharacterImageResolver(
                ImageColorFilterCache(cache_manager)
            ),
            face_cache=_FaceCache(),
        )
        command: list[str] = []

        inputs = await collect_character_inputs(
            renderer=renderer,
            characters_config=[
                {
                    "name": "hero",
                    "visible": True,
                    "color_filter": {"hue": 240, "saturation": 1.0, "brightness": 1.0},
                }
            ],
            cmd=command,
            input_layers=[],
        )

        filtered_path = Path(command[-1])
        assert filtered_path == inputs.metadata[0]["image_path"].resolve()
        assert filtered_path != source_path.resolve()

    asyncio.run(_run())


def test_collect_character_inputs_can_use_alias_with_shared_asset(
    tmp_path: Path, monkeypatch
) -> None:
    async def _run() -> None:
        source_path = _make_character(tmp_path)
        monkeypatch.chdir(tmp_path)
        renderer = SimpleNamespace(face_cache=_FaceCache())

        inputs = await collect_character_inputs(
            renderer=renderer,
            characters_config=[
                {
                    "name": "red-hero",
                    "asset_name": "hero",
                    "visible": True,
                }
            ],
            cmd=[],
            input_layers=[],
        )

        assert inputs.metadata[0]["name"] == "red-hero"
        assert inputs.metadata[0]["asset_name"] == "hero"
        assert inputs.metadata[0]["image_path"] == source_path.relative_to(tmp_path)

    asyncio.run(_run())


def test_color_filter_targets_only_recolors_top_dark_pixels(
    tmp_path: Path, monkeypatch
) -> None:
    async def _run() -> None:
        source_path = tmp_path / "assets" / "characters" / "hero" / "default" / "base.png"
        _save_test_rgba(
            source_path,
            [
                (25, 25, 25, 255),
                (230, 210, 190, 255),
                (30, 30, 30, 255),
                (10, 10, 10, 0),
            ],
            (2, 2),
        )
        monkeypatch.chdir(tmp_path)
        cache = CharacterImageResolver(ImageColorFilterCache(CacheManager(tmp_path / "cache")))

        filtered_path = await cache.resolve_image(
            "hero",
            "default",
            {
                "targets": [
                    {
                        "name": "hair",
                        "region": {"type": "top", "ratio": 0.5},
                        "select": {"color": {"mode": "luma", "min": 0, "max": 90}},
                        "adjust": {"hue": 330, "saturation": 1.6, "brightness": 1.4},
                    }
                ]
            },
        )

        with Image.open(filtered_path) as filtered:
            pixels = list(filtered.convert("RGBA").getdata())

        assert pixels[0][:3] != (25, 25, 25)
        assert len(set(pixels[0][:3])) > 1
        assert pixels[1][:3] == (230, 210, 190)
        assert pixels[2][:3] == (30, 30, 30)
        assert pixels[3][3] == 0

    asyncio.run(_run())


def test_color_filter_targets_can_use_rect_and_rgb_distance(
    tmp_path: Path, monkeypatch
) -> None:
    async def _run() -> None:
        source_path = tmp_path / "assets" / "characters" / "hero" / "default" / "base.png"
        _save_test_rgba(
            source_path,
            [
                (26, 26, 26, 255),
                (100, 100, 100, 255),
                (26, 26, 26, 255),
                (26, 26, 26, 255),
            ],
            (2, 2),
        )
        monkeypatch.chdir(tmp_path)
        cache = CharacterImageResolver(ImageColorFilterCache(CacheManager(tmp_path / "cache")))

        filtered_path = await cache.resolve_image(
            "hero",
            "default",
            {
                "targets": [
                    {
                        "name": "rect-dark",
                        "region": {
                            "type": "rect",
                            "x": 0.0,
                            "y": 0.0,
                            "width": 0.5,
                            "height": 0.5,
                        },
                        "select": {
                            "color": {
                                "mode": "rgb_distance",
                                "color": "#1a1a1a",
                                "tolerance": 5,
                            }
                        },
                        "adjust": {"hue": 220, "saturation": 1.4, "brightness": 1.5},
                    }
                ]
            },
        )

        with Image.open(filtered_path) as filtered:
            pixels = list(filtered.convert("RGBA").getdata())

        assert pixels[0][:3] != (26, 26, 26)
        assert pixels[1][:3] == (100, 100, 100)
        assert pixels[2][:3] == (26, 26, 26)
        assert pixels[3][:3] == (26, 26, 26)

    asyncio.run(_run())
