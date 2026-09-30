from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from zundamotion.components.video import clip_pipeline
from zundamotion.components.video.clip_pipeline import (
    ClipRenderRequest,
    run_clip_pipeline,
)
from zundamotion.components.video.clip_video_graph import ClipVideoGraph


class _Renderer:
    def __init__(self, root: Path) -> None:
        self.temp_dir = root
        self.video_params = SimpleNamespace(width=320, height=180, fps=30)


def test_clip_pipeline_expands_motion_preset_before_inputs_and_graph(
    monkeypatch,
    tmp_path: Path,
) -> None:
    authoring_character = {
        "name": "hero",
        "visible": True,
        "scale": 1.0,
        "position": {"x": 0, "y": -32},
        "move": {
            "preset": "pop",
            "duration": 0.5,
            "intensity": 1.0,
        },
    }
    observed: dict[str, object] = {}

    async def _collect(**kwargs):
        observed["collect_characters"] = kwargs["characters_config"]
        return SimpleNamespace(cmd=[])

    def _policy(**_kwargs):
        return SimpleNamespace()

    async def _graph(_renderer, _inputs, request, _policy_value):
        observed["graph_characters"] = request.characters_config
        return ClipVideoGraph([], None)

    async def _audio(**_kwargs):
        return None

    def _command(**_kwargs):
        return []

    async def _execute(**kwargs):
        return kwargs["output_path"]

    monkeypatch.setattr(clip_pipeline, "collect_clip_inputs", _collect)
    monkeypatch.setattr(clip_pipeline, "resolve_clip_filter_policy", _policy)
    monkeypatch.setattr(clip_pipeline, "build_clip_video_graph", _graph)
    monkeypatch.setattr(clip_pipeline, "append_clip_audio_graph", _audio)
    monkeypatch.setattr(clip_pipeline, "build_clip_command", _command)
    monkeypatch.setattr(clip_pipeline, "execute_clip_command", _execute)

    request = ClipRenderRequest(
        audio_path=Path("voice.wav"),
        duration=1.0,
        background_config={"type": "image", "path": "bg.png"},
        characters_config=[authoring_character],
        output_filename="preset",
    )

    result = asyncio.run(run_clip_pipeline(_Renderer(tmp_path), request))

    assert result == tmp_path / "preset.mp4"
    collect_character = observed["collect_characters"][0]
    graph_character = observed["graph_characters"][0]

    assert collect_character == graph_character
    assert collect_character["move"]["from"]["scale"] == 0.82
    assert collect_character["move"]["keyframes"][0]["scale"] == 1.08
    assert "preset" not in collect_character["move"]

    # The caller-owned authoring config remains untouched.
    assert authoring_character["move"] == {
        "preset": "pop",
        "duration": 0.5,
        "intensity": 1.0,
    }


def test_clip_pipeline_leaves_non_preset_character_config_unchanged(
    monkeypatch,
    tmp_path: Path,
) -> None:
    character = {
        "name": "hero",
        "visible": True,
        "position": {"x": 0, "y": -32},
        "scale": 1.0,
        "move": {
            "from": {"x": -100, "y": -32},
            "duration": 0.5,
        },
    }
    observed = {}

    async def _collect(**kwargs):
        observed["characters"] = kwargs["characters_config"]
        return SimpleNamespace(cmd=[])

    monkeypatch.setattr(clip_pipeline, "collect_clip_inputs", _collect)
    monkeypatch.setattr(
        clip_pipeline,
        "resolve_clip_filter_policy",
        lambda **_kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(
        clip_pipeline,
        "build_clip_video_graph",
        lambda *_args, **_kwargs: None,
    )

    async def _graph(*_args, **_kwargs):
        return ClipVideoGraph([], None)

    monkeypatch.setattr(clip_pipeline, "build_clip_video_graph", _graph)
    monkeypatch.setattr(
        clip_pipeline,
        "append_clip_audio_graph",
        lambda **_kwargs: _async_value(None),
    )
    monkeypatch.setattr(clip_pipeline, "build_clip_command", lambda **_kwargs: [])

    async def _execute(**kwargs):
        return kwargs["output_path"]

    monkeypatch.setattr(clip_pipeline, "execute_clip_command", _execute)

    request = ClipRenderRequest(
        audio_path=Path("voice.wav"),
        duration=1.0,
        background_config={"type": "image", "path": "bg.png"},
        characters_config=[character],
        output_filename="legacy",
    )

    asyncio.run(run_clip_pipeline(_Renderer(tmp_path), request))

    assert observed["characters"][0] is character


async def _async_value(value):
    return value
