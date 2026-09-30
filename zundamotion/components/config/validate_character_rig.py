"""Validation for character SVG rig runtime authoring."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from ...exceptions import ValidationError
from ..video.character_rig_validation import validate as validate_rig_file
from ..video.character_rig_resources import resolve_character_rig_resources

_ALLOWED_RIG_KEYS = {"enabled", "path", "raster_width"}
_MAX_RASTER_WIDTH = 4096


def validate_character_rig_config(value: Any, label: str) -> None:
    if value is None:
        return
    if not isinstance(value, Mapping):
        raise ValidationError(f"{label} must be a dictionary.")

    unknown = sorted(set(value) - _ALLOWED_RIG_KEYS)
    if unknown:
        raise ValidationError(
            f"{label} contains unsupported properties: {', '.join(unknown)}."
        )

    enabled = value.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValidationError(f"{label}.enabled must be a boolean.")

    path_value = value.get("path")
    if path_value is not None and (
        not isinstance(path_value, str) or not path_value.strip()
    ):
        raise ValidationError(f"{label}.path must be a non-empty string.")

    raster_width = value.get("raster_width")
    if raster_width is not None:
        if isinstance(raster_width, bool) or not isinstance(raster_width, int):
            raise ValidationError(f"{label}.raster_width must be an integer.")
        if not 1 <= raster_width <= _MAX_RASTER_WIDTH:
            raise ValidationError(
                f"{label}.raster_width must be between 1 and {_MAX_RASTER_WIDTH}."
            )

    if not enabled:
        return
    if path_value is None:
        raise ValidationError(f"{label}.path is required when rig is enabled.")

    resolved = resolve_character_rig_path(path_value, label)

    result = validate_rig_file(resolved)
    if not result.get("valid"):
        errors = result.get("errors") or []
        detail = "; ".join(str(item) for item in errors) or "unknown rig error"
        raise ValidationError(f"{label}.path is not a valid SVG character rig: {detail}")
    resolve_character_rig_resources(resolved)



def resolve_character_rig_path(path_value: str, label: str = "character.rig") -> Path:
    path = Path(path_value)
    if path.is_absolute():
        raise ValidationError(f"{label}.path must be project-relative.")
    try:
        project_root = Path.cwd().resolve()
        resolved = (project_root / path).resolve()
        resolved.relative_to(project_root)
    except (OSError, ValueError) as exc:
        raise ValidationError(
            f"{label}.path must stay inside the project directory."
        ) from exc

    if resolved.suffix.lower() != ".svg":
        raise ValidationError(f"{label}.path must point to an .svg file.")
    if not resolved.exists():
        raise ValidationError(f"{label}.path '{path_value}' does not exist.")
    if not resolved.is_file():
        raise ValidationError(f"{label}.path '{path_value}' is not a file.")
    return resolved
