from pathlib import Path

import pytest

from zundamotion.components.pipeline_phases.video_phase.scene_renderer import (
    SceneRenderer,
)


def _renderer(*, config=None, character_maps=None) -> SceneRenderer:
    renderer = object.__new__(SceneRenderer)
    renderer.config = config or {"video": {"scene_base_min_lines": 6}}
    maps = character_maps or {}
    renderer._norm_char_entries = lambda line: maps.get(line["id"], {})
    renderer._resolve_background_layout = lambda _config: {
        "fit": "stretch",
        "fill_color": "black",
        "anchor": "middle_center",
        "position": {"x": "0", "y": "0"},
    }
    return renderer


def test_scene_base_plan_extracts_common_characters_and_insert_image(
    tmp_path: Path,
) -> None:
    character_path = tmp_path / "character.png"
    insert_path = tmp_path / "insert.png"
    character_path.write_bytes(b"character")
    insert_path.write_bytes(b"insert")
    character_key = ("hero", "default")
    common_character = {"path": str(character_path), "scale": 1.0}
    renderer = _renderer(
        character_maps={
            "line-1": {character_key: common_character, ("only-1",): {"path": str(character_path)}},
            "line-2": {character_key: common_character},
        }
    )
    insert = {
        "path": str(insert_path),
        "scale": 0.75,
        "anchor": "top_left",
        "position": {"x": "10", "y": "20"},
    }
    scene = {
        "lines": [
            {"id": "line-1", "insert": insert},
            {"id": "line-2", "insert": insert},
        ]
    }

    plan = renderer._build_scene_base_plan(
        scene=scene,
        scene_copy=False,
        is_background_video=False,
        has_line_background_override=False,
    )

    assert plan.static_character_keys == {character_key}
    assert plan.static_overlays == [
        common_character,
        {
            "path": str(insert_path),
            "scale": 0.75,
            "anchor": "top_left",
            "position": {"x": "10", "y": "20"},
        },
    ]
    assert plan.static_insert_in_base is True
    assert plan.common_insert_video_path is None
    assert plan.should_generate_base is True
    assert plan.detection_error is None


def test_scene_base_plan_classifies_common_video_before_scene_copy_reset(
    tmp_path: Path,
) -> None:
    video_path = tmp_path / "insert.mp4"
    video_path.write_bytes(b"video")
    renderer = _renderer()
    insert = {"path": str(video_path)}
    scene = {
        "lines": [
            {"id": "line-1", "insert": insert},
            {"id": "line-2", "insert": insert},
        ]
    }

    plan = renderer._build_scene_base_plan(
        scene=scene,
        scene_copy=True,
        is_background_video=False,
        has_line_background_override=False,
    )

    assert plan.static_overlays == []
    assert plan.static_character_keys == set()
    assert plan.static_insert_in_base is False
    assert plan.common_insert_video_path == video_path
    assert plan.scene_copy is True
    assert plan.should_generate_base is True


@pytest.mark.parametrize(
    ("is_video", "line_count", "minimum", "override", "expected"),
    [
        (True, 5, 6, False, False),
        (True, 6, 6, False, True),
        (False, 1, 6, False, False),
        (False, 2, 6, False, True),
        (False, 2, 6, True, False),
    ],
)
def test_scene_base_plan_preserves_background_thresholds(
    is_video: bool,
    line_count: int,
    minimum: int,
    override: bool,
    expected: bool,
) -> None:
    renderer = _renderer(config={"video": {"scene_base_min_lines": minimum}})
    scene = {"lines": [{"id": f"line-{index}"} for index in range(line_count)]}

    plan = renderer._build_scene_base_plan(
        scene=scene,
        scene_copy=False,
        is_background_video=is_video,
        has_line_background_override=override,
    )

    assert plan.should_generate_base is expected
    assert plan.total_lines == line_count
    assert plan.minimum_lines == minimum


def test_scene_base_plan_keeps_invalid_minimum_failure() -> None:
    renderer = _renderer(config={"video": {"scene_base_min_lines": "invalid"}})

    with pytest.raises(ValueError):
        renderer._build_scene_base_plan(
            scene={"lines": []},
            scene_copy=False,
            is_background_video=True,
            has_line_background_override=False,
        )


def test_scene_base_plan_reports_static_detection_failure(tmp_path: Path) -> None:
    renderer = _renderer(character_maps={"line-1": {("broken",): {}}, "line-2": {("broken",): {}}})

    plan = renderer._build_scene_base_plan(
        scene={"lines": [{"id": "line-1"}, {"id": "line-2"}]},
        scene_copy=False,
        is_background_video=False,
        has_line_background_override=False,
    )

    assert plan.static_overlays == []
    assert plan.static_character_keys == set()
    assert plan.detection_error is not None
    assert plan.should_generate_base is True
