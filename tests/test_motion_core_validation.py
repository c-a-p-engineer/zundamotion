from __future__ import annotations

import math

import pytest

from zundamotion.components.config.validate_script import (
    _validate_character_move,
    _validate_character_opacity,
    _validate_character_rotate,
)
from zundamotion.exceptions import ValidationError


def test_multi_keyframe_validation_accepts_sparse_numeric_waypoints() -> None:
    _validate_character_move(
        {
            "from": {"x": -400, "y": -32, "scale": 0.6},
            "start": 0.2,
            "duration": 1.0,
            "easing": "ease_in_out",
            "keyframes": [
                {"at": 0.25, "x": -180, "easing": "ease_out"},
                {"at": 0.65, "y": -20, "scale": 0.9},
            ],
        },
        "character.move",
    )


def test_empty_keyframe_list_keeps_legacy_string_compatibility() -> None:
    _validate_character_move(
        {
            "from": {"x": "(W-w)/2", "y": 0},
            "duration": 0.0,
            "keyframes": [],
        },
        "character.move",
    )


@pytest.mark.parametrize(
    ("keyframes", "message"),
    [
        (
            [{"at": 0.4, "x": 10}, {"at": 0.4, "x": 20}],
            "strictly increasing",
        ),
        (
            [{"at": 0.6, "x": 10}, {"at": 0.4, "x": 20}],
            "strictly increasing",
        ),
        ([{"at": 0.0, "x": 10}], "0 < at < move.duration"),
        ([{"at": 1.0, "x": 10}], "0 < at < move.duration"),
        ([{"at": 1.2, "x": 10}], "0 < at < move.duration"),
        (
            [{"at": 0.4, "easing": "ease_out"}],
            "at least one of x, y, scale, rotate, or opacity",
        ),
        ([{"at": 0.4, "x": "10"}], "x must be a finite number"),
        ([{"at": 0.4, "scale": 0}], "scale must be greater than 0"),
        ([{"at": 0.4, "x": 10, "easing": "spring"}], "easing must be one of"),
    ],
)
def test_multi_keyframe_validation_rejects_invalid_cases(
    keyframes: list[dict],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        _validate_character_move(
            {
                "from": {"x": 0, "y": 0, "scale": 1.0},
                "duration": 1.0,
                "keyframes": keyframes,
            },
            "character.move",
        )


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_multi_keyframe_validation_rejects_non_finite_values(value: float) -> None:
    with pytest.raises(ValidationError, match="finite number"):
        _validate_character_move(
            {
                "from": {"x": 0, "y": 0},
                "duration": 1.0,
                "keyframes": [{"at": 0.5, "x": value}],
            },
            "character.move",
        )


def test_multi_keyframe_validation_rejects_non_numeric_legacy_from_expression() -> None:
    with pytest.raises(ValidationError, match="from.x must be a finite number"):
        _validate_character_move(
            {
                "from": {"x": "(W-w)/2", "y": 0},
                "duration": 1.0,
                "keyframes": [{"at": 0.5, "x": 10}],
            },
            "character.move",
        )


def test_multi_keyframe_validation_requires_positive_duration() -> None:
    with pytest.raises(ValidationError, match="duration must be a finite number greater than 0"):
        _validate_character_move(
            {
                "from": {"x": 0, "y": 0},
                "duration": 0.0,
                "keyframes": [{"at": 0.2, "x": 10}],
            },
            "character.move",
        )



def test_rotate_waypoints_are_valid_motion_properties() -> None:
    move = {
        "from": {"rotate": -10},
        "duration": 1.0,
        "keyframes": [
            {"at": 0.3, "rotate": 15, "easing": "ease_out"},
            {"at": 0.7, "x": 20},
        ],
    }

    _validate_character_move(move, "character.move")
    _validate_character_rotate(
        {"rotate": 0, "move": move},
        "character",
    )


def test_rotate_animation_requires_explicit_final_value() -> None:
    with pytest.raises(ValidationError, match="rotate is required"):
        _validate_character_rotate(
            {
                "move": {
                    "from": {"rotate": -10},
                    "duration": 1.0,
                }
            },
            "character",
        )


def test_rotate_waypoint_requires_explicit_start_value() -> None:
    with pytest.raises(ValidationError, match="move.from.rotate is required"):
        _validate_character_rotate(
            {
                "rotate": 0,
                "move": {
                    "from": {"x": 0},
                    "duration": 1.0,
                    "keyframes": [{"at": 0.5, "rotate": 10}],
                },
            },
            "character",
        )


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf, "10deg"])
def test_rotate_values_must_be_finite_numbers(value) -> None:
    with pytest.raises(ValidationError, match="finite number"):
        _validate_character_rotate(
            {"rotate": value},
            "character",
        )



def test_opacity_waypoints_are_valid_motion_properties() -> None:
    move = {
        "from": {"opacity": 0.0},
        "duration": 1.0,
        "keyframes": [
            {"at": 0.3, "opacity": 1.0, "easing": "ease_out"},
            {"at": 0.7, "x": 20},
        ],
    }

    _validate_character_move(move, "character.move")
    _validate_character_opacity(
        {"opacity": 0.5, "move": move},
        "character",
    )


def test_opacity_animation_requires_explicit_final_value() -> None:
    with pytest.raises(ValidationError, match="opacity is required"):
        _validate_character_opacity(
            {
                "move": {
                    "from": {"opacity": 0.0},
                    "duration": 1.0,
                }
            },
            "character",
        )


def test_opacity_waypoint_requires_explicit_start_value() -> None:
    with pytest.raises(ValidationError, match="move.from.opacity is required"):
        _validate_character_opacity(
            {
                "opacity": 1.0,
                "move": {
                    "from": {"x": 0},
                    "duration": 1.0,
                    "keyframes": [{"at": 0.5, "opacity": 0.5}],
                },
            },
            "character",
        )


@pytest.mark.parametrize("value", [-0.1, 1.1, math.nan, math.inf, -math.inf, "0.5"])
def test_opacity_values_must_be_finite_in_unit_interval(value) -> None:
    with pytest.raises(ValidationError):
        _validate_character_opacity(
            {"opacity": value},
            "character",
        )
