from pathlib import Path
from typing import Any, Dict

import yaml
from yaml import YAMLError

from ..exceptions import ValidationError


def load_config(config_path: str) -> Dict[str, Any]:
    """Loads a YAML configuration file."""
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except YAMLError as e:
        # Extract line and column number if available
        mark = getattr(e, "mark", None)
        line = mark.line + 1 if mark else None
        column = mark.column + 1 if mark else None
        raise ValidationError(
            f"Invalid YAML syntax in {config_path}: {e}",
            line_number=line,
            column_number=column,
        )
    except FileNotFoundError:
        raise ValidationError(f"Configuration file not found: {config_path}")


def merge_configs(base: Dict, override: Dict) -> Dict:
    """
    Recursively merges two dictionaries.
    The `override` dictionary values take precedence.
    """
    merged = base.copy()
    for key, value in override.items():
        if isinstance(value, dict) and key in merged and isinstance(merged[key], dict):
            merged[key] = merge_configs(merged[key], value)
        else:
            merged[key] = value
    return merged


def _validate_config(config: Dict[str, Any]):
    """
    Validates the loaded configuration and script data.
    Raises ValueError if any validation fails.
    """
    script = config.get("script")
    if not isinstance(script, dict):
        raise ValueError("Script data must be a dictionary under the 'script' key.")

    scenes = script.get("scenes")
    if not isinstance(scenes, list):
        raise ValueError("Script must contain a 'scenes' list.")

    # Get character assets path from config or default
    character_assets_path = Path(
        "assets/characters"
    )  # Assuming this is the base path for characters

    for scene_idx, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            raise ValidationError(f"Scene at index {scene_idx} must be a dictionary.")

        scene_id = scene.get(
            "id", f"scene_{scene_idx}"
        )  # Use generated ID for error messages

        if "id" not in scene:
            print(
                f"Warning: Scene at index {scene_idx} has no 'id'. Using '{scene_id}'."
            )

        lines = scene.get("lines")
        if not isinstance(lines, list):
            raise ValidationError(f"Scene '{scene_id}' must contain a 'lines' list.")

        # Validate background image/video path
        bg_path = scene.get("bg", config.get("background", {}).get("default"))
        if bg_path:
            bg_full_path = Path(bg_path)
            if not bg_full_path.exists():
                raise ValidationError(
                    f"Background file '{bg_path}' for scene '{scene_id}' does not exist."
                )
            if not bg_full_path.is_file():
                raise ValidationError(
                    f"Background path '{bg_path}' for scene '{scene_id}' is not a file."
                )

        # Validate BGM path
        bgm_config = scene.get("bgm")
        if bgm_config:
            if not isinstance(bgm_config, dict):
                raise ValidationError(
                    f"BGM configuration for scene '{scene_id}' must be a dictionary."
                )
            bgm_path = bgm_config.get("path")
            if bgm_path:
                bgm_full_path = Path(bgm_path)
                if not bgm_full_path.exists():
                    raise ValidationError(
                        f"BGM file '{bgm_path}' for scene '{scene_id}' does not exist."
                    )
                if not bgm_full_path.is_file():
                    raise ValidationError(
                        f"BGM path '{bgm_path}' for scene '{scene_id}' is not a file."
                    )

            # Validate bgm_volume range (moved from line validation to here)
            bgm_volume = bgm_config.get("volume")
            if bgm_volume is not None:
                if not (0.0 <= bgm_volume <= 1.0):
                    raise ValidationError(
                        f"BGM volume for scene '{scene_id}' must be between 0.0 and 1.0, but got {bgm_volume}."
                    )

        # Validate assets defined in the top-level 'assets' section
        top_level_assets = config.get("assets", {})
        for asset_key, asset_path_str in top_level_assets.items():
            asset_full_path = Path(asset_path_str)
            if not asset_full_path.exists():
                raise ValidationError(
                    f"Asset '{asset_key}' path '{asset_path_str}' does not exist."
                )
            if not asset_full_path.is_file():
                raise ValidationError(
                    f"Asset '{asset_key}' path '{asset_path_str}' is not a file."
                )

        for line_idx, line in enumerate(lines):
            if not isinstance(line, dict):
                raise ValidationError(
                    f"Line at scene '{scene_id}', index {line_idx} must be a dictionary."
                )
            if "text" not in line:
                raise ValidationError(
                    f"Line at scene '{scene_id}', index {line_idx} must contain 'text'."
                )

            # Validate speed range
            speed = line.get("speed")
            if speed is not None:
                if not (0.5 <= speed <= 2.0):
                    raise ValidationError(
                        f"Speech speed for scene '{scene_id}', line {line_idx} must be between 0.5 and 2.0, but got {speed}."
                    )

            # Validate pitch range
            pitch = line.get("pitch")
            if pitch is not None:
                if not (-1.0 <= pitch <= 1.0):
                    raise ValidationError(
                        f"Speech pitch for scene '{scene_id}', line {line_idx} must be between -1.0 and 1.0, but got {pitch}."
                    )

            # Validate speaker_id type
            speaker_id = line.get("speaker_id")
            if speaker_id is not None:
                if not isinstance(speaker_id, int):
                    raise ValidationError(
                        f"Speaker ID for scene '{scene_id}', line {line_idx} must be an integer, but got {type(speaker_id).__name__}."
                    )


def load_script_and_config(
    script_path: str, default_config_path: str
) -> Dict[str, Any]:
    """
    Loads the script YAML and merges it with the default configuration.

    Args:
        script_path (str): Path to the script YAML file.
        default_config_path (str): Path to the default config YAML file.

    Returns:
        Dict[str, Any]: The final, merged configuration.
    """
    # Load default config
    default_config = load_config(default_config_path)

    # Load script
    script_data = load_config(script_path)

    # Merge script into the 'script' key of the config
    final_config = default_config.copy()
    final_config["script"] = script_data

    # Process character speaker IDs
    characters_config = final_config.get("characters", {})
    for scene in final_config["script"].get("scenes", []):
        for line in scene.get("lines", []):
            character_name = line.get("character")
            if character_name and character_name in characters_config:
                character_settings = characters_config[character_name]
                # 1. If voice_style is specified, try to use it first
                voice_style = line.get("voice_style")
                if voice_style:
                    if (
                        "voice_styles" in character_settings
                        and voice_style in character_settings["voice_styles"]
                    ):
                        line["speaker_id"] = character_settings["voice_styles"][
                            voice_style
                        ]
                    else:
                        # If voice_style is specified but not found, log a warning and fall back to default_speaker_id if available
                        print(
                            f"Warning: Voice style '{voice_style}' not found for character '{character_name}'. Falling back to default_speaker_id."
                        )

                # 2. If speaker_id is still not explicitly set in the line, use default from character config
                if "speaker_id" not in line:
                    line["speaker_id"] = character_settings.get("default_speaker_id")

    # Allow script to override defaults
    if "defaults" in script_data:
        final_config = merge_configs(final_config, script_data["defaults"])

    # Validate the final configuration
    _validate_config(final_config)

    return final_config
