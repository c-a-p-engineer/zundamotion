import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from zundamotion.exceptions import PipelineError
from zundamotion.components.pipeline_phases.video_phase.scene_standard_context import (
    SceneStandardContextMixin,
)


class _Harness(SceneStandardContextMixin):
    def __init__(self) -> None:
        self.config = {
            "system": {
                "generate_no_sub_video": True,
                "cache_scene_base_video": False,
            }
        }
        self.video_extensions = {".mp4"}
        self.calls = []
        self.line_data_map = {}

    @staticmethod
    def _scene_base_cache_data(scene_hash_data):
        return {**scene_hash_data, "layer": "base"}

    @staticmethod
    def _scene_subtitle_cache_data(scene_hash_data, base_hash_data):
        return {**scene_hash_data, "layer": "sub"}

    @staticmethod
    def _build_scene_timing_plan(**kwargs):
        return SimpleNamespace(
            lines=[],
            scene_duration=1.0,
            start_time_by_idx={},
            badge_line_markers={},
            subtitle_entries=[],
            subtitle_timing_key="timing",
            component_keys={"base": "key"},
        )

    def _record_scene_cache_event(self, **kwargs):
        self.calls.append(("cache_event", kwargs))

    def _can_use_simple_scene_fast_path(self, **kwargs):
        self.calls.append(("can_fast", kwargs))
        return True, "eligible"

    async def _render_simple_scene_fast(self, **kwargs):
        self.calls.append(("fast", kwargs))
        return Path("fast.mp4")

    def _complete_scene_render(self, path):
        self.calls.append(("complete", path))


def test_prepare_standard_context_resolves_flags_background_and_timing() -> None:
    harness = _Harness()

    context = harness._prepare_standard_scene_context(
        scene={"id": "scene-a", "bg": "background.mp4", "lines": []},
        scene_copy=True,
        background_default=None,
        scene_hash_data={"key": "scene"},
    )

    assert context.scene_id == "scene-a"
    assert context.scene_copy is True
    assert context.background == "background.mp4"
    assert context.is_background_video is True
    assert context.generate_no_sub_video is True
    assert context.cache_scene_base_video is False
    assert context.scene_base_hash_data["layer"] == "base"
    assert context.scene_sub_hash_data["layer"] == "sub"


def test_prepare_standard_context_rejects_missing_background() -> None:
    harness = _Harness()

    with pytest.raises(PipelineError, match="does not define a background"):
        harness._prepare_standard_scene_context(
            scene={"id": "scene-a", "lines": []},
            scene_copy=False,
            background_default=None,
            scene_hash_data={},
        )


def test_disabled_base_cache_records_event_without_lookup() -> None:
    harness = _Harness()
    context = harness._prepare_standard_scene_context(
        scene={"id": "scene-a", "bg": "background.png", "lines": []},
        scene_copy=False,
        background_default=None,
        scene_hash_data={},
    )

    result = asyncio.run(harness._resolve_standard_scene_cache(context))

    assert result is None
    assert harness.calls[0][0] == "cache_event"
    assert harness.calls[0][1]["status"] == "DISABLED"


def test_fast_path_success_completes_and_returns_single_result() -> None:
    harness = _Harness()
    context = harness._prepare_standard_scene_context(
        scene={"id": "scene-a", "bg": "background.png", "lines": []},
        scene_copy=False,
        background_default=None,
        scene_hash_data={},
    )

    result = asyncio.run(harness._try_standard_scene_fast_path(context))

    assert result == [Path("fast.mp4")]
    assert harness.calls[-1] == ("complete", None)
