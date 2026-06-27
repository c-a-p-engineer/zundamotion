import pytest

from zundamotion.components.pipeline_phases.video_phase.character_tracker import CharacterTracker
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
