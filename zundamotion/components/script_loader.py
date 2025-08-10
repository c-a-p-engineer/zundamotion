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

    return final_config
