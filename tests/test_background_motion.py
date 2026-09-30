from __future__ import annotations

import pytest

from zundamotion.components.config.validate_script import validate_script
from zundamotion.components.video.clip.background_motion import (
    build_background_pan_zoom_expressions,
)
from zundamotion.components.video.clip.effects.resolve import resolve_background_effects
from zundamotion.exceptions import ValidationError


def _strict_effect() -> dict:
    return {
        "type": "bg:pan_zoom",
        "zoom": {"from": 1.0, "to": 1.4},
        "pan": {
            "from": {"x": 0.2, "y": 0.5},
            "to": {"x": 0.8, "y": 0.4},
        },
        "start": 0.1,
        "duration": 1.2,
        "easing": "ease_in_out",
        "keyframes": [
            {"at": 0.4, "zoom": 1.2, "easing": "ease_out"},
            {"at": 0.8, "pan": {"x": 0.6}, "easing": "ease_in"},
        ],
    }


def _validate_effect(effect: dict) -> None:
    validate_script(
        {},
        {
            "scenes": [
                {
                    "id": "motion",
                    "lines": [
                        {
                            "wait": 1.5,
                            "background_effects": [effect],
                        }
                    ],
                }
            ]
        },
    )


def test_legacy_background_pan_zoom_expression_remains_compatible() -> None:
    snippet = resolve_background_effects(
        effects=[
            {
                "type": "bg:pan_zoom",
                "zoom": {"from": 1.0, "to": 1.2},
                "pan": {
                    "from": {"x": 0.2, "y": 0.5},
                    "to": {"x": 0.8, "y": 0.5},
                },
                "fps": 30,
            }
        ],
        input_label="[bg]",
        duration=4.0,
        width=1280,
        height=720,
        output_fps=24,
    )

    assert snippet is not None
    assert snippet.filter_chain == [
        "[bg]zoompan="
        "z='1.000000+(0.200000)*min(max(on/120.000000\\,0)\\,1)':"
        "x='(iw-iw/zoom)*(0.200000+(0.600000)*min(max(on/120.000000\\,0)\\,1))':"
        "y='(ih-ih/zoom)*(0.500000+(0.000000)*min(max(on/120.000000\\,0)\\,1))':"
        "d=1:s=1280x720:fps=30.000[bg_pan_zoom_1]"
    ]


def test_legacy_background_pan_zoom_keeps_clamp_and_fallback() -> None:
    snippet = resolve_background_effects(
        effects=[
            {
                "type": "bg:ken_burns",
                "zoom": {"from": "invalid", "to": 9.0},
                "pan": {
                    "from": {"x": -5.0, "y": "invalid"},
                    "to": {"x": 7.0, "y": 2.0},
                },
                "fps": 999,
            }
        ],
        input_label="[bg]",
        duration=1.0,
        width=320,
        height=180,
        output_fps=24,
    )

    assert snippet is not None
    rendered = snippet.filter_chain[0]
    assert "z='1.000000+(3.000000)" in rendered
    assert "x='(iw-iw/zoom)*(0.000000+(1.000000)" in rendered
    assert "y='(ih-ih/zoom)*(0.500000+(0.500000)" in rendered
    assert "fps=120.000[bg_pan_zoom_1]" in rendered


def test_strict_background_motion_uses_renderer_fps_and_sparse_tracks() -> None:
    expressions = build_background_pan_zoom_expressions(
        _strict_effect(),
        output_fps=24,
    )

    assert expressions.fps == 24
    assert "(on/24.000000)" in expressions.zoom
    assert "(on/24.000000)" in expressions.pan_x
    assert "(on/24.000000)" in expressions.pan_y
    assert "if(lt(" in expressions.zoom
    assert "if(lt(" in expressions.pan_x
    # pan.y has no intermediate waypoint but still interpolates start -> final.
    assert "0.500000" in expressions.pan_y
    assert "0.400000" in expressions.pan_y


def test_strict_background_motion_accepts_valid_keyframes() -> None:
    _validate_effect(_strict_effect())


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda effect: effect["keyframes"].append(
                {"at": 0.8, "zoom": 1.3}
            ),
            "strictly increasing",
        ),
        (
            lambda effect: effect["keyframes"].append(
                {"at": 1.4, "zoom": 1.3}
            ),
            "less than",
        ),
        (
            lambda effect: effect["keyframes"][0].update({"zoom": 0.9}),
            "between 1.0 and 4.0",
        ),
        (
            lambda effect: effect["keyframes"][0].update(
                {"pan": {"x": 1.1}}
            ),
            "between 0.0 and 1.0",
        ),
        (
            lambda effect: effect.update({"fps": 0}),
            "between 1 and 120",
        ),
        (
            lambda effect: effect.update({"unknown": True}),
            "unsupported properties",
        ),
    ],
)
def test_strict_background_motion_rejects_invalid_input(mutate, message: str) -> None:
    effect = _strict_effect()
    mutate(effect)
    with pytest.raises(ValidationError, match=message):
        _validate_effect(effect)


def test_empty_keyframes_keep_legacy_permissive_validation() -> None:
    _validate_effect(
        {
            "type": "bg:pan_zoom",
            "zoom": {"from": "legacy-fallback", "to": 99},
            "fps": "legacy-fallback",
            "keyframes": [],
        }
    )
