from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from zundamotion.components.video import clip_pipeline
from zundamotion.components.video import clip_video_graph
from zundamotion.components.video.clip_pipeline import (
    ClipRenderRequest,
    run_clip_pipeline,
)
from zundamotion.components.video.clip_video_graph import (
    ClipVideoGraph,
    ClipVideoGraphRequest,
    build_clip_video_graph,
)


class _Renderer:
    def __init__(self, root: Path) -> None:
        self.temp_dir = root
        self.video_params = SimpleNamespace(width=320, height=180, fps=30)


def _request(camera_config):
    return ClipRenderRequest(
        audio_path=Path("voice.wav"),
        duration=1.0,
        background_config={"type": "image", "path": "bg.png"},
        characters_config=[],
        output_filename="camera",
        camera_config=camera_config,
    )


@pytest.mark.parametrize(
    ("camera_config", "expected_force_cpu"),
    [
        (
            {"focus": {"x": 0.6, "y": 0.5}, "zoom": 1.2},
            True,
        ),
        (
            {"focus": {"x": 0.8, "y": 0.2}, "zoom": 1.0},
            False,
        ),
        (None, False),
    ],
)
def test_camera_only_forces_cpu_when_view_transform_is_active(
    monkeypatch,
    tmp_path: Path,
    camera_config,
    expected_force_cpu: bool,
) -> None:
    observed: dict[str, object] = {}

    async def _collect(**_kwargs):
        return SimpleNamespace(cmd=[])

    def _policy(**kwargs):
        observed["policy_force_cpu"] = kwargs["force_cpu"]
        return SimpleNamespace()

    async def _graph(_renderer, _inputs, request, _policy_value):
        observed["graph_force_cpu"] = request.force_cpu
        return ClipVideoGraph([], None)

    async def _audio(**_kwargs):
        return None

    def _command(**_kwargs):
        return []

    async def _execute(**kwargs):
        observed["execute_force_cpu"] = kwargs["force_cpu"]
        return kwargs["output_path"]

    monkeypatch.setattr(clip_pipeline, "collect_clip_inputs", _collect)
    monkeypatch.setattr(clip_pipeline, "resolve_clip_filter_policy", _policy)
    monkeypatch.setattr(clip_pipeline, "build_clip_video_graph", _graph)
    monkeypatch.setattr(clip_pipeline, "append_clip_audio_graph", _audio)
    monkeypatch.setattr(clip_pipeline, "build_clip_command", _command)
    monkeypatch.setattr(clip_pipeline, "execute_clip_command", _execute)

    result = asyncio.run(
        run_clip_pipeline(
            _Renderer(tmp_path),
            _request(camera_config),
        )
    )

    assert result == tmp_path / "camera.mp4"
    assert observed == {
        "policy_force_cpu": expected_force_cpu,
        "graph_force_cpu": expected_force_cpu,
        "execute_force_cpu": expected_force_cpu,
    }


def test_camera_stage_is_after_world_composition_and_before_subtitle(
    monkeypatch,
) -> None:
    order: list[str] = []

    def _background(**_kwargs):
        return "[bg]", None

    def _insert(**_kwargs):
        order.append("insert")

    def _images(**_kwargs):
        order.append("images")

    def _characters(**_kwargs):
        order.append("characters")
        return {}

    async def _faces(*_args, **_kwargs):
        order.append("faces")

    def _world(**_kwargs):
        order.append("world")
        return "[world]"

    def _camera(**_kwargs):
        order.append("camera")
        return "[camera]"

    async def _subtitle(**_kwargs):
        order.append("subtitle")
        return "[subtitle]", None, None

    def _screen(*_args, **_kwargs):
        order.append("screen")
        return "[screen]"

    def _final(*_args, **_kwargs):
        order.append("final")

    monkeypatch.setattr(clip_video_graph, "build_background_graph", _background)
    monkeypatch.setattr(clip_video_graph, "append_insert_overlay", _insert)
    monkeypatch.setattr(clip_video_graph, "append_image_layer_overlays", _images)
    monkeypatch.setattr(clip_video_graph, "build_character_overlays", _characters)
    monkeypatch.setattr(clip_video_graph, "_append_faces", _faces)
    monkeypatch.setattr(clip_video_graph, "append_overlay_chain", _world)
    monkeypatch.setattr(clip_video_graph, "append_camera_transform", _camera)
    monkeypatch.setattr(clip_video_graph, "append_subtitle_overlay", _subtitle)
    monkeypatch.setattr(clip_video_graph, "_append_screen_effects", _screen)
    monkeypatch.setattr(clip_video_graph, "_append_final_video", _final)

    renderer = SimpleNamespace(
        video_params=SimpleNamespace(width=320, height=180, fps=30)
    )
    request = ClipVideoGraphRequest(
        duration=1.0,
        background_config={},
        characters_config=[],
        subtitle_text="subtitle",
        subtitle_line_config={},
        insert_config=None,
        screen_effects=[],
        camera_config={"focus": {"x": 0.6, "y": 0.5}, "zoom": 1.2},
        subtitle_png_path=None,
        face_anim=None,
        audio_delay=0.0,
        force_cpu=True,
    )
    policy = SimpleNamespace(
        use_cuda_filters=False,
        use_opencl_overlays=False,
    )

    asyncio.run(
        build_clip_video_graph(
            renderer,
            SimpleNamespace(
                character_indices={},
                char_effective_scale={},
                char_metadata={},
            ),
            request,
            policy,
        )
    )

    assert order == [
        "insert",
        "images",
        "characters",
        "faces",
        "world",
        "camera",
        "subtitle",
        "screen",
        "final",
    ]
