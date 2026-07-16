"""Scene and line traversal for configuration validation."""

from pathlib import Path
from typing import Any, Dict, List

from ...exceptions import ValidationError
from ...utils.filter_presets import AUDIO_FILTER_PRESETS, VIDEO_FILTER_PRESETS
from .validate_background import _validate_background_options
from .validate_badges import (
    _validate_badge,
    _validate_badge_definitions_list,
    _validate_badge_update,
)
from .validate_layers import _validate_image_layers
from .validate_overlays import _validate_fg_overlays
from .validate_common import validate_character_color_filter


def _line_from_item(scene_id: str, item: Dict[str, Any], idx: int) -> Dict[str, Any] | None:
    if "say" in item:
        value = item.get("say")
        if isinstance(value, str):
            return {"text": value}
        if isinstance(value, dict):
            return value
        raise ValidationError(
            f"Scene '{scene_id}' item {idx} say must be a string or dictionary."
        )
    if "wait" in item:
        value = item.get("wait")
        if isinstance(value, dict) and "wait" in value:
            return value
        if isinstance(value, dict) and "duration" in value:
            return {"wait": value}
        return {"wait": value}
    if "image_layers" in item:
        value = item.get("image_layers")
        return value if isinstance(value, dict) else {"image_layers": value}
    if "bgm" in item:
        _validate_bgm_item(scene_id, idx, item.get("bgm"))
        return None
    if "topic" in item:
        value = item.get("topic")
        if not isinstance(value, str) or not value.strip():
            raise ValidationError(
                f"Scene '{scene_id}' item {idx} topic must be a non-empty string."
            )
        return None
    raise ValidationError(f"Scene '{scene_id}' item {idx} must contain say/wait/bgm/topic.")


def _validate_bgm_item(scene_id: str, idx: int, value: Any) -> None:
    if not isinstance(value, dict):
        raise ValidationError(f"Scene '{scene_id}' item {idx} bgm must be a dictionary.")
    bgm_id = value.get("id")
    if not isinstance(bgm_id, str) or not bgm_id.strip():
        raise ValidationError(f"Scene '{scene_id}' item {idx} bgm requires a non-empty id.")
    if value.get("action") not in {"start", "stop", "resume"}:
        raise ValidationError(
            f"Scene '{scene_id}' item {idx} bgm action must be start/stop/resume."
        )
    fade = value.get("fade")
    if fade is not None and not isinstance(fade, (int, float)):
        raise ValidationError(f"Scene '{scene_id}' item {idx} bgm fade must be a number.")


def _resolve_scene_lines(scene_id: str, scene: Dict[str, Any]) -> List[Dict[str, Any]]:
    items = scene.get("items")
    lines = scene.get("lines")
    if items is not None:
        if not isinstance(items, list):
            raise ValidationError(f"Scene '{scene_id}' items must be a list.")
        lines = []
        for item_idx, item in enumerate(items):
            if not isinstance(item, dict):
                raise ValidationError(
                    f"Scene '{scene_id}' item {item_idx} must be a dictionary."
                )
            line = _line_from_item(scene_id, item, item_idx)
            if line is not None:
                lines.append(line)
    if not isinstance(lines, list):
        raise ValidationError(f"Scene '{scene_id}' must contain a 'lines' list.")
    return lines


def _validate_scene_settings(config: Dict[str, Any], scene: Dict[str, Any], scene_id: str) -> None:
    character_defaults = scene.get("character_defaults")
    if character_defaults is not None:
        if not isinstance(character_defaults, dict):
            raise ValidationError(f"Scene '{scene_id}' character_defaults must be a dictionary.")
        for name, value in character_defaults.items():
            if not isinstance(value, dict):
                raise ValidationError(
                    f"Scene '{scene_id}' character_defaults.{name} must be a dictionary."
                )
            validate_character_color_filter(
                value.get("color_filter"),
                f"scene '{scene_id}' character_defaults.{name}.color_filter",
            )
    background_cfg = scene.get("background")
    if background_cfg is not None:
        if not isinstance(background_cfg, dict):
            raise ValidationError(f"Scene '{scene_id}' background must be a dictionary.")
        _validate_background_options(background_cfg, f"scene '{scene_id}' background")
    for key in ("characters_persist", "background_persist"):
        value = scene.get(key)
        if value is not None and not isinstance(value, bool):
            raise ValidationError(f"Scene '{scene_id}' {key} must be a boolean.")
    video_filter = scene.get("video_filter")
    if video_filter is not None:
        if not isinstance(video_filter, str):
            raise ValidationError(f"Scene '{scene_id}' video_filter must be a string.")
        if video_filter.strip().lower() not in VIDEO_FILTER_PRESETS:
            raise ValidationError(
                f"Scene '{scene_id}' video_filter must be one of {sorted(VIDEO_FILTER_PRESETS)}."
            )
    bg_path = scene.get("bg", config.get("background", {}).get("default"))
    if bg_path:
        _validate_file_path(bg_path, f"Background file '{bg_path}' for scene '{scene_id}'")


