"""Registry-driven overlay effect resolution for FFmpeg filter chains."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

from zundamotion.utils.logger import logger
from zundamotion.plugins.loader import builtin_plugin_paths, load_plugins_cached
from zundamotion.plugins.schema import SOURCE_PRIORITY


OverlayEffectBuilder = Callable[[Dict[str, Any]], Optional[List[str]]]


@dataclass(frozen=True)
class OverlayEffectSpec:
    """Effect registration entry."""

    name: str
    builder: OverlayEffectBuilder
    source: str
    version: str
    aliases: tuple[str, ...]


_EFFECT_REGISTRY: Dict[str, OverlayEffectSpec] = {}


def register_overlay_effect(
    name: str,
    builder: OverlayEffectBuilder,
    *,
    aliases: Sequence[str] | None = None,
    source: str = "builtin",
    version: str = "0.0.0",
    enabled: bool = True,
) -> None:
    """Register an overlay effect builder under a canonical name and optional aliases."""

    if not enabled:
        return

    aliases = tuple(aliases or [])
    spec = OverlayEffectSpec(name=name, builder=builder, source=source, version=version, aliases=aliases)
    keys = (name, *aliases)
    for key in keys:
        existing = _EFFECT_REGISTRY.get(key)
        if existing and _source_priority(existing.source) > _source_priority(source):
            continue
        _EFFECT_REGISTRY[key] = spec


def resolve_overlay_effects(effects: Optional[Iterable[Any]]) -> List[str]:
    """Translate overlay effects into FFmpeg filter strings, preserving order."""

    if not effects:
        return []

    _ensure_registry_populated()

    filters: List[str] = []
    for raw in effects:
        effect = _normalize_effect(raw)
        if not effect:
            continue

        effect_type = effect.pop("type")
        spec = _EFFECT_REGISTRY.get(effect_type)
        if not spec:
            logger.warning("[Effects] Unsupported overlay effect type: %s", effect_type)
            continue

        try:
            built = spec.builder(effect)
        except Exception as exc:  # noqa: BLE001 - log and continue
            logger.warning(
                "[Effects] Failed to build overlay effect type=%s params=%s err=%s",
                effect_type,
                effect,
                exc,
            )
            continue

        if built:
            filters.extend(built)

    return filters


def _normalize_effect(raw: Any) -> Optional[Dict[str, Any]]:
    if isinstance(raw, str):
        et = raw.strip().lower()
        return {"type": et} if et else None
    if not isinstance(raw, dict):
        return None
    effect_type = raw.get("type")
    if not isinstance(effect_type, str) or not effect_type.strip():
        return None
    normalized = {k: v for k, v in raw.items() if v is not None}
    normalized["type"] = effect_type.strip().lower()
    return normalized


def _ensure_registry_populated() -> None:
    if _EFFECT_REGISTRY:
        return
    for plugin in load_plugins_cached(builtin_plugin_paths(), use_cache=True):
        if plugin.meta.kind != "overlay":
            continue
        aliases = plugin.aliases
        for effect_id, builder in plugin.builders.items():
            register_overlay_effect(
                effect_id,
                builder,
                aliases=aliases.get(effect_id, ()),
                source=plugin.meta.source,
                version=plugin.meta.version,
                enabled=plugin.meta.enabled,
            )


def reset_overlay_effect_registry() -> None:
    """Clear registry (for tests)."""

    _EFFECT_REGISTRY.clear()


def _source_priority(source: str) -> int:
    return SOURCE_PRIORITY.get(source, 0)


# Populate registry at import time for immediate availability.
_ensure_registry_populated()


__all__ = [
    "resolve_overlay_effects",
    "register_overlay_effect",
    "OverlayEffectSpec",
    "reset_overlay_effect_registry",
]
