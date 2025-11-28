"""Utility helpers for resolving subtitle overlay effects."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

from zundamotion.plugins.loader import builtin_plugin_paths, load_plugins_cached
from zundamotion.plugins.schema import SOURCE_PRIORITY
from ...utils.logger import logger


@dataclass
class SubtitleEffectSnippet:
    """Result of resolving text-specific effects for subtitle overlays."""

    filter_chain: List[str]
    output_label: str
    overlay_kwargs: Dict[str, str]
    dynamic: bool = False


@dataclass(frozen=True)
class SubtitleEffectContext:
    """Context shared with subtitle effect builders."""

    input_label: str
    base_x_expr: str
    base_y_expr: str
    duration: float
    width: int
    height: int
    index: int
    effect_index: int


SubtitleEffectBuilder = Callable[[SubtitleEffectContext, Dict[str, Any]], Optional[SubtitleEffectSnippet]]


@dataclass(frozen=True)
class SubtitleEffectSpec:
    """Effect registration entry."""

    name: str
    builder: SubtitleEffectBuilder
    source: str
    version: str
    aliases: tuple[str, ...]


_EFFECT_REGISTRY: Dict[str, SubtitleEffectSpec] = {}


def register_subtitle_effect(
    name: str,
    builder: SubtitleEffectBuilder,
    *,
    aliases: Sequence[str] | None = None,
    source: str = "builtin",
    version: str = "0.0.0",
    enabled: bool = True,
) -> None:
    """Register a subtitle effect builder under a canonical name and optional aliases."""

    if not enabled:
        return

    aliases = tuple(aliases or [])
    spec = SubtitleEffectSpec(
        name=name,
        builder=builder,
        source=source,
        version=version,
        aliases=aliases,
    )
    for key in (name, *aliases):
        existing = _EFFECT_REGISTRY.get(key)
        if existing and _source_priority(existing.source) > _source_priority(source):
            continue
        _EFFECT_REGISTRY[key] = spec


def resolve_subtitle_effects(
    *,
    effects: Optional[Iterable[Any]],
    input_label: str,
    base_x_expr: str,
    base_y_expr: str,
    duration: float,
    width: int,
    height: int,
    index: int,
) -> Optional[SubtitleEffectSnippet]:
    """Resolve configured subtitle effects into FFmpeg filter fragments."""

    if not effects:
        return None

    _ensure_registry_populated()

    filter_chain: List[str] = []
    current_label = input_label
    current_x = base_x_expr
    current_y = base_y_expr
    dynamic = False

    for effect_index, raw in enumerate(effects, start=1):
        effect = _normalize_effect(raw)
        if not effect:
            continue

        effect_type = effect.pop("type")
        spec = _EFFECT_REGISTRY.get(effect_type)
        if not spec:
            logger.warning("[SubtitleEffects] Unsupported effect type: %s", effect_type)
            continue

        context = SubtitleEffectContext(
            input_label=current_label,
            base_x_expr=current_x,
            base_y_expr=current_y,
            duration=duration,
            width=width,
            height=height,
            index=index,
            effect_index=effect_index,
        )

        try:
            snippet = spec.builder(context, effect)
        except Exception as exc:  # noqa: BLE001 - log and continue
            logger.warning(
                "[SubtitleEffects] Failed to build effect type=%s params=%s err=%s",
                effect_type,
                effect,
                exc,
            )
            continue

        if not snippet:
            continue

        if snippet.filter_chain:
            filter_chain.extend(snippet.filter_chain)
        if "x" in snippet.overlay_kwargs:
            current_x = snippet.overlay_kwargs["x"]
        if "y" in snippet.overlay_kwargs:
            current_y = snippet.overlay_kwargs["y"]
        current_label = snippet.output_label
        dynamic = dynamic or snippet.dynamic

    overlay_kwargs: Dict[str, str] = {}
    if current_x != base_x_expr:
        overlay_kwargs["x"] = current_x
    if current_y != base_y_expr:
        overlay_kwargs["y"] = current_y

    if not filter_chain and not overlay_kwargs:
        return None

    return SubtitleEffectSnippet(
        filter_chain=filter_chain,
        output_label=current_label,
        overlay_kwargs=overlay_kwargs,
        dynamic=dynamic,
    )


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
        if plugin.meta.kind != "subtitle":
            continue
        aliases = plugin.aliases
        for effect_id, builder in plugin.builders.items():
            register_subtitle_effect(
                effect_id,
                builder,
                aliases=aliases.get(effect_id, ()),
                source=plugin.meta.source,
                version=plugin.meta.version,
                enabled=plugin.meta.enabled,
            )


def reset_subtitle_effect_registry() -> None:
    _EFFECT_REGISTRY.clear()


def _source_priority(source: str) -> int:
    return SOURCE_PRIORITY.get(source, 0)


# Populate registry at import time for immediate availability.
_ensure_registry_populated()


__all__ = [
    "resolve_subtitle_effects",
    "register_subtitle_effect",
    "SubtitleEffectSpec",
    "SubtitleEffectSnippet",
    "reset_subtitle_effect_registry",
]
