from pathlib import Path

import pytest

from zundamotion.components.config.validate import validate_config
from zundamotion.components.config import validate as validate_module
from zundamotion.exceptions import ValidationError


def _config_with_line(line: dict) -> dict:
    return {"script": {"scenes": [{"id": "scene", "lines": [line]}]}}


def test_validate_config_accepts_minimal_script():
    validate_config({"script": {"scenes": []}})


def test_validate_module_preserves_existing_private_imports():
    assert callable(validate_module._validate_background_options)
    assert callable(validate_module._validate_fg_overlays)
    assert callable(validate_module._validate_badge)
    assert callable(validate_module._validate_image_layers)
    assert callable(validate_module._is_valid_color_string)


def test_validate_config_checks_background_fit():
    config = {"video": {"background_fit": "invalid"}, "script": {"scenes": []}}

    with pytest.raises(ValidationError, match="video.background_fit"):
        validate_config(config)


def test_validate_config_checks_foreground_overlay_file(tmp_path: Path):
    config = _config_with_line(
        {
            "text": "hello",
            "fg_overlays": [{"src": str(tmp_path / "missing.png"), "mode": "overlay"}],
        }
    )

    with pytest.raises(ValidationError, match="source file .* not found"):
        validate_config(config)


def test_validate_config_checks_badge_text():
    config = _config_with_line(
        {"text": "hello", "badge": {"text": "", "position": "top-right"}}
    )

    with pytest.raises(ValidationError, match="must have a non-empty string 'text'"):
        validate_config(config)


def test_validate_config_checks_image_layer_file(tmp_path: Path):
    config = _config_with_line(
        {
            "image_layers": [
                {"show": {"id": "layer", "path": str(tmp_path / "missing.png")}}
            ]
        }
    )

    with pytest.raises(ValidationError, match="show path .* not found"):
        validate_config(config)


def test_validate_config_accepts_existing_assets(tmp_path: Path):
    background = tmp_path / "background.png"
    overlay = tmp_path / "overlay.png"
    layer = tmp_path / "layer.png"
    for path in (background, overlay, layer):
        path.write_bytes(b"placeholder")

    config = {
        "background": {"default": str(background), "fit": "cover"},
        "script": {
            "scenes": [
                {
                    "id": "scene",
                    "fg_overlays": [
                        {"src": str(overlay), "mode": "overlay", "opacity": 0.5}
                    ],
                    "lines": [
                        {
                            "image_layers": [
                                {"show": {"id": "layer", "path": str(layer)}}
                            ]
                        }
                    ],
                }
            ]
        },
    }

    validate_config(config)


def test_validate_config_preserves_wait_error_message():
    config = _config_with_line({"wait": {"duration": 0}})

    with pytest.raises(ValidationError, match="must be positive, but got 0"):
        validate_config(config)


def test_validate_config_preserves_sound_effect_type_error(tmp_path: Path):
    sound_effect = tmp_path / "effect.wav"
    sound_effect.write_bytes(b"placeholder")
    config = _config_with_line(
        {"text": "hello", "sound_effects": [{"path": str(sound_effect), "start_time": "0"}]}
    )

    with pytest.raises(ValidationError, match="must be a number, but got str"):
        validate_config(config)


@pytest.mark.parametrize(
    ("color_filter", "message"),
    [
        ({"hue": -1}, "hue.*between 0 and 360"),
        ({"hue": 361}, "hue.*between 0 and 360"),
        ({"saturation": -0.1}, "saturation.*0 or greater"),
        ({"brightness": -0.1}, "brightness.*0 or greater"),
        ({"hue": "blue"}, "hue.*must be a number"),
    ],
)
def test_validate_config_rejects_invalid_character_color_filter(
    color_filter: dict, message: str
) -> None:
    config = _config_with_line(
        {
            "text": "hello",
            "characters": [
                {"name": "hero", "visible": True, "color_filter": color_filter}
            ],
        }
    )

    with pytest.raises(ValidationError, match=message):
        validate_config(config)


def test_validate_config_accepts_character_color_filter_in_defaults() -> None:
    validate_config(
        {
            "defaults": {
                "characters": {
                    "hero": {
                        "color_filter": {
                            "hue": 210,
                            "saturation": 1.2,
                            "brightness": 0.9,
                        }
                    }
                }
            },
            "script": {"scenes": []},
        }
    )
