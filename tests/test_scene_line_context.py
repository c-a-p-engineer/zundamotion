from __future__ import annotations

from pathlib import Path

import pytest

from zundamotion.components.pipeline_phases.video_phase.scene_line_context import (
    SceneLineContextMixin,
)
from zundamotion.components.pipeline_phases.video_phase.scene_run_base_renderer import (
    RenderedRunBase,
)
from zundamotion.exceptions import PipelineError


class _Subject(SceneLineContextMixin):
    def __init__(self, *, line_data, scene=None) -> None:
        self.line_data_map = {"demo_3": line_data}
        self.scene = scene or {}
        self.video_extensions = [".mp4", ".mov"]

    def _resolve_background_layout(self, line_config):
        return {
            "fit": "contain",
            "fill_color": "black",
            "anchor": "middle_center",
            "position": {"x": "1", "y": "2"},
        }

    def _resolve_background_source(self, line_config, scene_background):
        return (line_config.get("background") or {}).get("path") or scene_background

    @staticmethod
    def _find_run_base(run_bases, line_index):
        for item in run_bases:
            if item.start_line <= line_index <= item.end_line:
                return item
        return None


def _line_data(*, line_type="talk", background=None):
    line_config = {}
    if background is not None:
        line_config["background"] = {"path": background}
    return {
        "type": line_type,
        "duration": 1.5,
        "pre_duration": 0.2,
        "post_duration": 0.3,
        "line_config": line_config,
        "text": "hello",
        "audio_path": Path("voice.wav"),
        "extra_audio_overlays": [{"src": "sfx.wav"}, "invalid"],
    }


def _build(subject, **overrides):
    values = {
        "scene_id": "demo",
        "line_index": 3,
        "line": {"id": "line-3"},
        "scene_background": "background.png",
        "scene_base_path": None,
        "normalized_background_path": None,
        "start_time_by_index": {3: 4.5},
        "run_bases": [],
        "image_layers_by_line": {3: [{"id": "layer"}]},
    }
    values.update(overrides)
    return subject._build_scene_line_context(**values)


def test_context_keeps_original_identity_and_line_inputs() -> None:
    subject = _Subject(line_data=_line_data())

    context = _build(subject)

    assert context.line_index == 3
    assert context.line_id == "demo_3"
    assert context.line_type == "talk"
    assert context.duration == 1.5
    assert context.pre_duration == 0.2
    assert context.post_duration == 0.3
    assert context.text == "hello"
    assert context.audio_path == Path("voice.wav")
    assert context.extra_audio_overlays == ({"src": "sfx.wav"},)
    assert context.image_layer_overlays == ({"id": "layer"},)
    assert context.visual_container == {"id": "line-3"}
    assert context.background_config["type"] == "image"
    assert context.background_config["start_time"] == 4.5


def test_scene_base_has_priority_over_run_base(tmp_path: Path) -> None:
    scene_base = tmp_path / "scene-base.mp4"
    scene_base.write_bytes(b"scene")
    run_path = tmp_path / "run.mp4"
    run_path.write_bytes(b"run")
    run_base = RenderedRunBase(
        start_line=3,
        end_line=4,
        path=run_path,
        character_keys=frozenset(),
        has_insert_image=False,
        offsets={3: 0.0, 4: 1.0},
    )
    subject = _Subject(line_data=_line_data())

    context = _build(subject, scene_base_path=scene_base, run_bases=[run_base])

    assert context.run_base is run_base
    assert context.background_config["path"] == str(scene_base)
    assert context.background_config["start_time"] == 4.5
    assert context.background_config["normalized"] is True


def test_run_base_uses_original_line_offset(tmp_path: Path) -> None:
    run_path = tmp_path / "run.mp4"
    run_path.write_bytes(b"run")
    run_base = RenderedRunBase(
        start_line=3,
        end_line=4,
        path=run_path,
        character_keys=frozenset({"key"}),
        has_insert_image=True,
        offsets={3: 0.75, 4: 1.25},
    )
    subject = _Subject(line_data=_line_data())

    context = _build(subject, run_bases=[run_base])

    assert context.background_config["path"] == str(run_path)
    assert context.background_config["start_time"] == 0.75
    assert context.background_config["pre_scaled"] is True


def test_normalized_video_is_used_only_for_scene_background(tmp_path: Path) -> None:
    normalized = tmp_path / "normalized.mp4"
    normalized.write_bytes(b"video")
    subject = _Subject(line_data=_line_data())

    context = _build(
        subject,
        scene_background="background.mp4",
        normalized_background_path=normalized,
    )

    assert context.background_is_video is True
    assert context.uses_scene_background is True
    assert context.background_config["path"] == str(normalized)
    assert context.background_config["normalized"] is True


def test_line_background_override_uses_raw_media_and_line_filter(tmp_path: Path) -> None:
    line_data = _line_data(background="line.mp4")
    line_data["line_config"]["video_filter"] = "grayscale"
    subject = _Subject(line_data=line_data, scene={"video_filter": "sepia"})

    context = _build(
        subject,
        scene_background="scene.mp4",
        normalized_background_path=tmp_path / "normalized.mp4",
    )

    assert context.uses_scene_background is False
    assert context.background_config["path"] == "line.mp4"
    assert context.background_config["video_filter"] == "grayscale"
    assert "normalized" not in context.background_config


def test_missing_background_is_rejected() -> None:
    subject = _Subject(line_data=_line_data())

    with pytest.raises(PipelineError, match="Background is not defined"):
        _build(subject, scene_background="")
