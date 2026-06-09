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
