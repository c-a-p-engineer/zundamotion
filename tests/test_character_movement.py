import pytest

from zundamotion.components.pipeline_phases.video_phase.character_tracker import CharacterTracker
from zundamotion.components.video.clip.motion_track import (
    build_motion_track,
    evaluate_motion_track,
)
from zundamotion.components.video.clip.movement import (
    build_dynamic_scale_filter,
    build_move_expressions,
    build_scale_expression,
)
from zundamotion.exceptions import ValidationError


def test_build_move_expressions_uses_explicit_from_position() -> None:
    x_expr, y_expr, dynamic = build_move_expressions(
        move_config={
            "from": {"x": -480, "y": -32},
            "duration": 0.6,
            "easing": "ease_out",
        },
        anchor="bottom_center",
        from_position=None,
        to_position={"x": 240, "y": -32},
        to_x_expr="(W-w)/2+240",
        to_y_expr="H-h-32",
    )

    assert dynamic is True
    assert "(W-w)/2-480" in x_expr
    assert "(W-w)/2+240" in x_expr
    assert "1-(1-(" in x_expr
    assert "H-h-32" in y_expr


def test_build_move_expressions_requires_from_without_previous_position() -> None:
    with pytest.raises(ValidationError, match="move.from is required"):
        build_move_expressions(
            move_config={"duration": 0.3},
            anchor="bottom_center",
            from_position=None,
            to_position={"x": 0, "y": 0},
            to_x_expr="(W-w)/2",
            to_y_expr="H-h",
        )


def test_build_scale_expression_without_position_movement() -> None:
    x_expr, y_expr, position_dynamic = build_move_expressions(
        move_config={
            "from": {"scale": 0.5},
            "duration": 0.6,
            "easing": "ease_out",
        },
        anchor="bottom_center",
        from_position=None,
        to_position={"x": 120, "y": -32},
        to_x_expr="(W-w)/2+120",
        to_y_expr="H-h-32",
    )
    scale_expr, scale_dynamic = build_scale_expression(
        move_config={
            "from": {"scale": 0.5},
            "duration": 0.6,
            "easing": "ease_out",
        },
        to_scale=1.0,
    )

    assert position_dynamic is False
    assert x_expr == "(W-w)/2+120"
    assert y_expr == "H-h-32"
    assert scale_dynamic is True
    assert "0.500000" in scale_expr
    assert "1.000000" in scale_expr
    assert "1-(1-(" in scale_expr


def test_build_move_and_scale_expressions_share_timing() -> None:
    move = {
        "from": {"x": -480, "y": -32, "scale": 0.6},
        "duration": 0.8,
        "start": 0.2,
        "easing": "ease_in_out",
    }
    x_expr, _y_expr, position_dynamic = build_move_expressions(
        move_config=move,
        anchor="bottom_center",
        from_position=None,
        to_position={"x": 240, "y": -32},
        to_x_expr="(W-w)/2+240",
        to_y_expr="H-h-32",
    )
    scale_expr, scale_dynamic = build_scale_expression(
        move_config=move,
        to_scale=1.1,
    )

    assert position_dynamic is True
    assert scale_dynamic is True
    assert "lt(t,0.200000)" in x_expr
    assert "lt(t,0.200000)" in scale_expr
    assert "1.100000" in scale_expr


def test_dynamic_scale_filter_uses_fixed_anchor_aligned_canvas() -> None:
    move = {"from": {"scale": 0.5}, "duration": 0.8}
    scale_expr, _dynamic = build_scale_expression(
        move_config=move,
        to_scale=1.0,
    )

    filter_expr = build_dynamic_scale_filter(
        scale_expr=scale_expr,
        move_config=move,
        to_scale=1.0,
        source_width=800,
        source_height=1200,
        anchor="bottom_center",
        scale_flags="bicubic",
    )

    assert "pad=w=800:h=1200" in filter_expr
    assert "x='(ow-iw)/2'" in filter_expr
    assert "y='oh-ih'" in filter_expr
    assert "color=black@0:eval=frame" in filter_expr


def test_character_tracker_fills_move_from_and_does_not_persist_move() -> None:
    tracker = CharacterTracker(1920, 1080)
    tracker.apply(
        [
            {
                "name": "copetan",
                "visible": True,
                "position": {"x": -480, "y": -32},
                "scale": 0.7,
            }
        ]
    )
    assert tracker.snapshot()[0]["position"] == {"x": -480, "y": -32}

    tracker.apply(
        [
            {
                "name": "copetan",
                "visible": True,
                "position": {"x": 240, "y": -32},
                "scale": 1.0,
                "move": {"duration": 0.8, "easing": "ease_in_out"},
            }
        ]
    )
    moving = tracker.snapshot()[0]
    assert moving["move"]["from"] == {"x": -480, "y": -32, "scale": 0.7}

    tracker.apply([{"name": "copetan", "visible": True}])
    assert "move" not in tracker.snapshot()[0]



