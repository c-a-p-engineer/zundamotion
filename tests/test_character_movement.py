import pytest

from zundamotion.components.pipeline_phases.video_phase.character_tracker import CharacterTracker
from zundamotion.components.video.clip.movement import build_move_expressions
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


def test_character_tracker_fills_move_from_and_does_not_persist_move() -> None:
    tracker = CharacterTracker(1920, 1080)
    tracker.apply(
        [
            {
                "name": "copetan",
                "visible": True,
                "position": {"x": -480, "y": -32},
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
                "move": {"duration": 0.8, "easing": "ease_in_out"},
            }
        ]
    )
    moving = tracker.snapshot()[0]
    assert moving["move"]["from"] == {"x": -480, "y": -32}

    tracker.apply([{"name": "copetan", "visible": True}])
    assert "move" not in tracker.snapshot()[0]
