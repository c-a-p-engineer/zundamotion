from typing import Any, Dict

import yaml
from yaml import YAMLError

from ..exceptions import ValidationError


def load_config(config_path: str) -> Dict[str, Any]:
    """Load a YAML configuration file with friendly validation errors.

    Parameters
    ----------
    config_path: str
        Path to a YAML file (UTF-8).

    Returns
    -------
    Dict[str, Any]

    Raises
    ------
    ValidationError
        When the file is not found or the YAML syntax is invalid.
    """
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except YAMLError as e:
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

