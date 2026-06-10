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

    _validate_color_filter_adjust_block(
        color_filter,
        label,
        allow_empty=True,
    )

    targets = color_filter.get("targets")
    if targets is None:
        return
    if not isinstance(targets, list):
        raise ValidationError(f"'{label}.targets' must be a list.")
    for idx, target in enumerate(targets):
        _validate_color_filter_target(target, f"{label}.targets[{idx}]")


def _validate_color_filter_adjust_block(
    adjust: Any,
    label: str,
    *,
    allow_empty: bool,
) -> None:
    if not isinstance(adjust, dict):
        raise ValidationError(f"'{label}' must be a dictionary.")
    known_keys = {"hue", "saturation", "brightness", "targets"}
    if not allow_empty and not any(key in adjust for key in ("hue", "saturation", "brightness")):
        raise ValidationError(
            f"'{label}' must contain at least one of hue, saturation, or brightness."
        )
    for key, minimum, maximum in (
        ("hue", 0.0, 360.0),
        ("saturation", 0.0, None),
        ("brightness", 0.0, None),
    ):
        value = adjust.get(key)
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
    extra_keys = set(adjust.keys()) - known_keys
    if extra_keys:
        extras = ", ".join(sorted(extra_keys))
        raise ValidationError(f"'{label}' contains unsupported keys: {extras}.")


def _validate_color_filter_target(target: Any, label: str) -> None:
    if not isinstance(target, dict):
        raise ValidationError(f"'{label}' must be a dictionary.")

    name = target.get("name")
    if name is not None and (not isinstance(name, str) or not name.strip()):
        raise ValidationError(f"'{label}.name' must be a non-empty string.")

    region = target.get("region")
    if region is None:
        raise ValidationError(f"'{label}.region' is required.")
    _validate_color_filter_region(region, f"{label}.region")

    select_cfg = target.get("select")
    if select_cfg is None:
        raise ValidationError(f"'{label}.select' is required.")
    _validate_color_filter_select(select_cfg, f"{label}.select")

    adjust = target.get("adjust")
    if adjust is None:
        raise ValidationError(f"'{label}.adjust' is required.")
    _validate_color_filter_adjust_block(adjust, f"{label}.adjust", allow_empty=False)


def _validate_color_filter_region(region: Any, label: str) -> None:
    if not isinstance(region, dict):
        raise ValidationError(f"'{label}' must be a dictionary.")

    region_type = region.get("type")
    if not isinstance(region_type, str):
        raise ValidationError(f"'{label}.type' must be a string.")

    if region_type in {"top", "bottom"}:
        ratio = region.get("ratio")
        if isinstance(ratio, bool) or not isinstance(ratio, (int, float)):
            raise ValidationError(f"'{label}.ratio' must be a number.")
        if ratio < 0 or ratio > 1:
            raise ValidationError(f"'{label}.ratio' must be between 0 and 1.")
        return

    if region_type == "rect":
        for key in ("x", "y", "width", "height"):
            value = region.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValidationError(f"'{label}.{key}' must be a number.")
            if value < 0 or value > 1:
                raise ValidationError(f"'{label}.{key}' must be between 0 and 1.")
        if region["width"] <= 0 or region["height"] <= 0:
            raise ValidationError(
                f"'{label}.width' and '{label}.height' must be greater than 0."
            )
        if region["x"] + region["width"] > 1 or region["y"] + region["height"] > 1:
            raise ValidationError(
                f"'{label}' rect must stay within normalized bounds."
            )
        return

    raise ValidationError(
        f"'{label}.type' must be one of 'top', 'bottom', or 'rect'."
    )


def _validate_color_filter_select(select_cfg: Any, label: str) -> None:
    if not isinstance(select_cfg, dict):
        raise ValidationError(f"'{label}' must be a dictionary.")
    color_cfg = select_cfg.get("color")
    if color_cfg is None:
        raise ValidationError(f"'{label}.color' is required.")
    if not isinstance(color_cfg, dict):
        raise ValidationError(f"'{label}.color' must be a dictionary.")

    mode = color_cfg.get("mode")
    if not isinstance(mode, str):
        raise ValidationError(f"'{label}.color.mode' must be a string.")

    if mode == "luma":
        for key in ("min", "max"):
            value = color_cfg.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValidationError(f"'{label}.color.{key}' must be a number.")
            if value < 0 or value > 255:
                raise ValidationError(
                    f"'{label}.color.{key}' must be between 0 and 255."
                )
        if color_cfg["min"] > color_cfg["max"]:
            raise ValidationError(
                f"'{label}.color.min' must be less than or equal to max."
            )
        return

    if mode == "rgb_distance":
        color = color_cfg.get("color")
        if not isinstance(color, str) or not HEX_COLOR_RE.match(color):
            raise ValidationError(
                f"'{label}.color.color' must be a valid hex color string."
            )
        tolerance = color_cfg.get("tolerance")
        if isinstance(tolerance, bool) or not isinstance(tolerance, (int, float)):
            raise ValidationError(f"'{label}.color.tolerance' must be a number.")
        if tolerance < 0:
            raise ValidationError(
                f"'{label}.color.tolerance' must be 0 or greater."
            )
        return

    raise ValidationError(
        f"'{label}.color.mode' must be one of 'luma' or 'rgb_distance'."
    )
