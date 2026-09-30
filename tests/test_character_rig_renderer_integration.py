from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from zundamotion.components.video.character_rig_materializer import (
    MaterializedCharacterRig,
)
from zundamotion.components.video.clip.characters import collect_character_inputs
from zundamotion.components.video.clip.face import apply_face_overlays


class _RigMaterializer:
    def __init__(self, assets: MaterializedCharacterRig | None) -> None:
        self.assets = assets
        self.calls = 0

    async def materialize(self, _config):
        self.calls += 1
        if self.assets is None:
            raise AssertionError("rig materializer must not run for PNG character")
        return self.assets


class _FaceCache:
    async def get_scaled_overlay(
        self,
        path: Path,
        _scale: float,
        _thr: int,
        horizontal_flip: bool = False,
        vertical_flip: bool = False,
    ) -> Path:
        return path


class _Renderer:
    def __init__(self, materializer: _RigMaterializer) -> None:
        self.character_rig_materializer = materializer
        self.video_params = SimpleNamespace(fps=30)
        self.scale_flags = "bicubic"
        self.face_cache = _FaceCache()


def _png(path: Path, color=(0, 255, 0, 255)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (20, 40), color).save(path)
    return path


def _assets(tmp_path: Path) -> MaterializedCharacterRig:
    root = tmp_path / "materialized"
    base = _png(root / "base.png")
    eyes = {
        "open": _png(root / "eyes-open.png", (0, 0, 255, 255)),
        "close": _png(root / "eyes-close.png", (255, 0, 0, 255)),
    }
    mouth = {
        "close": _png(root / "mouth-close.png", (0, 0, 0, 255)),
        "half": _png(root / "mouth-half.png", (255, 255, 0, 255)),
        "open": _png(root / "mouth-open.png", (255, 0, 255, 255)),
    }
    return MaterializedCharacterRig(
        source_path=tmp_path / "character.svg",
        raster_width=20,
        base=base,
        eyes=eyes,
        mouth=mouth,
    )


def test_collect_character_inputs_uses_materialized_rig_base_and_face_paths(
    tmp_path: Path,
) -> None:
    async def _run() -> None:
        assets = _assets(tmp_path)
        materializer = _RigMaterializer(assets)
        renderer = _Renderer(materializer)
        cmd: list[str] = []
        input_layers: list[dict] = []

        result = await collect_character_inputs(
            renderer=renderer,
            characters_config=[
                {
                    "name": "hero",
                    "visible": True,
                    "scale": 1.0,
                    "rig": {"path": "assets/characters/hero/character.svg"},
                }
            ],
            cmd=cmd,
            input_layers=input_layers,
            duration=1.0,
        )

        assert materializer.calls == 1
        assert result.any_visible is True
        assert result.metadata[0]["image_path"] == assets.base
        assert result.metadata[0]["source_width"] == 20
        assert result.metadata[0]["source_height"] == 40
        assert result.metadata[0]["rig_face_paths"] == assets.face_paths()
        assert str(assets.base.resolve()) in cmd

    asyncio.run(_run())


def test_collect_character_inputs_keeps_png_path_without_rig(
    tmp_path: Path,
    monkeypatch,
) -> None:
    async def _run() -> None:
        monkeypatch.chdir(tmp_path)
        base = _png(tmp_path / "assets" / "characters" / "hero" / "default" / "base.png")
        materializer = _RigMaterializer(None)
        renderer = _Renderer(materializer)
        cmd: list[str] = []
        input_layers: list[dict] = []

        result = await collect_character_inputs(
            renderer=renderer,
            characters_config=[
                {
                    "name": "hero",
                    "visible": True,
                    "scale": 1.0,
                }
            ],
            cmd=cmd,
            input_layers=input_layers,
            duration=1.0,
        )

        assert materializer.calls == 0
        assert result.metadata[0]["image_path"].resolve() == base.resolve()
        assert result.metadata[0]["rig_face_paths"] is None

    asyncio.run(_run())


def test_face_overlay_uses_materialized_rig_paths(
    tmp_path: Path,
) -> None:
    async def _run() -> None:
        assets = _assets(tmp_path)
        renderer = _Renderer(_RigMaterializer(assets))
        cmd: list[str] = []
        input_layers: list[dict] = []
        filter_parts: list[str] = []
        overlay_streams: list[str] = []
        overlay_filters: list[str] = []

        await apply_face_overlays(
            renderer=renderer,
            face_anim={
                "target_name": "hero",
                "mouth": [{"start": 0.0, "end": 0.3, "state": "half"}],
                "eyes": [{"start": 0.4, "end": 0.45, "state": "close"}],
            },
            subtitle_line_config={
                "characters": [{"name": "hero", "visible": True}]
            },
            char_overlay_placement={
                "hero": {
                    "x_expr": "10",
                    "y_expr": "20",
                    "scale_orig": "1.0",
                    "scale_expr": "1.000000",
                    "dynamic_scale": False,
                    "source_width": 20,
                    "source_height": 40,
                    "anchor": "bottom_center",
                    "move": None,
                    "rotate_expr": "0",
                    "rotate_active": False,
                    "opacity_expr": "1.000000",
                    "opacity_active": False,
                    "dynamic_position": False,
                    "expression": "default",
                    "asset_name": "hero",
                    "rig_face_paths": assets.face_paths(),
                }
            },
            duration=1.0,
            cmd=cmd,
            input_layers=input_layers,
            filter_complex_parts=filter_parts,
            overlay_streams=overlay_streams,
            overlay_filters=overlay_filters,
        )

        paths = {str(item.get("path")) for item in input_layers}
        assert str(assets.mouth["half"].resolve()) in paths
        assert str(assets.eyes["close"].resolve()) in paths
        assert len(overlay_streams) == 2
        assert all("overlay=x=10:y=20" in item for item in overlay_filters)

    asyncio.run(_run())
