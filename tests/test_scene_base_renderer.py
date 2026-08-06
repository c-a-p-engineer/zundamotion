import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from zundamotion.components.pipeline_phases.video_phase.scene_base_plan import (
    SceneBasePlan,
)
from zundamotion.components.pipeline_phases.video_phase.scene_renderer import (
    SceneRenderer,
)
import zundamotion.components.pipeline_phases.video_phase.scene_base_renderer as base_module


class _CacheManager:
    def __init__(self, tmp_path: Path) -> None:
        self.cache_dir = tmp_path / "cache"
        self.calls = []

    async def get_or_create(self, **kwargs):
        self.calls.append(kwargs)
        output = self.cache_dir / f"{kwargs['file_name']}.{kwargs['extension']}"
        output.parent.mkdir(parents=True, exist_ok=True)
        return await kwargs["creator_func"](output)


class _VideoRenderer:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.scale_flags = "lanczos"
        self.composited_calls = []
        self.base_calls = []
        self.loop_calls = []
        self.fail_composited = False

    async def render_scene_base_composited(self, *args):
        self.composited_calls.append(args)
        if self.fail_composited:
            raise RuntimeError("base failed")
        path = self.tmp_path / "composited.mp4"
        path.write_bytes(b"base")
        return path

    async def render_scene_base(self, *args):
        self.base_calls.append(args)
        path = self.tmp_path / "shared.mp4"
        path.write_bytes(b"shared")
        return path

    async def render_looped_background_video(self, *args, **kwargs):
        self.loop_calls.append((args, kwargs))
        path = self.tmp_path / "loop.mp4"
        path.write_bytes(b"loop")
        return path


def _plan(**overrides) -> SceneBasePlan:
    values = {
        "static_overlays": [],
        "static_character_keys": set(),
        "static_insert_in_base": False,
        "common_insert_video_path": None,
        "should_generate_base": True,
        "base_background_layout": {
            "fit": "stretch",
            "fill_color": "black",
            "anchor": "middle_center",
            "position": {"x": "0", "y": "0"},
        },
        "total_lines": 2,
        "minimum_lines": 6,
        "scene_copy": False,
        "detection_error": None,
    }
    values.update(overrides)
    return SceneBasePlan(**values)


def _renderer(tmp_path: Path) -> SceneRenderer:
    renderer = object.__new__(SceneRenderer)
    renderer.video_params = SimpleNamespace(width=320, height=180, fps=30)
    renderer.audio_params = SimpleNamespace(sample_rate=48000)
    renderer.hw_kind = None
    renderer.cache_manager = _CacheManager(tmp_path)
    renderer.video_renderer = _VideoRenderer(tmp_path)
    return renderer


def test_prepare_scene_base_renders_static_overlays(tmp_path: Path) -> None:
    async def _run() -> None:
        renderer = _renderer(tmp_path)
        overlay = {"path": str(tmp_path / "character.png")}

        result = await renderer._prepare_scene_base(
            scene_id="demo",
            background="background.png",
            is_background_video=False,
            scene_duration=2.5,
            plan=_plan(static_overlays=[overlay]),
        )

        assert result.scene_base_path == tmp_path / "composited.mp4"
        assert renderer.video_renderer.composited_calls[0][3] == [overlay]
        assert renderer.cache_manager.calls == []

    asyncio.run(_run())


def test_prepare_scene_base_uses_shared_cache_without_overlays(
    tmp_path: Path,
) -> None:
    async def _run() -> None:
        renderer = _renderer(tmp_path)

        result = await renderer._prepare_scene_base(
            scene_id="demo",
            background="background.png",
            is_background_video=False,
            scene_duration=2.5,
            plan=_plan(),
        )

        assert result.scene_base_path == tmp_path / "shared.mp4"
        call = renderer.cache_manager.calls[0]
        assert call["file_name"] == "scene_base_shared"
        assert call["key_data"]["version"] == "20260502_v1"

    asyncio.run(_run())


def test_prepare_scene_base_falls_back_for_video_background(
    tmp_path: Path,
    monkeypatch,
) -> None:
    async def _run() -> None:
        renderer = _renderer(tmp_path)
        renderer.video_renderer.fail_composited = True
        normalized = tmp_path / "normalized.mp4"
        normalized.write_bytes(b"normalized")
        calls = []

        async def fake_normalize(**kwargs):
            calls.append(kwargs)
            return normalized

        monkeypatch.setattr(base_module, "normalize_media", fake_normalize)

        result = await renderer._prepare_scene_base(
            scene_id="demo",
            background="background.mp4",
            is_background_video=True,
            scene_duration=2.5,
            plan=_plan(static_overlays=[{"path": "character.png"}]),
        )

        assert result.scene_base_path == tmp_path / "loop.mp4"
        assert result.normalized_background_path == normalized
        assert calls[0]["fit_mode"] == "stretch"
        assert len(renderer.video_renderer.loop_calls) == 1

    asyncio.run(_run())


def test_prepare_scene_base_only_normalizes_when_base_is_skipped(
    tmp_path: Path,
    monkeypatch,
) -> None:
    async def _run() -> None:
        renderer = _renderer(tmp_path)
        normalized = tmp_path / "normalized.mp4"
        normalized.write_bytes(b"normalized")

        async def fake_normalize(**_kwargs):
            return normalized

        monkeypatch.setattr(base_module, "normalize_media", fake_normalize)

        result = await renderer._prepare_scene_base(
            scene_id="demo",
            background="background.mp4",
            is_background_video=True,
            scene_duration=2.5,
            plan=_plan(should_generate_base=False),
        )

        assert result.scene_base_path is None
        assert result.normalized_background_path == normalized
        assert renderer.video_renderer.base_calls == []
        assert renderer.video_renderer.composited_calls == []

    asyncio.run(_run())


@pytest.mark.parametrize(("scene_copy", "expected"), [(False, True), (True, False)])
def test_prepare_scene_base_normalizes_common_insert_before_scene_copy_reset(
    tmp_path: Path,
    monkeypatch,
    scene_copy: bool,
    expected: bool,
) -> None:
    async def _run() -> None:
        renderer = _renderer(tmp_path)
        insert = tmp_path / "insert.mp4"
        normalized = tmp_path / "insert-normalized.mp4"
        insert.write_bytes(b"insert")
        normalized.write_bytes(b"normalized")
        calls = []

        async def fake_normalize(**kwargs):
            calls.append(kwargs)
            return normalized

        monkeypatch.setattr(base_module, "normalize_media", fake_normalize)

        result = await renderer._prepare_scene_base(
            scene_id="demo",
            background="background.png",
            is_background_video=False,
            scene_duration=2.5,
            plan=_plan(
                common_insert_video_path=insert,
                scene_copy=scene_copy,
            ),
        )

        assert calls[0]["input_path"] == insert
        assert (result.scene_level_insert_video == normalized) is expected

    asyncio.run(_run())
