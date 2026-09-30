"""Deterministic character motion preset expansion.

Preset authoring is sugar for the existing character move/MotionTrack contract.
This module has no renderer side effects and never mutates the authoring input.
"""

from __future__ import annotations

from copy import deepcopy
import math
from typing import Any, Dict, Iterable, List, Mapping

from ....exceptions import ValidationError


SUPPORTED_CHARACTER_MOTION_PRESETS = frozenset(
    {"pop", "bounce", "emphasis"}
)

DEFAULT_PRESET_DURATIONS = {
    "pop": 0.45,
    "bounce": 0.60,
    "emphasis": 0.50,
}


def expand_character_motion_presets(
    characters: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Expand preset moves for one clip without mutating authoring objects."""

    return [expand_character_motion_preset(character) for character in characters]


def expand_character_motion_preset(
    character: Dict[str, Any],
) -> Dict[str, Any]:
    """Return a character config with preset sugar lowered to explicit move."""

    move = character.get("move")
    if not isinstance(move, Mapping) or "preset" not in move:
        return character

    result = deepcopy(character)
    resolved_move = result.get("move")
    assert isinstance(resolved_move, dict)

    preset = _preset_name(resolved_move.get("preset"))
    start = _finite_number(
        resolved_move.get("start", 0.0),
        "move.start",
    )
    if start < 0.0:
        raise ValidationError(
            "Character move.start must be greater than or equal to 0."
        )

    duration = _finite_number(
        resolved_move.get("duration", DEFAULT_PRESET_DURATIONS[preset]),
        "move.duration",
    )
    if duration <= 0.0:
        raise ValidationError(
            "Character move.duration must be greater than 0."
        )

    intensity = _finite_number(
        resolved_move.get("intensity", 1.0),
        "move.intensity",
    )
    if not 0.0 <= intensity <= 2.0:
        raise ValidationError(
            "Character move.intensity must be between 0.0 and 2.0."
        )

    if resolved_move.get("enabled") is False:
        return result

    if preset == "pop":
        synthetic = _pop_move(
            final_scale=_positive_number(
                result.get("scale"),
                "character scale",
            ),
            start=start,
            duration=duration,
            intensity=intensity,
        )
    elif preset == "bounce":
        position = result.get("position")
        if not isinstance(position, Mapping) or "y" not in position:
            raise ValidationError(
                "Character position.y is required for bounce preset."
            )
        synthetic = _bounce_move(
            final_y=_finite_number(
                position.get("y"),
                "character position.y",
            ),
            start=start,
            duration=duration,
            intensity=intensity,
        )
    else:
        synthetic = _emphasis_move(
            final_scale=_positive_number(
                result.get("scale"),
                "character scale",
            ),
            start=start,
            duration=duration,
            intensity=intensity,
        )

    if resolved_move.get("enabled") is True:
        synthetic["enabled"] = True
    result["move"] = synthetic
    return result


def _pop_move(
    *,
    final_scale: float,
    start: float,
    duration: float,
    intensity: float,
) -> Dict[str, Any]:
    return {
        "from": {
            "scale": final_scale * (1.0 - 0.18 * intensity),
        },
        "start": start,
        "duration": duration,
        "easing": "ease_in_out",
        "keyframes": [
            {
                "at": duration * 0.65,
                "scale": final_scale * (1.0 + 0.08 * intensity),
                "easing": "ease_out",
            }
        ],
    }


def _bounce_move(
    *,
    final_y: float,
    start: float,
    duration: float,
    intensity: float,
) -> Dict[str, Any]:
    return {
        "from": {"y": final_y},
        "start": start,
        "duration": duration,
        "easing": "ease_out",
        "keyframes": [
            {
                "at": duration * 0.35,
                "y": final_y - 48.0 * intensity,
                "easing": "ease_out",
            },
            {
                "at": duration * 0.68,
                "y": final_y + 10.0 * intensity,
                "easing": "ease_in_out",
            },
        ],
    }


def _emphasis_move(
    *,
    final_scale: float,
    start: float,
    duration: float,
    intensity: float,
) -> Dict[str, Any]:
    return {
        "from": {"scale": final_scale},
        "start": start,
        "duration": duration,
        "easing": "ease_in_out",
        "keyframes": [
            {
                "at": duration * 0.45,
                "scale": final_scale * (1.0 + 0.12 * intensity),
                "easing": "ease_out",
            }
        ],
    }


def _preset_name(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ValidationError("Character move.preset must be a supported string.")
    if value not in SUPPORTED_CHARACTER_MOTION_PRESETS:
        raise ValidationError(
            "Character move.preset must be one of: "
            + ", ".join(sorted(SUPPORTED_CHARACTER_MOTION_PRESETS))
            + "."
        )
    return value


def _finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise ValidationError(f"Character {label} must be a finite number.")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(
            f"Character {label} must be a finite number."
        ) from exc
    if not math.isfinite(result):
        raise ValidationError(f"Character {label} must be a finite number.")
    return result


def _positive_number(value: Any, label: str) -> float:
    result = _finite_number(value, label)
    if result <= 0.0:
        raise ValidationError(f"Character {label} must be greater than 0.")
    return result
