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


def _validate_fg_overlays(container: Dict[str, Any], container_id: str) -> None:
    """Validate foreground overlay configuration for a scene or line.

    Parameters
    ----------
    container: Dict[str, Any]
        Dictionary potentially containing ``fg_overlays``.
    container_id: str
        Identifier used in error messages (e.g., "scene 'id'" or "scene 'id', line 2").

    Raises
    ------
    ValidationError
        If any foreground overlay entry is invalid.
    """

    fg_overlays = container.get("fg_overlays")
    if fg_overlays is None:
        return

    if not isinstance(fg_overlays, list):
        raise ValidationError(
            f"Foreground overlays for {container_id} must be a list."
        )

    for fg_idx, fg in enumerate(fg_overlays):
        if not isinstance(fg, dict):
            raise ValidationError(
                f"Foreground overlay at {container_id}, index {fg_idx} must be a dictionary."
            )

        fg_id = fg.get("id", f"fg_{fg_idx}")
        src = fg.get("src")
        if not src or not isinstance(src, str):
            raise ValidationError(
                f"Foreground overlay '{fg_id}' in {container_id} must have a string 'src' path."
            )
        src_path = Path(src)
        if not src_path.exists() or not src_path.is_file():
            raise ValidationError(
                f"Foreground overlay '{fg_id}' source file '{src}' not found for {container_id}."
            )

        mode = fg.get("mode")
        if mode not in {"overlay", "blend", "chroma"}:
            raise ValidationError(
                f"Foreground overlay '{fg_id}' in {container_id} has invalid mode '{mode}'."
            )

        if mode == "blend":
            blend_mode = fg.get("blend_mode")
            if blend_mode not in {"screen", "add", "multiply", "lighten"}:
                raise ValidationError(
                    f"Foreground overlay '{fg_id}' in {container_id} requires a valid 'blend_mode'."
                )

        if mode == "chroma":
            chroma = fg.get("chroma")
            if not isinstance(chroma, dict):
                raise ValidationError(
                    f"Foreground overlay '{fg_id}' in {container_id} must have a 'chroma' dictionary."
                )
            key_color = chroma.get("key_color")
            if not isinstance(key_color, str) or not key_color.startswith("#"):
                raise ValidationError(
                    f"Foreground overlay '{fg_id}' in {container_id} has invalid chroma key_color '{key_color}'."
                )
            similarity = chroma.get("similarity", 0.1)
            blend = chroma.get("blend", 0.0)
            if not isinstance(similarity, (int, float)) or not (0.0 <= similarity <= 1.0):
                raise ValidationError(
                    f"Foreground overlay '{fg_id}' in {container_id} chroma similarity must be between 0.0 and 1.0."
                )
            if not isinstance(blend, (int, float)) or not (0.0 <= blend <= 1.0):
                raise ValidationError(
                    f"Foreground overlay '{fg_id}' in {container_id} chroma blend must be between 0.0 and 1.0."
                )

        opacity = fg.get("opacity")
        if opacity is not None and (
            not isinstance(opacity, (int, float)) or not (0.0 <= opacity <= 1.0)
        ):
            raise ValidationError(
                f"Foreground overlay '{fg_id}' in {container_id} opacity must be between 0.0 and 1.0."
            )

        position = fg.get("position", {})
        if not isinstance(position, dict):
            raise ValidationError(
                f"Foreground overlay '{fg_id}' in {container_id} position must be a dictionary."
            )
        for axis in ("x", "y"):
            val = position.get(axis, 0)
            if not isinstance(val, (int, float)):
                raise ValidationError(
                    f"Foreground overlay '{fg_id}' in {container_id} position '{axis}' must be a number."
                )

        scale = fg.get("scale", {})
        if not isinstance(scale, dict):
            raise ValidationError(
                f"Foreground overlay '{fg_id}' in {container_id} scale must be a dictionary."
            )
        for dim in ("w", "h"):
            val = scale.get(dim)
            if val is not None and (not isinstance(val, (int, float)) or val <= 0):
                raise ValidationError(
                    f"Foreground overlay '{fg_id}' in {container_id} scale '{dim}' must be a positive number."
                )
        keep_aspect = scale.get("keep_aspect")
        if keep_aspect is not None and not isinstance(keep_aspect, bool):
            raise ValidationError(
                f"Foreground overlay '{fg_id}' in {container_id} scale 'keep_aspect' must be a boolean."
            )

        timing = fg.get("timing", {})
        if not isinstance(timing, dict):
            raise ValidationError(
                f"Foreground overlay '{fg_id}' in {container_id} timing must be a dictionary."
            )
        start = timing.get("start", 0.0)
        if not isinstance(start, (int, float)) or start < 0:
            raise ValidationError(
                f"Foreground overlay '{fg_id}' in {container_id} timing start must be non-negative."
            )
        duration = timing.get("duration")
        if duration is not None and (
            not isinstance(duration, (int, float)) or duration <= 0
        ):
            raise ValidationError(
                f"Foreground overlay '{fg_id}' in {container_id} timing duration must be positive."
            )
        loop = timing.get("loop")
        if loop is not None and not isinstance(loop, bool):
            raise ValidationError(
                f"Foreground overlay '{fg_id}' in {container_id} timing loop must be a boolean."
            )

        fps = fg.get("fps")
        if fps is not None and (not isinstance(fps, int) or fps <= 0):
            raise ValidationError(
                f"Foreground overlay '{fg_id}' in {container_id} fps must be a positive integer."
            )


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

        # Validate scene transition
        transition_config = scene.get("transition")
        if transition_config:
            if not isinstance(transition_config, dict):
                raise ValidationError(
                    f"Transition configuration for scene '{scene_id}' must be a dictionary."
                )
            transition_type = transition_config.get("type")
            if not transition_type:
                raise ValidationError(
                    f"Transition for scene '{scene_id}' must have a 'type'."
                )
            if not isinstance(transition_type, str):
                raise ValidationError(
                    f"Transition type for scene '{scene_id}' must be a string, but got {type(transition_type).__name__}."
                )

            transition_duration = transition_config.get("duration")
            if transition_duration is None:
                raise ValidationError(
                    f"Transition for scene '{scene_id}' must have a 'duration'."
                )
            if not isinstance(transition_duration, (int, float)):
                raise ValidationError(
                    f"Transition duration for scene '{scene_id}' must be a number, but got {type(transition_duration).__name__}."
                )
            if transition_duration <= 0:
                raise ValidationError(
                    f"Transition duration for scene '{scene_id}' must be positive, but got {transition_duration}."
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

        # Validate foreground overlays
        _validate_fg_overlays(scene, scene_id)

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

            _validate_fg_overlays(line, f"scene '{scene_id}', line {line_idx}")

            # 'text' or 'wait' key must exist
            if "text" not in line and "wait" not in line:
                raise ValidationError(
                    f"Line at scene '{scene_id}', index {line_idx} must contain 'text' or 'wait'."
                )

            if "text" in line and "wait" in line:
                raise ValidationError(
                    f"Line at scene '{scene_id}', index {line_idx} cannot contain both 'text' and 'wait'."
                )

            if "wait" in line:
                wait_value = line["wait"]
                if isinstance(wait_value, (int, float)):
                    if wait_value <= 0:
                        raise ValidationError(
                            f"Wait duration for scene '{scene_id}', line {line_idx} must be positive, but got {wait_value}."
                        )
                elif isinstance(wait_value, dict):
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
                else:
                    raise ValidationError(
                        f"Wait value for scene '{scene_id}', line {line_idx} must be a number or a dictionary."
                    )
                continue  # Skip other validations for wait steps

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

            # Validate sound_effects
            sound_effects = line.get("sound_effects")
            if sound_effects:
                if not isinstance(sound_effects, list):
                    raise ValidationError(
                        f"Sound effects for scene '{scene_id}', line {line_idx} must be a list."
                    )
                for se_idx, se in enumerate(sound_effects):
                    if not isinstance(se, dict):
                        raise ValidationError(
                            f"Sound effect at scene '{scene_id}', line {line_idx}, index {se_idx} must be a dictionary."
                        )
                    se_path = se.get("path")
                    if not se_path:
                        raise ValidationError(
                            f"Sound effect at scene '{scene_id}', line {line_idx}, index {se_idx} must have a 'path'."
                        )
                    se_full_path = Path(se_path)
                    if not se_full_path.exists():
                        raise ValidationError(
                            f"Sound effect file '{se_path}' for scene '{scene_id}', line {line_idx}, index {se_idx} does not exist."
                        )
                    if not se_full_path.is_file():
                        raise ValidationError(
                            f"Sound effect path '{se_path}' for scene '{scene_id}', line {line_idx}, index {se_idx} is not a file."
                        )

                    se_start_time = se.get("start_time", 0.0)
                    if not isinstance(se_start_time, (int, float)):
                        raise ValidationError(
                            f"Sound effect start_time for scene '{scene_id}', line {line_idx}, index {se_idx} must be a number, but got {type(se_start_time).__name__}."
                        )
                    if se_start_time < 0:
                        raise ValidationError(
                            f"Sound effect start_time for scene '{scene_id}', line {line_idx}, index {se_idx} must be non-negative, but got {se_start_time}."
                        )

                    se_volume = se.get("volume", 1.0)
                    if not isinstance(se_volume, (int, float)):
                        raise ValidationError(
                            f"Sound effect volume for scene '{scene_id}', line {line_idx}, index {se_idx} must be a number, but got {type(se_volume).__name__}."
                        )
                    if not (0.0 <= se_volume <= 1.0):
                        raise ValidationError(
                            f"Sound effect volume for scene '{scene_id}', line {line_idx}, index {se_idx} must be between 0.0 and 1.0, but got {se_volume}."
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

    # Allow script's top-level defaults to override default_config's defaults
    if "defaults" in script_data:
        final_config["defaults"] = merge_configs(
            final_config.get("defaults", {}), script_data["defaults"]
        )

    # Allow selected top-level sections in script to override global config
    # e.g., subtitle settings (reading_display), video params, bgm defaults, etc.
    for top_key in ("video", "subtitle", "bgm", "background", "system"):
        if top_key in script_data and isinstance(script_data[top_key], dict):
            final_config[top_key] = merge_configs(
                final_config.get(top_key, {}), script_data[top_key]
            )

    # Extract defaults for easier access
    global_defaults = final_config.get("defaults", {})
    character_defaults = global_defaults.get("characters", {})

    for scene in final_config["script"].get("scenes", []):
        for line_idx, line in enumerate(scene.get("lines", [])):
            # Initialize merged_line with a copy of the current line to preserve its original structure
            current_line_data = line.copy()

            # Start with global defaults (if any)
            merged_line_settings = global_defaults.copy()
            # Remove 'characters' from global_defaults to avoid deep merging issues with line-specific character lists
            merged_line_settings.pop("characters", None)

            speaker_name = current_line_data.get("speaker_name")
            if speaker_name and speaker_name in character_defaults:
                # Apply character-specific defaults
                merged_line_settings = merge_configs(
                    merged_line_settings, character_defaults[speaker_name]
                )

            # Apply line-specific settings, overriding previous defaults
            merged_line_settings = merge_configs(
                merged_line_settings, current_line_data
            )

            # Handle character-specific settings within the 'characters' list in the line
            if "characters" in current_line_data and isinstance(
                current_line_data["characters"], list
            ):
                processed_characters = []
                for char_entry in current_line_data["characters"]:
                    char_name = char_entry.get("name")
                    if char_name and char_name in character_defaults:
                        # Merge character defaults into the specific character entry
                        merged_char_entry = merge_configs(
                            character_defaults[char_name], char_entry
                        )
                        processed_characters.append(merged_char_entry)
                    else:
                        processed_characters.append(char_entry)
                merged_line_settings["characters"] = processed_characters

            # Update the original line dictionary with the merged settings
            line.clear()
            line.update(merged_line_settings)

    # Validate the final configuration
    _validate_config(final_config)

    return final_config
