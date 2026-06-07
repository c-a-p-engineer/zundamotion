"""Background configuration validation."""

from pathlib import Path
from typing import Any, Dict

from ...exceptions import ValidationError
from .validate_common import ANCHOR_CHOICES, BACKGROUND_FIT_CHOICES, is_valid_color_string


def _validate_background_options(
    cfg: Dict[str, Any], container_id: str
) -> None:
    bg_path = cfg.get("path")
    if bg_path is not None:
        if not isinstance(bg_path, str):
            raise ValidationError(
                f"Background path for {container_id} must be a string."
            )
        resolved = Path(bg_path)
        if not resolved.exists() or not resolved.is_file():
            raise ValidationError(
                f"Background path '{bg_path}' not found for {container_id}."
            )

    fit = cfg.get("fit")
    if fit is not None:
        if not isinstance(fit, str):
            raise ValidationError(
                f"Background fit for {container_id} must be a string."
            )
        if fit.lower() not in BACKGROUND_FIT_CHOICES:
            raise ValidationError(
                f"Background fit for {container_id} must be one of {sorted(BACKGROUND_FIT_CHOICES)}."
            )

    fill_color = cfg.get("fill_color")
    if fill_color is not None:
        if not isinstance(fill_color, str) or not is_valid_color_string(fill_color):
            raise ValidationError(
                f"Background fill_color for {container_id} must be a valid color string."
            )

    anchor = cfg.get("anchor")
    if anchor is not None:
        if not isinstance(anchor, str) or anchor not in ANCHOR_CHOICES:
            raise ValidationError(
                f"Background anchor for {container_id} must be one of {sorted(ANCHOR_CHOICES)}."
            )

    position = cfg.get("position")
    if position is not None:
        if not isinstance(position, dict):
            raise ValidationError(
                f"Background position for {container_id} must be a dictionary."
            )
        for axis in ("x", "y"):
            val = position.get(axis)
            if val is None:
                continue
            if not isinstance(val, (int, float, str)):
                raise ValidationError(
                    f"Background position '{axis}' for {container_id} must be a number or string expression."
                )