def _validate_file_path(path: str, label: str) -> None:
    resolved = Path(path)
    if not resolved.exists():
        raise ValidationError(f"{label} does not exist.")
    if not resolved.is_file():
        raise ValidationError(f"{label.replace('file', 'path')} is not a file.")


def _validate_scene_transition(scene: Dict[str, Any], scene_id: str) -> None:
    transition = scene.get("transition")
    if not transition:
        return
    if not isinstance(transition, dict):
        raise ValidationError(
            f"Transition configuration for scene '{scene_id}' must be a dictionary."
        )
    transition_type = transition.get("type") or transition.get("video")
    if not transition_type:
        raise ValidationError(f"Transition for scene '{scene_id}' must have a 'type' or 'video'.")
    if not isinstance(transition_type, str):
        raise ValidationError(
            f"Transition type for scene '{scene_id}' must be a string, but got {type(transition_type).__name__}."
        )
    duration = transition.get("duration")
    if duration is None:
        raise ValidationError(f"Transition for scene '{scene_id}' must have a 'duration'.")
    if not isinstance(duration, (int, float)):
        raise ValidationError(
            f"Transition duration for scene '{scene_id}' must be a number, but got {type(duration).__name__}."
        )
    if duration <= 0:
        raise ValidationError(
            f"Transition duration for scene '{scene_id}' must be positive, but got {duration}."
        )


def _validate_top_level_assets(config: Dict[str, Any]) -> None:
    for asset_key, asset_path in config.get("assets", {}).items():
        resolved = Path(asset_path)
        if not resolved.exists():
            raise ValidationError(f"Asset '{asset_key}' path '{asset_path}' does not exist.")
        if not resolved.is_file():
            raise ValidationError(f"Asset '{asset_key}' path '{asset_path}' is not a file.")


def _validate_line_features(line: Dict[str, Any], scene_id: str, line_idx: int) -> None:
    container_id = f"scene '{scene_id}', line {line_idx}"
    background = line.get("background")
    if background is not None:
        if not isinstance(background, dict):
            raise ValidationError(f"Background override for {container_id} must be a dictionary.")
        _validate_background_options(background, f"{container_id} background")
    _validate_fg_overlays(line, container_id)
    _validate_badge(line, container_id)
    _validate_line_badges(line.get("badges"), container_id)
    _validate_image_layers(line, container_id)
    characters = line.get("characters")
    if characters is not None:
        if not isinstance(characters, list):
            raise ValidationError(f"Characters for {container_id} must be a list.")
        for char_idx, character in enumerate(characters):
            if not isinstance(character, dict):
                raise ValidationError(
                    f"Character at {container_id}, index {char_idx} must be a dictionary."
                )
            asset_name = character.get("asset_name")
            if asset_name is not None and (
                not isinstance(asset_name, str) or not asset_name.strip()
            ):
                raise ValidationError(
                    f"Character asset_name at {container_id}, index {char_idx} must be a non-empty string."
                )
            validate_character_color_filter(
                character.get("color_filter"),
                f"{container_id}, characters[{char_idx}].color_filter",
            )
            _validate_character_move(
                character.get("move"),
                f"{container_id}, characters[{char_idx}].move",
            )
    reset_flag = line.get("reset_characters")
    if reset_flag is not None and not isinstance(reset_flag, bool):
        raise ValidationError(
            f"Line at scene '{scene_id}', index {line_idx} reset_characters must be a boolean."
        )


