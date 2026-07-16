"""Configuration validation entry point.

Script traversal and domain-specific validators live in adjacent modules.
"""

from pathlib import Path
from typing import Any, Dict

from ...exceptions import ValidationError
from .validate_background import _validate_background_options
from .validate_badges import (
    _validate_badge,
    _validate_badge_definition,
    _validate_badge_definitions_list,
    _validate_badge_update,
)
from .validate_common import (
    ANCHOR_CHOICES,
    BACKGROUND_FIT_CHOICES,
    BADGE_POSITION_CHOICES,
    HEX_COLOR_RE,
    HSL_COLOR_RE,
    IMAGE_LAYER_TRANSITION_TYPES,
    RGB_COLOR_RE,
    is_valid_color_string as _is_valid_color_string,
    validate_character_color_filter,
)
from .validate_layers import _validate_image_layer_transition, _validate_image_layers
from .validate_overlays import _validate_fg_overlays
from .validate_script import validate_script


def _validate_plugins_config(cfg: Dict[str, Any]) -> None:
    if not isinstance(cfg, dict):
        raise ValidationError("'plugins' section must be a dictionary when provided.")
    enabled = cfg.get("enabled")
    if enabled is not None and not isinstance(enabled, bool):
        raise ValidationError("'plugins.enabled' must be a boolean.")

    for key in ("paths", "allow", "deny"):
        value = cfg.get(key)
        if value is None:
            continue
        if not isinstance(value, list):
            raise ValidationError(f"'plugins.{key}' must be a list when provided.")
        for idx, item in enumerate(value):
            if not isinstance(item, str):
                raise ValidationError(
                    f"'plugins.{key}[{idx}]' must be a string path or ID."
                )


def _validate_video_config(config: Dict[str, Any]) -> None:
    video_cfg = config.get("video", {}) or {}
    audio_codec = video_cfg.get("audio_codec")
    if audio_codec is not None and str(audio_codec).strip().lower() != "aac":
        raise ValidationError(
            "'video.audio_codec' must be 'aac' for MP4 output; "
            "PCM is used automatically for intermediate WAV files."
        )
    fit_mode = video_cfg.get("background_fit")
    if fit_mode is None:
        return
    if not isinstance(fit_mode, str):
        raise ValidationError("'video.background_fit' must be a string.")
    if fit_mode.lower() not in BACKGROUND_FIT_CHOICES:
        raise ValidationError(
            f"'video.background_fit' must be one of {sorted(BACKGROUND_FIT_CHOICES)}."
        )


def _validate_global_background(config: Dict[str, Any]) -> None:
    background_cfg = config.get("background", {}) or {}
    if not background_cfg:
        return
    if not isinstance(background_cfg, dict):
        raise ValidationError("'background' section must be a dictionary.")
    _validate_background_options(background_cfg, "global background")


def _validate_bgm_layers(script: Dict[str, Any]) -> None:
    bgm_layers = script.get("bgm_layers")
    if bgm_layers is None:
        return
    if not isinstance(bgm_layers, list):
        raise ValidationError("'bgm_layers' must be a list.")

    seen_ids = set()
    for idx, layer in enumerate(bgm_layers):
        if not isinstance(layer, dict):
            raise ValidationError(f"bgm_layers entry {idx} must be a dictionary.")
        layer_id = layer.get("id")
        if not isinstance(layer_id, str) or not layer_id.strip():
            raise ValidationError(f"bgm_layers entry {idx} must have a non-empty 'id'.")
        if layer_id in seen_ids:
            raise ValidationError(f"bgm_layers id '{layer_id}' is duplicated.")
        seen_ids.add(layer_id)
        _validate_bgm_layer(layer_id, layer)


def _validate_bgm_layer(layer_id: str, layer: Dict[str, Any]) -> None:
    file_path = layer.get("file")
    if not isinstance(file_path, str) or not file_path.strip():
        raise ValidationError(f"bgm_layers '{layer_id}' must have a 'file' path.")
    file_full_path = Path(file_path)
    if not file_full_path.exists():
        raise ValidationError(f"bgm_layers '{layer_id}' file '{file_path}' does not exist.")
    if not file_full_path.is_file():
        raise ValidationError(f"bgm_layers '{layer_id}' file '{file_path}' is not a file.")
    gain = layer.get("gain")
    if gain is not None and not isinstance(gain, (int, float)):
        raise ValidationError(f"bgm_layers '{layer_id}' gain must be a number.")
    loop = layer.get("loop")
    if loop is not None and not isinstance(loop, bool):
        raise ValidationError(f"bgm_layers '{layer_id}' loop must be a boolean.")


def _validate_defaults(config: Dict[str, Any]) -> None:
    defaults = config.get("defaults", {})
    if not defaults:
        return
    for key in ("characters_persist", "background_persist"):
        value = defaults.get(key)
        if value is not None and not isinstance(value, bool):
            raise ValidationError(f"'defaults.{key}' must be a boolean.")
    characters = defaults.get("characters")
    if characters is not None:
        if not isinstance(characters, dict):
            raise ValidationError("'defaults.characters' must be a dictionary.")
        for name, character in characters.items():
            if not isinstance(character, dict):
                raise ValidationError(
                    f"'defaults.characters.{name}' must be a dictionary."
                )
            asset_name = character.get("asset_name")
            if asset_name is not None and (
                not isinstance(asset_name, str) or not asset_name.strip()
            ):
                raise ValidationError(
                    f"'defaults.characters.{name}.asset_name' must be a non-empty string."
                )
            validate_character_color_filter(
                character.get("color_filter"),
                f"defaults.characters.{name}.color_filter",
            )


def _validate_transitions(config: Dict[str, Any]) -> None:
    transitions_cfg = config.get("transitions")
    if transitions_cfg is None:
        return
    if not isinstance(transitions_cfg, dict):
        raise ValidationError("'transitions' section must be a dictionary when provided.")
    wait_padding = transitions_cfg.get("wait_padding_seconds")
    if wait_padding is None:
        return
    if not isinstance(wait_padding, (int, float)):
        raise ValidationError("'transitions.wait_padding_seconds' must be a number.")
    if wait_padding < 0:
        raise ValidationError("'transitions.wait_padding_seconds' must be non-negative.")


def validate_config(config: Dict[str, Any]) -> None:
    """Validate the loaded configuration and script data."""
    plugins_cfg = config.get("plugins")
    if plugins_cfg is not None:
        _validate_plugins_config(plugins_cfg)
    _validate_video_config(config)
    _validate_global_background(config)

    script = config.get("script")
    if not isinstance(script, dict):
        raise ValueError("Script data must be a dictionary under the 'script' key.")
    _validate_bgm_layers(script)
    _validate_defaults(config)
    _validate_transitions(config)
    validate_script(config, script)
