"""Plugin initialization entrypoints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence

from zundamotion.utils.logger import logger

from .loader import PluginLoadResult, default_plugin_paths, load_plugins_cached


@dataclass(frozen=True)
class PluginSettings:
    enabled: bool = True
    paths: Sequence[str] = ()
    allow: Sequence[str] = ()
    deny: Sequence[str] = ()


def initialize_plugins(
    *,
    config: dict,
    cli_paths: Optional[Sequence[str]] = None,
    allow_ids: Optional[Iterable[str]] = None,
    deny_ids: Optional[Iterable[str]] = None,
) -> None:
    """Discover plugins and register builders into effect registries."""

    plugin_cfg = _extract_settings(config, cli_paths, allow_ids, deny_ids)
    if not plugin_cfg.enabled:
        logger.info("[PluginLoader] Plugin system disabled; using built-in registry only")
        return

    roots = default_plugin_paths(plugin_cfg.paths)
    use_cache = not (plugin_cfg.paths or plugin_cfg.allow or plugin_cfg.deny)
    resolved = load_plugins_cached(
        roots,
        allow=plugin_cfg.allow,
        deny=plugin_cfg.deny,
        use_cache=use_cache,
    )

    if not resolved:
        return

    _register_overlay_plugins(resolved)
    _register_subtitle_plugins(resolved)


def _extract_settings(
    config: dict,
    cli_paths: Optional[Sequence[str]],
    allow_ids: Optional[Iterable[str]],
    deny_ids: Optional[Iterable[str]],
) -> PluginSettings:
    plugins_cfg = config.get("plugins", {}) or {}
    enabled = plugins_cfg.get("enabled", True)
    cfg_paths = plugins_cfg.get("paths") or []
    cfg_allow = plugins_cfg.get("allow") or []
    cfg_deny = plugins_cfg.get("deny") or []

    paths = list(cfg_paths)
    if cli_paths:
        paths.extend(cli_paths)

    allow_set = list(cfg_allow)
    if allow_ids:
        allow_set.extend(list(allow_ids))

    deny_set = list(cfg_deny)
    if deny_ids:
        deny_set.extend(list(deny_ids))

    return PluginSettings(
        enabled=bool(enabled),
        paths=tuple(paths),
        allow=tuple(allow_set),
        deny=tuple(deny_set),
    )


def _register_overlay_plugins(plugins: List[PluginLoadResult]) -> None:
    from zundamotion.components.video.overlay_effects import register_overlay_effect

    for plugin in plugins:
        meta = plugin.meta
        if meta.kind != "overlay" or not meta.enabled:
            continue
        builders = plugin.builders
        aliases = plugin.aliases
        for effect_id, builder in builders.items():
            register_overlay_effect(
                effect_id,
                builder,
                aliases=aliases.get(effect_id, ()),
                source=meta.source,
                version=meta.version,
                enabled=meta.enabled,
            )


def _register_subtitle_plugins(plugins: List[PluginLoadResult]) -> None:
    from zundamotion.components.subtitles.effects import register_subtitle_effect

    for plugin in plugins:
        meta = plugin.meta
        if meta.kind != "subtitle" or not meta.enabled:
            continue
        builders = plugin.builders
        aliases = plugin.aliases
        for effect_id, builder in builders.items():
            register_subtitle_effect(
                effect_id,
                builder,
                aliases=aliases.get(effect_id, ()),
                source=meta.source,
                version=meta.version,
                enabled=meta.enabled,
            )

