"""Badge configuration validation."""

from typing import Any, Dict

from ...exceptions import ValidationError
from .validate_common import BADGE_POSITION_CHOICES, is_valid_color_string


def _validate_badge(container: Dict[str, Any], container_id: str) -> None:
    badge = container.get("badge")
    if badge is None:
        return
    if not isinstance(badge, dict):
        raise ValidationError(f"Badge for {container_id} must be a dictionary.")

    text = badge.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ValidationError(
            f"Badge for {container_id} must have a non-empty string 'text'."
        )

    position = badge.get("position")
    if not isinstance(position, str) or position not in BADGE_POSITION_CHOICES:
        raise ValidationError(
            f"Badge position for {container_id} must be one of {sorted(BADGE_POSITION_CHOICES)}."
        )
    _validate_badge_text_style(badge, container_id)
    _validate_badge_background(badge.get("background"), container_id)
    _validate_badge_timing(badge.get("timing"), container_id)


def _validate_badge_text_style(badge: Dict[str, Any], container_id: str) -> None:
    font_size = badge.get("font_size")
    if font_size is not None and (
        not isinstance(font_size, (int, float)) or float(font_size) <= 0
    ):
        raise ValidationError(
            f"Badge font_size for {container_id} must be a positive number."
        )
    for key in ("font_color", "stroke_color"):
        value = badge.get(key)
        if value is not None and (
            not isinstance(value, str) or not is_valid_color_string(value)
        ):
            raise ValidationError(
                f"Badge {key} for {container_id} must be a valid color string."
            )
    stroke_width = badge.get("stroke_width")
    if stroke_width is not None and (
        not isinstance(stroke_width, (int, float)) or float(stroke_width) < 0
    ):
        raise ValidationError(
            f"Badge stroke_width for {container_id} must be a non-negative number."
        )
    for key in ("min_width", "max_width"):
        value = badge.get(key)
        if value is not None and (
            not isinstance(value, (int, float)) or float(value) <= 0
        ):
            raise ValidationError(
                f"Badge {key} for {container_id} must be a positive number."
            )
    text_align = badge.get("text_align")
    if text_align is not None and str(text_align).strip().lower() not in {
        "left",
        "center",
        "right",
    }:
        raise ValidationError(
            f"Badge text_align for {container_id} must be one of ['center', 'left', 'right']."
        )


def _validate_badge_background(background: Any, container_id: str) -> None:
    if background is None:
        return
    if not isinstance(background, dict):
        raise ValidationError(f"Badge background for {container_id} must be a dictionary.")
    for key in ("color", "border_color"):
        value = background.get(key)
        if value is not None and (
            not isinstance(value, str) or not is_valid_color_string(value)
        ):
            raise ValidationError(
                f"Badge background.{key} for {container_id} must be a valid color string."
            )
    for key in ("opacity", "border_opacity"):
        value = background.get(key)
        if value is not None and (
            not isinstance(value, (int, float)) or not (0.0 <= float(value) <= 1.0)
        ):
            raise ValidationError(
                f"Badge background.{key} for {container_id} must be between 0.0 and 1.0."
            )
    for key in ("radius", "border_width"):
        value = background.get(key)
        if value is not None and (
            not isinstance(value, (int, float)) or float(value) < 0
        ):
            raise ValidationError(
                f"Badge background.{key} for {container_id} must be a non-negative number."
            )


def _validate_badge_timing(timing: Any, container_id: str) -> None:
    if timing is None:
        return
    if not isinstance(timing, dict):
        raise ValidationError(f"Badge timing for {container_id} must be a dictionary.")
    start = timing.get("start", 0.0)
    if not isinstance(start, (int, float)) or float(start) < 0:
        raise ValidationError(
            f"Badge timing.start for {container_id} must be a non-negative number."
        )
    end = timing.get("end")
    if end is not None and (
        not isinstance(end, (int, float)) or float(end) <= float(start)
    ):
        raise ValidationError(
            f"Badge timing.end for {container_id} must be greater than timing.start."
        )
    for key in ("show_on_line", "hide_on_line"):
        _validate_badge_line_marker(timing.get(key), key, container_id)


def _validate_badge_line_marker(value: Any, key: str, container_id: str) -> None:
    if value is None or (isinstance(value, str) and value.strip()):
        return
    if isinstance(value, int) and value > 0:
        return
    if isinstance(value, int):
        raise ValidationError(
            f"Badge timing.{key} for {container_id} must be a positive line number."
        )
    raise ValidationError(
        f"Badge timing.{key} for {container_id} must be a positive integer or line id string."
    )


def _validate_badge_definition(badge: Dict[str, Any], container_id: str) -> None:
    if not isinstance(badge, dict):
        raise ValidationError(f"Badge definition for {container_id} must be a dictionary.")
    badge_id = badge.get("id")
    if not isinstance(badge_id, str) or not badge_id.strip():
        raise ValidationError(f"Badge definition for {container_id} requires a non-empty string 'id'.")
    _validate_badge({"badge": badge}, container_id)
    visible = badge.get("visible")
    if visible is not None and not isinstance(visible, bool):
        raise ValidationError(f"Badge definition visible for {container_id} must be a boolean.")


def _validate_badge_definitions_list(
    badges: Any,
    *,
    container_id: str,
    label: str,
) -> None:
    if badges is None:
        return
    if not isinstance(badges, list):
        raise ValidationError(f"{label} for {container_id} must be a list.")
    seen_ids = set()
    for badge_idx, badge in enumerate(badges):
        _validate_badge_definition(
            badge,
            f"{container_id}, {label}[{badge_idx}]",
        )
        badge_id = str(badge.get("id")).strip()
        if badge_id in seen_ids:
            raise ValidationError(
                f"{label} for {container_id} contains duplicate badge id '{badge_id}'."
            )
        seen_ids.add(badge_id)


def _validate_badge_update(badge: Dict[str, Any], container_id: str) -> None:
    if not isinstance(badge, dict):
        raise ValidationError(f"Badge update for {container_id} must be a dictionary.")
    badge_id = badge.get("id")
    visible = badge.get("visible")
    if visible is not None and not isinstance(visible, bool):
        raise ValidationError(f"Badge update visible for {container_id} must be a boolean.")
    if not badge_id:
        merged = {
            "badge": {
                "text": badge.get("text"),
                "position": badge.get("position"),
                **{k: v for k, v in badge.items() if k != "visible"},
            }
        }
        _validate_badge(merged, container_id)
        return
    if not isinstance(badge_id, str) or not badge_id.strip():
        raise ValidationError(f"Badge update for {container_id} requires a non-empty string 'id'.")
    # Allow full badge-style overrides on updates, but don't require text/position.
    if any(
        key in badge
        for key in {
            "text",
            "position",
            "font_size",
            "font_color",
            "stroke_color",
            "stroke_width",
            "min_width",
            "max_width",
            "text_align",
            "background",
            "timing",
        }
    ):
        merged = {
            "badge": {
                "text": badge.get("text", "placeholder"),
                "position": badge.get("position", "top-right"),
                **{k: v for k, v in badge.items() if k != "id" and k != "visible"},
            }
        }
        _validate_badge(merged, container_id)
