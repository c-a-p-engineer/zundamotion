"""Plugin metadata schema and utilities."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


PLUGIN_KINDS = {"overlay", "subtitle", "audio", "transition"}
SOURCE_PRIORITY = {"user": 3, "package": 2, "builtin": 1}


@dataclass(frozen=True)
class PluginMeta:
    """Validated plugin metadata loaded from ``plugin.yaml``."""

    plugin_id: str
    version: str
    kind: str
    provides: List[str]
    enabled: bool = True
    description: str | None = None
    capabilities: Dict[str, Any] = field(default_factory=dict)
    params_schema: Dict[str, Any] = field(default_factory=dict)
    defaults: Dict[str, Any] = field(default_factory=dict)
    compat: Dict[str, Any] = field(default_factory=dict)
    source: str = "builtin"


@dataclass(frozen=True)
class PluginSpec:
    """A discovered plugin definition prior to import."""

    meta: PluginMeta
    base_path: str
    module_path: str


def parse_plugin_meta(raw: Dict[str, Any], *, source: str, base_path: str) -> Optional[PluginMeta]:
    """Parse and validate raw plugin metadata."""

    allowed_keys = {
        "id",
        "version",
        "kind",
        "provides",
        "enabled",
        "description",
        "capabilities",
        "params_schema",
        "defaults",
        "compat",
    }
    unknown_keys = set(raw.keys()) - allowed_keys
    if unknown_keys:
        return None

    plugin_id = raw.get("id")
    version = raw.get("version")
    kind = raw.get("kind")
    provides_raw = raw.get("provides")
    enabled = raw.get("enabled", True)

    if not isinstance(plugin_id, str) or not plugin_id.strip():
        return None
    if not isinstance(version, str) or not version.strip():
        return None
    if not isinstance(kind, str) or kind not in PLUGIN_KINDS:
        return None
    if provides_raw is None:
        provides: List[str] = [plugin_id.strip()]
    elif isinstance(provides_raw, list):
        provides = [str(p).strip() for p in provides_raw if isinstance(p, (str, int, float)) and str(p).strip()]
    elif isinstance(provides_raw, str):
        provides = [provides_raw.strip()]
    else:
        return None

    if not provides:
        return None

    if not isinstance(enabled, bool):
        enabled = bool(enabled)

    description = raw.get("description") if isinstance(raw.get("description"), str) else None

    def _validate_mapping(key: str) -> Dict[str, Any]:
        val = raw.get(key)
        if not isinstance(val, dict):
            return {}
        clean: Dict[str, Any] = {}
        for k, v in val.items():
            if not isinstance(k, str) or not k.strip():
                continue
            if not _is_json_like(v):
                continue
            clean[k.strip()] = v
        return clean

    return PluginMeta(
        plugin_id=plugin_id.strip(),
        version=version.strip(),
        kind=kind,
        provides=provides,
        enabled=enabled,
        description=description,
        capabilities=_validate_mapping("capabilities"),
        params_schema=_validate_mapping("params_schema"),
        defaults=_validate_mapping("defaults"),
        compat=_validate_mapping("compat"),
        source=source,
    )


def _is_json_like(value: Any) -> bool:
    return isinstance(value, (str, int, float, bool, type(None), list, dict))

