from typing import Any, Dict

from ...exceptions import ValidationError
from ..config.io import load_config
from ..config.merge import merge_configs
from ..config.validate import validate_config

__all__ = ["load_script_and_config", "ValidationError"]


def load_script_and_config(script_path: str, default_config_path: str) -> Dict[str, Any]:
    """
    Load the script YAML and merge it with the default configuration.

    Args:
        script_path: Path to the script YAML file.
        default_config_path: Path to the default config YAML file.

    Returns:
        The final, merged configuration.
    """
    # Load default config and script YAML
    default_config = load_config(default_config_path)
    script_data = load_config(script_path)

    # Merge script into the 'script' key of the config
    final_config: Dict[str, Any] = default_config.copy()
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

    # Merge line-level defaults and character overrides
    for scene in final_config.get("script", {}).get("scenes", []):
        for line in scene.get("lines", []):
            current_line_data = line.copy()

            # Start with global defaults (if any)
            merged_line_settings = global_defaults.copy()
            # Avoid deep merging issues with line-specific character lists
            merged_line_settings.pop("characters", None)
            merged_line_settings.pop("voice_layers", None)

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
            if isinstance(current_line_data.get("characters"), list):
                processed_characters = []
                for char_entry in current_line_data["characters"]:
                    char_name = char_entry.get("name")
                    if char_name and char_name in character_defaults:
                        merged_char_entry = merge_configs(
                            character_defaults[char_name], char_entry
                        )
                        processed_characters.append(merged_char_entry)
                    else:
                        processed_characters.append(char_entry)
                merged_line_settings["characters"] = processed_characters

            # Handle concurrent voice layers for simultaneous speech
            voice_layers = current_line_data.get("voice_layers")
            if isinstance(voice_layers, list):
                processed_layers = []
                for layer_entry in voice_layers:
                    if not isinstance(layer_entry, dict):
                        processed_layers.append(layer_entry)
                        continue

                    layer_defaults = global_defaults.copy()
                    layer_defaults.pop("characters", None)
                    layer_defaults.pop("voice_layers", None)

                    layer_speaker = layer_entry.get("speaker_name")
                    if layer_speaker and layer_speaker in character_defaults:
                        layer_defaults = merge_configs(
                            layer_defaults, character_defaults[layer_speaker]
                        )

                    merged_layer = merge_configs(layer_defaults, layer_entry)
                    processed_layers.append(merged_layer)

                merged_line_settings["voice_layers"] = processed_layers

            # Update the original line dictionary with the merged settings
            line.clear()
            line.update(merged_line_settings)

    # Validate the final configuration
    validate_config(final_config)

    return final_config

