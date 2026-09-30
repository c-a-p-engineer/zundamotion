from __future__ import annotations

import pytest

from zundamotion.components.video.clip.camera import (
    append_camera_transform,
    build_camera_expressions,
    camera_requested,
)
from zundamotion.exceptions import ValidationError


def test_camera_requested_only_when_zoom_can_change_view() -> None:
    assert camera_requested(None) is False
    assert camera_requested(
        {"focus": {"x": 0.2, "y": 0.8}, "zoom": 1.0}
    ) is False
    assert camera_requested(
        {"focus": {"x": 0.5, "y": 0.5}, "zoom": 1.5}
    ) is True
    assert camera_requested(
        {
            "focus": {"x": 0.5, "y": 0.5},
            "zoom": 1.0,
            "move": {"from": {"zoom": 1.2}, "duration": 1.0},
        }
    ) is True


def test_static_camera_uses_normalized_focus_and_zoom() -> None:
    result = build_camera_expressions(
        {"focus": {"x": 0.7, "y": 0.3}, "zoom": 1.5},
        fps=30,
    )

    assert result.focus_x == "0.700000"
    assert result.focus_y == "0.300000"
    assert result.zoom == "1.500000"
    assert result.active is True


def test_camera_tracks_use_zoompan_output_clock_and_sparse_waypoints() -> None:
    result = build_camera_expressions(
        {
            "focus": {"x": 0.7, "y": 0.4},
            "zoom": 1.4,
            "move": {
                "from": {
                    "focus": {"x": 0.5},
                    "zoom": 1.0,
                },
                "start": 0.2,
                "duration": 1.0,
                "easing": "linear",
                "keyframes": [
                    {"at": 0.4, "zoom": 1.2, "easing": "ease_out"},
                    {"at": 0.7, "focus": {"x": 0.65}},
                ],
            },
        },
        fps=30,
    )

    assert "(on/30.000000)" in result.focus_x
    assert "(on/30.000000)" in result.zoom
    assert result.focus_y == "0.400000"
    assert "0.900000" in result.focus_x
    assert "0.600000" in result.zoom
    assert "1-(1-(" in result.zoom
    assert result.active is True


def test_focus_only_motion_at_zoom_one_is_observably_neutral() -> None:
    result = build_camera_expressions(
        {
            "focus": {"x": 0.8, "y": 0.5},
            "zoom": 1.0,
            "move": {
                "from": {"focus": {"x": 0.2}},
                "duration": 1.0,
            },
        },
        fps=30,
    )

    assert result.active is False
    assert result.focus_x != "0.800000"
    assert result.zoom == "1.000000"


def test_append_camera_transform_is_noop_for_neutral_camera() -> None:
    parts: list[str] = []
    output = append_camera_transform(
        camera_config={"focus": {"x": 0.2, "y": 0.8}, "zoom": 1.0},
        input_label="[world]",
        width=1920,
        height=1080,
        fps=30,
        parts=parts,
    )

    assert output == "[world]"
    assert parts == []


def test_append_camera_transform_builds_one_bounded_zoompan_stage() -> None:
    parts: list[str] = []
    output = append_camera_transform(
        camera_config={"focus": {"x": 0.75, "y": 0.25}, "zoom": 2.0},
        input_label="[world]",
        width=1280,
        height=720,
        fps=30,
        parts=parts,
    )

    assert output == "[camera_view]"
    assert len(parts) == 1
    assert parts[0].startswith("[world]zoompan=")
    assert "x='(iw-iw/zoom)*(0.750000)'" in parts[0]
    assert "y='(ih-ih/zoom)*(0.250000)'" in parts[0]
    assert "d=1:s=1280x720:fps=30.000[camera_view]" in parts[0]


@pytest.mark.parametrize(
    "camera",
    [
        {"focus": {"x": -0.1, "y": 0.5}, "zoom": 1.0},
        {"focus": {"x": 0.5, "y": 1.1}, "zoom": 1.0},
        {"focus": {"x": 0.5, "y": 0.5}, "zoom": 0.9},
        {"focus": {"x": 0.5, "y": 0.5}, "zoom": 4.1},
    ],
)
def test_camera_expression_rejects_out_of_domain_values(camera) -> None:
    with pytest.raises(ValidationError):
        build_camera_expressions(camera, fps=30)


def test_camera_keyframe_requires_matching_start_value() -> None:
    with pytest.raises(ValidationError, match="move.from.focus.x"):
        build_camera_expressions(
            {
                "focus": {"x": 0.8, "y": 0.5},
                "zoom": 1.2,
                "move": {
                    "from": {"zoom": 1.0},
                    "duration": 1.0,
                    "keyframes": [
                        {"at": 0.5, "focus": {"x": 0.7}},
                    ],
                },
            },
            fps=30,
        )
