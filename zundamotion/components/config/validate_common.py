"""Shared constants and value checks for configuration validation."""

import re



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
