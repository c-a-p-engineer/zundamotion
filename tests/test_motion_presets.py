from __future__ import annotations

from copy import deepcopy

import pytest

from zundamotion.components.config.validate_motion_preset import (
    validate_character_motion_preset,
)
from zundamotion.components.video.clip.motion_preset import (
    expand_character_motion_preset,
)
from zundamotion.exceptions import ValidationError


def test_pop_preset_expands_deterministically_without_mutating_input() -> None:
    character = {
        "name": "hero",
        "visible": True,
        "scale": 1.0,
        "position": {"x": 0, "y": -32},
        "move": {
            "preset": "pop",
            "start": 0.1,
            "duration": 0.5,
            "intensity": 1.0,
        },
    }
    original = deepcopy(character)

    expanded = expand_character_motion_preset(character)

    assert character == original
    assert expanded is not character
    assert expanded["move"]["from"]["scale"] == pytest.approx(0.82)
    assert expanded["move"]["start"] == pytest.approx(0.1)
    assert expanded["move"]["duration"] == pytest.approx(0.5)
    assert expanded["move"]["easing"] == "ease_in_out"
    assert expanded["move"]["keyframes"] == [
        {
            "at": pytest.approx(0.325),
            "scale": pytest.approx(1.08),
            "easing": "ease_out",
        }
    ]
    assert "preset" not in expanded["move"]
    assert "intensity" not in expanded["move"]


def test_bounce_preset_expands_sparse_y_track() -> None:
    expanded = expand_character_motion_preset(
        {
            "name": "hero",
            "visible": True,
            "position": {"x": 24, "y": -32},
            "scale": 1.0,
            "move": {
                "preset": "bounce",
                "intensity": 0.5,
            },
        }
    )

    move = expanded["move"]
    assert move["duration"] == pytest.approx(0.60)
    assert move["from"] == {"y": pytest.approx(-32.0)}
    assert move["keyframes"][0] == {
        "at": pytest.approx(0.21),
        "y": pytest.approx(-56.0),
        "easing": "ease_out",
    }
    assert move["keyframes"][1] == {
        "at": pytest.approx(0.408),
        "y": pytest.approx(-27.0),
        "easing": "ease_in_out",
    }
    assert all("x" not in frame for frame in move["keyframes"])


def test_emphasis_preset_uses_stable_default_duration() -> None:
    expanded = expand_character_motion_preset(
        {
            "name": "hero",
            "visible": True,
            "scale": 0.8,
            "position": {"x": 0, "y": 0},
            "move": {
                "preset": "emphasis",
                "intensity": 2.0,
            },
        }
    )

    move = expanded["move"]
    assert move["duration"] == pytest.approx(0.50)
    assert move["from"]["scale"] == pytest.approx(0.8)
    assert move["keyframes"][0]["at"] == pytest.approx(0.225)
    assert move["keyframes"][0]["scale"] == pytest.approx(0.992)


def test_zero_intensity_remains_valid_deterministic_motion_authoring() -> None:
    expanded = expand_character_motion_preset(
        {
            "scale": 1.0,
            "move": {"preset": "pop", "intensity": 0.0},
        }
    )

    assert expanded["move"]["from"]["scale"] == pytest.approx(1.0)
    assert expanded["move"]["keyframes"][0]["scale"] == pytest.approx(1.0)


def test_disabled_preset_keeps_authoring_move_and_skips_final_state_requirement() -> None:
    character = {
        "name": "hero",
        "move": {
            "preset": "pop",
            "enabled": False,
            "duration": 0.4,
            "intensity": 1.0,
        },
    }

    validate_character_motion_preset(character, "character")
    expanded = expand_character_motion_preset(character)

    assert expanded == character
    assert expanded is not character


@pytest.mark.parametrize(
    ("character", "message"),
    [
        (
            {"scale": 1.0, "move": {"preset": "unknown"}},
            "preset must be one of",
        ),
        (
            {
                "scale": 1.0,
                "move": {
                    "preset": "pop",
                    "from": {"scale": 0.5},
                },
            },
            "unsupported properties with preset: from",
        ),
        (
            {
                "scale": 1.0,
                "move": {
                    "preset": "pop",
                    "keyframes": [{"at": 0.2, "scale": 1.2}],
                },
            },
            "unsupported properties with preset: keyframes",
        ),
        (
            {
                "scale": 1.0,
                "move": {"preset": "pop", "duration": 0},
            },
            "duration must be greater than 0",
        ),
        (
            {
                "scale": 1.0,
                "move": {"preset": "pop", "start": True},
            },
            "start must be a finite number",
        ),
        (
            {
                "scale": 1.0,
                "move": {"preset": "pop", "intensity": 2.1},
            },
            "intensity must be between 0.0 and 2.0",
        ),
        (
            {
                "position": {"x": 0},
                "move": {"preset": "bounce"},
            },
            "position.y is required",
        ),
        (
            {
                "position": {"x": 0, "y": "10*t"},
                "move": {"preset": "bounce"},
            },
            "position.y must be a finite number",
        ),
        (
            {
                "move": {"preset": "emphasis"},
            },
            "scale is required",
        ),
    ],
)
def test_preset_validation_rejects_invalid_authoring(character, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        validate_character_motion_preset(character, "character")


def test_preset_validation_accepts_first_slice_presets() -> None:
    validate_character_motion_preset(
        {
            "scale": 1.0,
            "move": {
                "preset": "pop",
                "start": 0.1,
                "duration": 0.45,
                "intensity": 1.2,
            },
        },
        "pop",
    )
    validate_character_motion_preset(
        {
            "position": {"x": 0, "y": -32},
            "move": {"preset": "bounce"},
        },
        "bounce",
    )
    validate_character_motion_preset(
        {
            "scale": 0.8,
            "move": {"preset": "emphasis"},
        },
        "emphasis",
    )
