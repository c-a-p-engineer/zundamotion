import asyncio
import inspect
from pathlib import Path
from types import SimpleNamespace

from zundamotion.components.pipeline_phases.video_phase.scene_standard_renderer import (
    SceneStandardRendererMixin,
)


class _Harness(SceneStandardRendererMixin):
    def __init__(self) -> None:
        self.calls = []
        self.cached_result = None
        self.fast_result = None
        self.assembly = object()
        self.context = SimpleNamespace(
            scene_id="scene-a",
            scene={"id": "scene-a"},
            scene_hash_data={"key": "scene"},
            cache_scene_base_video=True,
            generate_no_sub_video=False,
            scene_base_hash_data={"key": "base"},
            scene_sub_hash_data={"key": "sub"},
            timing=SimpleNamespace(
                badge_line_markers={"line": 0.0},
                subtitle_entries=[{"text": "hello"}],
                subtitle_timing_key="timing",
            ),
        )
        self.layers = SimpleNamespace(scene_base_path=Path("scene-base.mp4"))

    def _prepare_standard_scene_context(self, **kwargs):
        self.calls.append("prepare")
        return self.context

    async def _resolve_standard_scene_cache(self, context):
        self.calls.append("cache")
        return self.cached_result

    async def _try_standard_scene_fast_path(self, context):
        self.calls.append("fast")
        return self.fast_result

    async def _precache_standard_scene_assets(self, context):
        self.calls.append("precache")

    async def _prepare_standard_scene_layers(self, context):
        self.calls.append("layers")
        return self.layers

    async def _render_standard_scene_lines(self, context, layers):
        self.calls.append("lines")
        return [Path("line.mp4")]

    async def _maybe_retune_line_workers(self):
        self.calls.append("retune")

    async def _assemble_scene_media(self, **kwargs):
        self.calls.append("assembly")
        return self.assembly

    def _store_scene_result_cache(self, **kwargs):
        self.calls.append("store")
        return Path("scene-final.mp4")

    def _complete_scene_render(self, scene_base_path):
        self.calls.append(("complete", scene_base_path))


def _render(harness: _Harness):
    return asyncio.run(
        harness._render_scene_internal(
            {"id": "scene-a"},
            False,
            "background.png",
            {"key": "scene"},
        )
    )


def test_standard_orchestration_runs_named_stages_in_order() -> None:
    harness = _Harness()

    result = _render(harness)

    assert result == [Path("scene-final.mp4")]
    assert harness.calls == [
        "prepare",
        "cache",
        "fast",
        "precache",
        "layers",
        "lines",
        "retune",
        "assembly",
        "store",
        ("complete", Path("scene-base.mp4")),
    ]


def test_scene_cache_hit_short_circuits_later_stages() -> None:
    harness = _Harness()
    harness.cached_result = [Path("cached.mp4")]

    result = _render(harness)

    assert result == [Path("cached.mp4")]
    assert harness.calls == ["prepare", "cache"]


def test_fast_path_short_circuits_render_pipeline() -> None:
    harness = _Harness()
    harness.fast_result = [Path("fast.mp4")]

    result = _render(harness)

    assert result == [Path("fast.mp4")]
    assert harness.calls == ["prepare", "cache", "fast"]


def test_empty_assembly_still_completes_scene() -> None:
    harness = _Harness()
    harness.assembly = None

    result = _render(harness)

    assert result == []
    assert "store" not in harness.calls
    assert harness.calls[-1] == ("complete", Path("scene-base.mp4"))


def test_render_scene_internal_stays_within_orchestration_budget() -> None:
    source_lines = inspect.getsource(
        SceneStandardRendererMixin._render_scene_internal
    ).splitlines()

    assert len(source_lines) <= 80
