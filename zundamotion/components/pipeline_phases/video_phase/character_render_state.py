"""Canonical character render state used by cache keys and static overlays."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from ...video.character_image_resolver import CharacterImageResolver
from ...video.clip.characters import (
    is_horizontal_flip_enabled,
    is_vertical_flip_enabled,
)
from ...video.image_color_filter_cache import ImageColorFilterCache


SCENE_STATE_RESOLUTION_VERSION = "20260717_scene_state_v2"


def _number(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _offset(value: Any) -> str:
    try:
        return format(float(value), ".12g")
    except (TypeError, ValueError):
        return "0" if value is None else str(value)


def _normalize_color_filter(value: Any) -> Any:
    if value is None:
        return None
    if not isinstance(value, dict):
        return value
    try:
        return ImageColorFilterCache._normalize_color_filter(value)
    except (KeyError, TypeError, ValueError):
        return value


def _has_dynamic_position(position: Dict[str, Any]) -> bool:
    for value in position.values():
        if isinstance(value, str) and "t" in value.lower():
            return True
    return False


def resolve_character_render_state(
    character: Dict[str, Any],
    character_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Resolve defaults, asset identity, transforms, and dynamic behavior once."""

    defaults = character_config or {}
    name = str(character.get("name") or "")
    asset_name = str(character.get("asset_name") or name)
    expression = str(character.get("expression") or "default")
    position_raw = character.get("position")
    if not isinstance(position_raw, dict):
        position_raw = {}
    position = {
        "x": _offset(position_raw.get("x", "0")),
        "y": _offset(position_raw.get("y", "0")),
    }
    source_path = CharacterImageResolver.resolve_base_image(asset_name, expression)
    move = character.get("move")
    move_enabled = bool(move)
    if isinstance(move, dict) and move.get("enabled") is False:
        move_enabled = False
    dynamic = bool(
        move_enabled
        or character.get("enter")
        or character.get("leave")
        or character.get("effects")
        or character.get("effect")
        or character.get("dynamic_scale")
        or character.get("dynamic_position")
        or _has_dynamic_position(position)
    )
    return {
        "name": name,
        "asset_name": asset_name,
        "expression": expression,
        "visible": bool(character.get("visible", False)),
        "scale": _number(character.get("scale", defaults.get("default_scale", 1.0)), 1.0),
        "anchor": str(
            character.get("anchor", defaults.get("default_anchor", "bottom_center"))
        ).lower(),
        "position": position,
        "flip_x": is_horizontal_flip_enabled(character),
        "flip_y": is_vertical_flip_enabled(character),
        "color_filter": _normalize_color_filter(character.get("color_filter")),
        "z": int(_number(character.get("z", 0), 0.0)),
        "image_path": source_path.resolve() if source_path is not None else None,
        "dynamic": dynamic,
    }


def character_state_fingerprint(state: Dict[str, Any]) -> Dict[str, Any]:
    """Return the cache-relevant portion of a resolved character state."""

    return {
        key: state.get(key)
        for key in (
            "name",
            "asset_name",
            "expression",
            "visible",
            "scale",
            "anchor",
            "position",
            "flip_x",
            "flip_y",
            "color_filter",
            "z",
            "image_path",
            "dynamic",
        )
    }


def is_static_character_state(state: Dict[str, Any]) -> bool:
    """Return whether the state can be safely baked into a scene base."""

    return bool(
        state.get("visible")
        and state.get("image_path")
        and not state.get("dynamic")
        # Filtered PNG resolution is asynchronous; keep it on the per-line path.
        and state.get("color_filter") is None
    )


def static_character_entry(
    character: Dict[str, Any],
    character_config: Optional[Dict[str, Any]] = None,
) -> Optional[Tuple[str, Dict[str, Any]]]:
    """Build a stable key and overlay payload for a static character."""

    state = resolve_character_render_state(character, character_config)
    if not is_static_character_state(state):
        return None
    fingerprint = character_state_fingerprint(state)
    key = json.dumps(fingerprint, sort_keys=True, ensure_ascii=False, default=str)
    return key, {
        "path": str(Path(state["image_path"])),
        "scale": state["scale"],
        "anchor": state["anchor"],
        "position": dict(state["position"]),
        "z": state["z"],
    }