def _validate_line_badges(badges: Any, container_id: str) -> None:
    if badges is None:
        return
    if not isinstance(badges, list):
        raise ValidationError(f"Badges for {container_id} must be a list.")
    for badge_idx, badge in enumerate(badges):
        _validate_badge_update(badge, f"{container_id}, badges[{badge_idx}]")


def _validate_wait_line(wait_value: Any, scene_id: str, line_idx: int) -> None:
    if isinstance(wait_value, (int, float)):
        if wait_value <= 0:
            raise ValidationError(
                f"Wait duration for scene '{scene_id}', line {line_idx} must be positive, but got {wait_value}."
            )
        return
    if not isinstance(wait_value, dict):
        raise ValidationError(
            f"Wait value for scene '{scene_id}', line {line_idx} must be a number or a dictionary."
        )
    duration = wait_value.get("duration")
    if duration is None:
        raise ValidationError(
            f"Wait dictionary for scene '{scene_id}', line {line_idx} must contain 'duration'."
        )
    if not isinstance(duration, (int, float)):
        raise ValidationError(
            f"Wait duration for scene '{scene_id}', line {line_idx} must be a number, but got {type(duration).__name__}."
        )
    if duration <= 0:
        raise ValidationError(
            f"Wait duration for scene '{scene_id}', line {line_idx} must be positive, but got {duration}."
        )


def _validate_character_move(move: Any, label: str) -> None:
    if move is None:
        return
    if not isinstance(move, dict):
        raise ValidationError(f"{label} must be a dictionary.")
    enabled = move.get("enabled")
    if enabled is not None and not isinstance(enabled, bool):
        raise ValidationError(f"{label}.enabled must be a boolean.")
    for key in ("duration", "start"):
        value = move.get(key)
        if value is None:
            continue
        if not isinstance(value, (int, float)):
            raise ValidationError(f"{label}.{key} must be a number.")
        if value < 0:
            raise ValidationError(f"{label}.{key} must be greater than or equal to 0.")
    easing = move.get("easing")
    if easing is not None and easing not in {
        "linear",
        "ease_in",
        "ease_out",
        "ease_in_out",
    }:
        raise ValidationError(
            f"{label}.easing must be one of linear, ease_in, ease_out, ease_in_out."
        )
    from_position = move.get("from")
    if from_position is not None:
        if not isinstance(from_position, dict):
            raise ValidationError(f"{label}.from must be a dictionary.")
        for axis in ("x", "y"):
            value = from_position.get(axis)
            if value is not None and not isinstance(value, (int, float, str)):
                raise ValidationError(f"{label}.from.{axis} must be a number or string.")
        from_scale = from_position.get("scale")
        if from_scale is not None:
            if not isinstance(from_scale, (int, float)):
                raise ValidationError(f"{label}.from.scale must be a number.")
            if from_scale <= 0:
                raise ValidationError(f"{label}.from.scale must be greater than 0.")


def _validate_sound_effects(sound_effects: Any, scene_id: str, line_idx: int) -> None:
    if not sound_effects:
        return
    if not isinstance(sound_effects, list):
        raise ValidationError(f"Sound effects for scene '{scene_id}', line {line_idx} must be a list.")
    for se_idx, sound_effect in enumerate(sound_effects):
        _validate_sound_effect(sound_effect, scene_id, line_idx, se_idx)


def _validate_sound_effect(sound_effect: Any, scene_id: str, line_idx: int, se_idx: int) -> None:
    label = f"scene '{scene_id}', line {line_idx}, index {se_idx}"
    if not isinstance(sound_effect, dict):
        raise ValidationError(f"Sound effect at {label} must be a dictionary.")
    path = sound_effect.get("path")
    if not path:
        raise ValidationError(f"Sound effect at {label} must have a 'path'.")
    resolved = Path(path)
    if not resolved.exists():
        raise ValidationError(f"Sound effect file '{path}' for {label} does not exist.")
    if not resolved.is_file():
        raise ValidationError(f"Sound effect path '{path}' for {label} is not a file.")
    start_time = sound_effect.get("start_time", 0.0)
    if not isinstance(start_time, (int, float)):
        raise ValidationError(
            f"Sound effect start_time for {label} must be a number, but got {type(start_time).__name__}."
        )
    if start_time < 0:
        raise ValidationError(
            f"Sound effect start_time for {label} must be non-negative, but got {start_time}."
        )
    volume = sound_effect.get("volume", 1.0)
    if not isinstance(volume, (int, float)):
        raise ValidationError(
            f"Sound effect volume for {label} must be a number, but got {type(volume).__name__}."
        )
    if not (0.0 <= volume <= 1.0):
        raise ValidationError(
            f"Sound effect volume for {label} must be between 0.0 and 1.0, but got {volume}."
        )


