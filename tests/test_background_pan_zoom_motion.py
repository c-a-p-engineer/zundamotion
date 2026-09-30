from __future__ import annotations

import pytest

from zundamotion.cache import CacheManager
from zundamotion.components.config.validate_motion_background import (
    validate_background_motion_effects,
)
from zundamotion.components.video.clip.effects.resolve import (
    resolve_background_effects,
)
from zundamotion.exceptions import ValidationError


def _effect(**overrides):
    value = {
        "type": "bg:pan_zoom",
        "zoom": {"from": 1.0, "to": 1.4},
        "pan": {
            "from": {"x": 0.2, "y": 0.5},
            "to": {"x": 0.8, "y": 0.5},
        },
        "start": 0.1,
        "duration": 1.2,
        "easing": "ease_in_out",
        "keyframes": [
            {"at": 0.3, "zoom": 1.15, "easing": "ease_out"},
            {"at": 0.8, "pan": {"x": 0.6}, "zoom": 1.3},
        ],
    }
    value.update(overrides)
    return value


def test_legacy_pan_zoom_ignores_new_output_fps_and_keeps_linear_path() -> None:
    snippet = resolve_background_effects(
        effects=[
            {
                "type": "bg:pan_zoom",
                "zoom": {"from": 1.0, "to": 1.2},
                "pan": {
                    "from": {"x": 0.2, "y": 0.5},
                    "to": {"x": 0.8, "y": 0.5},
                },
            }
        ],
        input_label="[bg]",
        duration=4.0,
        width=1280,
        height=720,
        fps=60,
    )

    assert snippet is not None
    filter_text = snippet.filter_chain[0]
    assert "on/120.000000" in filter_text
    assert "fps=30.000[bg_pan_zoom_1]" in filter_text
    assert "if(lt(" not in filter_text


def test_legacy_pan_zoom_keeps_silent_clamp_compatibility() -> None:
    snippet = resolve_background_effects(
        effects=[
            {
                "type": "bg:pan_zoom",
                "zoom": {"from": 0.2, "to": 9.0},
                "pan": {
                    "from": {"x": -1.0, "y": 2.0},
                    "to": {"x": 3.0, "y": -2.0},
                },
                "fps": 999,
            }
        ],
        input_label="[bg]",
        duration=2.0,
        width=320,
        height=180,
        fps=24,
    )

    assert snippet is not None
    filter_text = snippet.filter_chain[0]
    assert "1.000000+(3.000000)" in filter_text
    assert "0.000000+(1.000000)" in filter_text
    assert "1.000000+(-1.000000)" in filter_text
    assert "fps=120.000[bg_pan_zoom_1]" in filter_text


def test_keyed_pan_zoom_uses_motion_track_and_output_fps() -> None:
    snippet = resolve_background_effects(
        effects=[_effect()],
        input_label="[bg]",
        duration=2.0,
        width=1280,
        height=720,
        fps=60,
    )

    assert snippet is not None
    filter_text = snippet.filter_chain[0]
    assert "fps=60.000[bg_pan_zoom_1]" in filter_text
    assert "(on/60.000000)" in filter_text
    assert "if(lt(" in filter_text
    assert "1-(1-(" in filter_text
    assert "0.500000" in filter_text


def test_keyed_ken_burns_uses_same_motion_owner() -> None:
    effect = _effect(type="bg:ken_burns")
    snippet = resolve_background_effects(
        effects=[effect],
        input_label="[bg]",
        duration=2.0,
        width=640,
        height=360,
        fps=30,
    )

    assert snippet is not None
    assert snippet.output_label == "[bg_pan_zoom_1]"
    assert "(on/30.000000)" in snippet.filter_chain[0]


def test_strict_background_motion_validation_accepts_sparse_waypoints() -> None:
    validate_background_motion_effects(
        [_effect()],
        "line.background_effects",
    )


@pytest.mark.parametrize(
    ("effect", "message"),
    [
        (
            _effect(duration=None),
            "duration must be a finite number",
        ),
        (
            _effect(zoom={"from": 0.9, "to": 1.2}),
            "zoom.from must be between 1.0 and 4.0",
        ),
        (
            _effect(
                keyframes=[
                    {"at": 0.8, "zoom": 1.2},
                    {"at": 0.4, "zoom": 1.3},
                ]
            ),
            "strictly increasing",
        ),
        (
            _effect(keyframes=[{"at": 0.3, "pan": {"x": 1.2}}]),
            "pan.x must be between 0.0 and 1.0",
        ),
        (
            _effect(keyframes=[{"at": 0.3, "opacity": 0.5}]),
            "unsupported properties",
        ),
    ],
)
def test_strict_background_motion_validation_rejects_invalid_input(
    effect,
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        validate_background_motion_effects(
            [effect],
            "line.background_effects",
        )


def test_invalid_legacy_values_are_not_hardened_by_new_validator() -> None:
    validate_background_motion_effects(
        [
            {
                "type": "bg:pan_zoom",
                "zoom": {"from": "bad", "to": 99},
                "pan": {"from": {"x": -10, "y": 20}},
            }
        ],
        "line.background_effects",
    )



def test_background_keyframes_change_cache_identity(tmp_path) -> None:
    cache = CacheManager(tmp_path / "cache")
    first = {
        "background_effects": [
            _effect(
                keyframes=[
                    {"at": 0.3, "zoom": 1.15},
                    {"at": 0.8, "pan": {"x": 0.6}, "zoom": 1.3},
                ]
            )
        ]
    }
    changed = {
        "background_effects": [
            _effect(
                keyframes=[
                    {"at": 0.35, "zoom": 1.15},
                    {"at": 0.8, "pan": {"x": 0.6}, "zoom": 1.3},
                ]
            )
        ]
    }

    assert cache._generate_hash(first) != cache._generate_hash(changed)
