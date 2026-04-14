import asyncio
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from zundamotion.components.video.clip.characters import (
    build_character_overlays,
    collect_character_inputs,
    is_horizontal_flip_enabled,
    is_vertical_flip_enabled,
)
from zundamotion.components.video.face_overlay_cache import FaceOverlayCache


class _RecordingFaceCache:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def get_scaled_overlay(
        self,
        path: Path,
        scale: float,
        thr: int | None,
        horizontal_flip: bool = False,
        vertical_flip: bool = False,
    ) -> Path:
        self.calls.append(
            {
                "path": path,
                "scale": scale,
                "thr": thr,
                "horizontal_flip": horizontal_flip,
                "vertical_flip": vertical_flip,
            }
        )
        return path


class _Renderer:
    def __init__(self) -> None:
        self.face_cache = _RecordingFaceCache()
        self.scale_filter = "scale_cuda"
        self.scale_flags = "bicubic"
        self.video_params = SimpleNamespace(width=1920, height=1080)


def test_is_horizontal_flip_enabled_accepts_supported_spellings() -> None:
    assert is_horizontal_flip_enabled({"flip_x": True})
    assert is_horizontal_flip_enabled({"flip": "horizontal"})
    assert is_horizontal_flip_enabled({"mirror": "yes"})
    assert not is_horizontal_flip_enabled({"flip_x": False})
    assert not is_horizontal_flip_enabled({"flip": "vertical"})


def test_is_vertical_flip_enabled_accepts_supported_spellings() -> None:
    assert is_vertical_flip_enabled({"flip_y": True})
    assert is_vertical_flip_enabled({"flip": "vertical"})
    assert is_vertical_flip_enabled({"flip": "y"})
    assert not is_vertical_flip_enabled({"flip_y": False})
    assert not is_vertical_flip_enabled({"flip": "horizontal"})


def test_collect_character_inputs_preprocesses_flips_even_without_scaling(
    monkeypatch, tmp_path: Path
) -> None:
    async def _run() -> None:
        character_root = tmp_path / "assets" / "characters" / "hero" / "default"
        character_root.mkdir(parents=True)
        Image.new("RGBA", (8, 4), (255, 0, 0, 255)).save(character_root / "base.png")
        monkeypatch.chdir(tmp_path)

        renderer = _Renderer()
        inputs = await collect_character_inputs(
            renderer=renderer,
            characters_config=[
                {
                    "name": "hero",
                    "visible": True,
                    "expression": "default",
                    "scale": 1.0,
                    "flip_x": True,
                    "flip_y": True,
                }
            ],
            cmd=[],
            input_layers=[],
        )

        assert renderer.face_cache.calls[0]["horizontal_flip"] is True
        assert renderer.face_cache.calls[0]["vertical_flip"] is True
        assert inputs.effective_scales[0] == 1.0
        assert inputs.metadata[0]["preprocessed_flip_x"] is True
        assert inputs.metadata[0]["preprocessed_flip_y"] is True

    asyncio.run(_run())


def test_build_character_overlays_adds_flip_filters_when_cache_did_not_preprocess(
    monkeypatch, tmp_path: Path
) -> None:
    character_root = tmp_path / "assets" / "characters" / "hero" / "default"
    character_root.mkdir(parents=True)
    image_path = character_root / "base.png"
    Image.new("RGBA", (80, 100), (255, 0, 0, 255)).save(image_path)
    monkeypatch.chdir(tmp_path)

    filter_complex_parts: list[str] = []
    overlay_streams: list[str] = []
    overlay_filters: list[str] = []

    placements = build_character_overlays(
        renderer=_Renderer(),
        characters_config=[
            {
                "name": "hero",
                "visible": True,
                "expression": "default",
                "scale": 1.0,
                "flip_x": True,
                "flip_y": True,
            }
        ],
        duration=1.0,
        character_indices={0: 1},
        char_effective_scale={0: 1.0},
        filter_complex_parts=filter_complex_parts,
        overlay_streams=overlay_streams,
        overlay_filters=overlay_filters,
        use_cuda_filters=False,
        use_opencl=False,
        metadata={
            0: {
                "image_path": image_path,
                "preprocessed_flip_x": False,
                "preprocessed_flip_y": False,
            }
        },
    )

    assert any(",hflip,vflip[" in part for part in filter_complex_parts)
    assert placements["hero"]["flip_x"] is True
    assert placements["hero"]["flip_y"] is True


def test_face_overlay_cache_can_mirror_and_flip_image(tmp_path: Path) -> None:
    class _CacheManager:
        async def get_or_create(self, *, creator_func, **_kwargs):
            out = tmp_path / "cached.png"
            return await creator_func(out)

    src = tmp_path / "src.png"
    img = Image.new("RGBA", (2, 2))
    img.putpixel((0, 0), (255, 0, 0, 255))
    img.putpixel((1, 0), (0, 0, 255, 255))
    img.putpixel((0, 1), (0, 255, 0, 255))
    img.putpixel((1, 1), (255, 255, 0, 255))
    img.save(src)

    async def _run() -> None:
        out = await FaceOverlayCache(_CacheManager()).get_scaled_overlay(
            src,
            1.0,
            None,
            horizontal_flip=True,
            vertical_flip=True,
        )
        mirrored = Image.open(out).convert("RGBA")
        assert mirrored.getpixel((0, 0)) == (255, 255, 0, 255)
        assert mirrored.getpixel((1, 0)) == (0, 255, 0, 255)
        assert mirrored.getpixel((0, 1)) == (0, 0, 255, 255)
        assert mirrored.getpixel((1, 1)) == (255, 0, 0, 255)

    asyncio.run(_run())