def _validate_speech_line(line: Dict[str, Any], scene_id: str, line_idx: int) -> None:
    speed = line.get("speed")
    if speed is not None and not (0.5 <= speed <= 2.0):
        raise ValidationError(
            f"Speech speed for scene '{scene_id}', line {line_idx} must be between 0.5 and 2.0, but got {speed}."
        )
    pitch = line.get("pitch")
    if pitch is not None and not (-1.0 <= pitch <= 1.0):
        raise ValidationError(
            f"Speech pitch for scene '{scene_id}', line {line_idx} must be between -1.0 and 1.0, but got {pitch}."
        )
    speaker_id = line.get("speaker_id")
    if speaker_id is not None and not isinstance(speaker_id, int):
        raise ValidationError(
            f"Speaker ID for scene '{scene_id}', line {line_idx} must be an integer, but got {type(speaker_id).__name__}."
        )
    _validate_sound_effects(line.get("sound_effects"), scene_id, line_idx)
    audio_filter = line.get("audio_filter")
    if audio_filter is not None:
        if not isinstance(audio_filter, str):
            raise ValidationError(f"Audio filter for scene '{scene_id}', line {line_idx} must be a string.")
        if audio_filter.strip().lower() not in AUDIO_FILTER_PRESETS:
            raise ValidationError(
                f"Audio filter for scene '{scene_id}', line {line_idx} must be one of {sorted(AUDIO_FILTER_PRESETS)}."
            )


def _validate_line(line: Any, scene_id: str, line_idx: int) -> None:
    if not isinstance(line, dict):
        raise ValidationError(f"Line at scene '{scene_id}', index {line_idx} must be a dictionary.")
    _validate_line_features(line, scene_id, line_idx)
    has_image_layers = line.get("image_layers") is not None
    if "text" not in line and "wait" not in line and not has_image_layers:
        raise ValidationError(
            f"Line at scene '{scene_id}', index {line_idx} must contain 'text', 'wait', or 'image_layers'."
        )
    if "text" in line and "wait" in line:
        raise ValidationError(
            f"Line at scene '{scene_id}', index {line_idx} cannot contain both 'text' and 'wait'."
        )
    if "wait" in line:
        _validate_wait_line(line["wait"], scene_id, line_idx)
        return
    _validate_speech_line(line, scene_id, line_idx)


def _validate_scene(config: Dict[str, Any], scene: Any, scene_idx: int) -> None:
    if not isinstance(scene, dict):
        raise ValidationError(f"Scene at index {scene_idx} must be a dictionary.")
    scene_id = scene.get("id", f"scene_{scene_idx}")
    _validate_scene_settings(config, scene, scene_id)
    _validate_scene_transition(scene, scene_id)
    _validate_fg_overlays(scene, scene_id)
    _validate_badge(scene, scene_id)
    _validate_badge_definitions_list(
        scene.get("badges"), container_id=f"scene '{scene_id}'", label="badges"
    )
    _validate_top_level_assets(config)
    for line_idx, line in enumerate(_resolve_scene_lines(scene_id, scene)):
        _validate_line(line, scene_id, line_idx)


def validate_script(config: Dict[str, Any], script: Dict[str, Any]) -> None:
    """Validate script-level badges, assets, scenes, and lines."""
    scenes = script.get("scenes")
    if not isinstance(scenes, list):
        raise ValueError("Script must contain a 'scenes' list.")
    _validate_badge_definitions_list(script.get("badges"), container_id="script", label="badges")
    for scene_idx, scene in enumerate(scenes):
        _validate_scene(config, scene, scene_idx)