def test_motion_track_sparse_waypoints_and_segment_easing() -> None:
    x_track = build_motion_track(
        property_name="x",
        start_time=0.2,
        duration=1.0,
        start_value=-400,
        final_value=200,
        waypoints=[
            {"at": 0.25, "x": -200, "easing": "ease_out"},
            {"at": 0.65, "y": -80, "easing": "ease_in"},
        ],
        default_easing="linear",
    )
    y_track = build_motion_track(
        property_name="y",
        start_time=0.2,
        duration=1.0,
        start_value=-32,
        final_value=-32,
        waypoints=[
            {"at": 0.25, "x": -200, "easing": "ease_out"},
            {"at": 0.65, "y": -80, "easing": "ease_in"},
        ],
        default_easing="linear",
    )

    assert [frame.time for frame in x_track.keyframes] == pytest.approx(
        [0.2, 0.45, 1.2]
    )
    assert [frame.value for frame in x_track.keyframes] == pytest.approx(
        [-400, -200, 200]
    )
    assert x_track.keyframes[1].easing_to_here == "ease_out"
    assert x_track.keyframes[2].easing_to_here == "linear"

    assert [frame.time for frame in y_track.keyframes] == pytest.approx(
        [0.2, 0.85, 1.2]
    )
    assert [frame.value for frame in y_track.keyframes] == pytest.approx(
        [-32, -80, -32]
    )
    assert y_track.keyframes[1].easing_to_here == "ease_in"


def test_motion_track_evaluator_hits_boundaries_without_jump() -> None:
    track = build_motion_track(
        property_name="x",
        start_time=0.0,
        duration=1.0,
        start_value=0,
        final_value=100,
        waypoints=[
            {"at": 0.5, "x": 80, "easing": "ease_out"},
        ],
        default_easing="linear",
    )

    assert evaluate_motion_track(track, -0.1) == pytest.approx(0)
    assert evaluate_motion_track(track, 0.25) == pytest.approx(60)
    assert evaluate_motion_track(track, 0.5) == pytest.approx(80)
    assert evaluate_motion_track(track, 0.75) == pytest.approx(90)
    assert evaluate_motion_track(track, 1.0) == pytest.approx(100)
    assert evaluate_motion_track(track, 1.2) == pytest.approx(100)


def test_build_multi_keyframe_position_expression_uses_each_waypoint() -> None:
    x_expr, y_expr, dynamic = build_move_expressions(
        move_config={
            "from": {"x": -400, "y": -32},
            "duration": 1.0,
            "start": 0.2,
            "easing": "linear",
            "keyframes": [
                {"at": 0.25, "x": -200, "easing": "ease_out"},
                {"at": 0.65, "x": 40, "y": -80, "easing": "ease_in"},
            ],
        },
        anchor="bottom_center",
        from_position=None,
        to_position={"x": 200, "y": -32},
        to_x_expr="(W-w)/2+200",
        to_y_expr="H-h-32",
    )

    assert dynamic is True
    assert "0.450000" in x_expr
    assert "0.850000" in x_expr
    assert "(W-w)/2-200" in x_expr
    assert "(W-w)/2+40" in x_expr
    assert "H-h-80" in y_expr


def test_dynamic_scale_filter_sizes_canvas_for_largest_intermediate_keyframe() -> None:
    move = {
        "from": {"scale": 0.6},
        "duration": 1.0,
        "keyframes": [
            {"at": 0.4, "scale": 1.4, "easing": "ease_out"},
            {"at": 0.7, "scale": 0.8},
        ],
    }
    scale_expr, dynamic = build_scale_expression(
        move_config=move,
        to_scale=1.0,
    )
    filter_expr = build_dynamic_scale_filter(
        scale_expr=scale_expr,
        move_config=move,
        to_scale=1.0,
        source_width=800,
        source_height=1200,
        anchor="bottom_center",
        scale_flags="bicubic",
    )

    assert dynamic is True
    assert "1.400000" in scale_expr
    assert "pad=w=1120:h=1680" in filter_expr


def test_character_tracker_uses_previous_scale_for_keyframe_loop() -> None:
    tracker = CharacterTracker(1920, 1080)
    tracker.apply(
        [
            {
                "name": "copetan",
                "visible": True,
                "position": {"x": 0, "y": -32},
                "scale": 1.0,
            }
        ]
    )
    tracker.snapshot()

    tracker.apply(
        [
            {
                "name": "copetan",
                "visible": True,
                "position": {"x": 0, "y": -32},
                "scale": 1.0,
                "move": {
                    "duration": 1.0,
                    "keyframes": [{"at": 0.5, "scale": 1.3}],
                },
            }
        ]
    )
    moving = tracker.snapshot()[0]

    assert moving["move"]["from"]["scale"] == pytest.approx(1.0)
    assert moving["scale"] == pytest.approx(1.0)
