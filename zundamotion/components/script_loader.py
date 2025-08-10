from pathlib import Path
from typing import Any, Dict

import yaml


def load_config(config_path: str) -> Dict[str, Any]:
    """Loads a YAML configuration file."""
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


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

    for scene_idx, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            raise ValueError(f"Scene at index {scene_idx} must be a dictionary.")

        scene_id = scene.get(
            "id", f"scene_{scene_idx}"
        )  # Use generated ID for error messages

        if "id" not in scene:
            print(
                f"Warning: Scene at index {scene_idx} has no 'id'. Using '{scene_id}'."
            )

        lines = scene.get("lines")
        if not isinstance(lines, list):
            raise ValueError(f"Scene '{scene_id}' must contain a 'lines' list.")

        # Validate background image/video path
        bg_path = scene.get("bg", config.get("background", {}).get("default"))
        if bg_path and not Path(bg_path).exists():
            raise ValueError(
                f"Background file '{bg_path}' for scene '{scene_id}' does not exist."
            )

        # Validate BGM path
        bgm_path = scene.get("bgm")
        if bgm_path and not Path(bgm_path).exists():
            raise ValueError(
                f"BGM file '{bgm_path}' for scene '{scene_id}' does not exist."
            )

        for line_idx, line in enumerate(lines):
            if not isinstance(line, dict):
                raise ValueError(
                    f"Line at scene '{scene_id}', index {line_idx} must be a dictionary."
                )
            if "text" not in line:
                raise ValueError(
                    f"Line at scene '{scene_id}', index {line_idx} must contain 'text'."
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

    # Allow script to override defaults
    if "defaults" in script_data:
        final_config = merge_configs(final_config, script_data["defaults"])

    # Validate the final configuration
    _validate_config(final_config)

    return final_config
