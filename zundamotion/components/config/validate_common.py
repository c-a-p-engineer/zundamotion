"""Shared constants and value checks for configuration validation."""

import re
from typing import Any

from ...exceptions import ValidationError

BACKGROUND_FIT_CHOICES = {
    "stretch",
    "contain",
    "cover",
    "fit_width",
    "fit_height",
}

ANCHOR_CHOICES = {
    "top_left",
    "top_center",
    "top_right",
    "middle_left",
    "middle_center",
    "middle_right",
    "bottom_left",
    "bottom_center",
    "bottom_right",
}

IMAGE_LAYER_TRANSITION_TYPES = {
    "fade",
    "none",
}
BADGE_POSITION_CHOICES = {
    "top-left",
    "top-center",
    "top-right",
    "bottom-left",
    "bottom-center",
    "bottom-right",
}

HEX_COLOR_RE = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
RGB_COLOR_RE = re.compile(r"^rgba?\(.*\)$", re.IGNORECASE)
HSL_COLOR_RE = re.compile(r"^hsla?\(.*\)$", re.IGNORECASE)


def is_valid_color_string(value: str) -> bool:
    if HEX_COLOR_RE.match(value):
        return True
    if RGB_COLOR_RE.match(value) or HSL_COLOR_RE.match(value):
        return True
    if value.lower().startswith("0x"):
        try:
            int(value[2:], 16)
            return True
        except ValueError:
            return False
    if value.isalpha():
        return True
    return False


def validate_character_color_filter(color_filter: Any, label: str) -> None:
    """Validate a character color_filter mapping."""
    if color_filter is None:
        return
    if not isinstance(color_filter, dict):
        raise ValidationError(f"'{label}' must be a dictionary.")
    for key, minimum, maximum in (
        ("hue", 0.0, 360.0),
        ("saturation", 0.0, None),
        ("brightness", 0.0, None),
    ):
        value = color_filter.get(key)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValidationError(f"'{label}.{key}' must be a number.")
        if value < minimum or (maximum is not None and value > maximum):
            if maximum is None:
                raise ValidationError(f"'{label}.{key}' must be 0 or greater.")
            raise ValidationError(
                f"'{label}.{key}' must be between {minimum:g} and {maximum:g}."
            )
