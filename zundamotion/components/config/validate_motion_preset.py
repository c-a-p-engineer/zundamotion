"""Validation for deterministic character motion presets."""

from __future__ import annotations

import math
from typing import Any, Mapping

from ...exceptions import ValidationError


_SUPPORTED_PRESETS = {"pop", "bounce", "emphasis"}
_ALLOWED_PRESET_MOVE_FIELDS = {
    "enabled",
    "preset",
    "start",
    "duration",
    "intensity",
}


def validate_character_motion_preset(
    character: Mapping[str, Any],
    label: str,
) -> None:
    """Validate the strict preset subpath without changing legacy move rules."""

    move = character.get("move")
    if not isinstance(move, Mapping) or "preset" not in move:
        return

    unknown = sorted(set(move) - _ALLOWED_PRESET_MOVE_FIELDS)
    if unknown:
        raise ValidationError(
            f"{label}.move contains unsupported properties with preset: "
            + ", ".join(unknown)
            + "."
        )

    preset = move.get("preset")
    if not isinstance(preset, str) or preset not in _SUPPORTED_PRESETS:
        raise ValidationError(
            f"{label}.move.preset must be one of bounce, emphasis, pop."
        )

    enabled = move.get("enabled")
    if enabled is not None and not isinstance(enabled, bool):
        raise ValidationError(f"{label}.move.enabled must be a boolean.")

    if "start" in move:
        start = _finite_number(move.get("start"), f"{label}.move.start")
        if start < 0.0:
            raise ValidationError(
                f"{label}.move.start must be greater than or equal to 0."
            )

    if "duration" in move:
        duration = _finite_number(
            move.get("duration"),
            f"{label}.move.duration",
        )
        if duration <= 0.0:
            raise ValidationError(
                f"{label}.move.duration must be greater than 0."
            )

    if "intensity" in move:
        intensity = _finite_number(
            move.get("intensity"),
            f"{label}.move.intensity",
        )
        if not 0.0 <= intensity <= 2.0:
            raise ValidationError(
                f"{label}.move.intensity must be between 0.0 and 2.0."
            )

    if enabled is False:
        return

    if preset in {"pop", "emphasis"}:
        if "scale" not in character:
            raise ValidationError(
                f"{label}.scale is required for {preset} preset."
            )
        scale = _finite_number(character.get("scale"), f"{label}.scale")
        if scale <= 0.0:
            raise ValidationError(f"{label}.scale must be greater than 0.")
        return

    position = character.get("position")
    if not isinstance(position, Mapping) or "y" not in position:
        raise ValidationError(
            f"{label}.position.y is required for bounce preset."
        )
    _finite_number(position.get("y"), f"{label}.position.y")


def _finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise ValidationError(f"{label} must be a finite number.")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{label} must be a finite number.") from exc
    if not math.isfinite(result):
        raise ValidationError(f"{label} must be a finite number.")
    return result
