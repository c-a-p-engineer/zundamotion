"""Plugin discovery and loader implementation."""

from __future__ import annotations

import ast
import importlib.util
import time
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, Iterable, List, Optional, Tuple

import yaml

from zundamotion.utils.logger import logger

from .schema import PluginMeta, PluginSpec, parse_plugin_meta


@dataclass(frozen=True)
class PluginLoadResult:
    """Structured load result to avoid extra dependencies."""

    meta: PluginMeta
    builders: Dict[str, Any]
    aliases: Dict[str, List[str]]
    duration_s: float
    source_path: str


_PLUGIN_CACHE: Dict[Tuple[Any, ...], Tuple[PluginLoadResult, ...]] = {}


class UnsafePluginError(Exception):
    """Raised when a plugin module violates safety guard rails."""


def default_plugin_paths(extra_paths: Optional[Iterable[str | Path]] = None) -> List[Path]:
    """Return default plugin search paths including built-ins and user drop-ins."""

    roots = builtin_plugin_paths()
    roots.append(Path.cwd() / "plugins")
    try:
        roots.append(Path.home() / ".zundamotion" / "plugins")
    except Exception:
        pass
    if extra_paths:
        roots.extend(Path(p).expanduser() for p in extra_paths)
    return _deduplicate_paths(roots)


def load_plugins_cached(
    roots: Iterable[Path],
    *,
    allow: Optional[Iterable[str]] = None,
    deny: Optional[Iterable[str]] = None,
    use_cache: bool = True,
) -> List[PluginLoadResult]:
    """Discover and load plugins with an optional in-process cache."""

    allow_key = tuple(sorted(set(allow or ())))
    deny_key = tuple(sorted(set(deny or ())))
    root_key = tuple(sorted(str(Path(r).resolve()) for r in roots))
    cache_key = (root_key, allow_key, deny_key)

    if use_cache and cache_key in _PLUGIN_CACHE:
        return list(_PLUGIN_CACHE[cache_key])

    specs = discover_plugins((Path(r) for r in root_key), allow=allow, deny=deny)
    resolved: List[PluginLoadResult] = []
    for spec in specs:
        loaded = load_plugin_builders(spec)
        if loaded:
            resolved.append(loaded)

    if use_cache:
        _PLUGIN_CACHE[cache_key] = tuple(resolved)

    return resolved


def builtin_plugin_paths() -> List[Path]:
    """Return only built-in plugin search paths (no user drop-ins)."""

    base = Path(__file__).resolve().parent
    return [base / "builtin"]


def _deduplicate_paths(paths: Iterable[Path]) -> List[Path]:
    seen = set()
    ordered: List[Path] = []
    for root in paths:
        key = str(root.resolve())
        if key in seen:
            continue
        seen.add(key)
        ordered.append(root)
    return ordered


def discover_plugins(
    roots: Iterable[Path], *, allow: Optional[Iterable[str]] = None, deny: Optional[Iterable[str]] = None
) -> List[PluginSpec]:
    """Scan plugin roots for ``plugin.yaml`` files and return validated specs."""

    allow_set = {a for a in (allow or [])}
    deny_set = {d for d in (deny or [])}

    specs: List[PluginSpec] = []
    for root in roots:
        if not root.exists():
            continue
        for manifest in root.rglob("plugin.yaml"):
            source = "builtin" if "builtin" in manifest.parts else "user"
            meta = _load_meta(manifest, source=source)
            if not meta:
                continue
            if allow_set and meta.plugin_id not in allow_set:
                continue
            if meta.plugin_id in deny_set:
                continue
            module_path = manifest.with_name("plugin.py")
            specs.append(
                PluginSpec(
                    meta=meta,
                    base_path=str(manifest.parent),
                    module_path=str(module_path),
                )
            )
    return specs


def load_plugin_module(spec: PluginSpec) -> Optional[ModuleType]:
    """Import a plugin module from the discovered spec."""

    module_file = Path(spec.module_path)
    if not module_file.exists():
        logger.warning(
            "[PluginLoader] Module file missing for plugin %s at %s", spec.meta.plugin_id, spec.module_path
        )
        return None

    start = time.perf_counter()
    module_name = f"zundamotion.plugins.dynamic.{spec.meta.plugin_id.replace('-', '_')}"
    try:
        _guard_plugin_source(module_file)
        loader = importlib.util.spec_from_file_location(module_name, module_file)
        if loader is None or loader.loader is None:
            raise ImportError("Invalid module spec")
        module = importlib.util.module_from_spec(loader)
        loader.loader.exec_module(module)  # type: ignore[assignment]
        return module
    except UnsafePluginError as exc:
        elapsed = time.perf_counter() - start
        logger.warning(
            "[PluginLoader] Blocked unsafe plugin %s (%s) reason=%s duration=%.4fs",
            spec.meta.plugin_id,
            spec.module_path,
            exc,
            elapsed,
        )
        return None
    except Exception as exc:  # noqa: BLE001 - safe logging and continue
        elapsed = time.perf_counter() - start
        logger.warning(
            "[PluginLoader] Failed to import plugin %s: %s duration=%.4fs",
            spec.meta.plugin_id,
            exc,
            elapsed,
        )
        return None


def load_plugin_builders(spec: PluginSpec) -> Optional[PluginLoadResult]:
    """Load plugin module and extract builder mapping + aliases."""

    start = time.perf_counter()
    module = load_plugin_module(spec)
    if module is None:
        return None

    builders = _extract_builders(module)
    if not builders:
        logger.warning(
            "[PluginLoader] Plugin %s did not expose any builders", spec.meta.plugin_id
        )
        return None

    aliases = _extract_aliases(module)
    duration = time.perf_counter() - start
    return PluginLoadResult(
        meta=spec.meta,
        builders=builders,
        aliases=aliases,
        duration_s=duration,
        source_path=str(spec.module_path),
    )


def _extract_builders(module: ModuleType) -> Dict[str, Any]:
    if hasattr(module, "BUILDERS") and isinstance(module.BUILDERS, dict):  # type: ignore[attr-defined]
        return {
            str(name): func
            for name, func in module.BUILDERS.items()  # type: ignore[attr-defined]
            if callable(func)
        }
    builder = getattr(module, "builder", None)
    effect_id = getattr(module, "EFFECT_ID", None)
    if callable(builder) and isinstance(effect_id, str):
        return {effect_id: builder}
    return {}


def _extract_aliases(module: ModuleType) -> Dict[str, List[str]]:
    aliases = getattr(module, "ALIASES", None)
    if isinstance(aliases, dict):
        result: Dict[str, List[str]] = {}
        for name, alias_list in aliases.items():
            if isinstance(alias_list, (list, tuple)):
                sanitized = [str(a).strip() for a in alias_list if str(a).strip()]
                if sanitized:
                    result[str(name)] = sanitized
        return result
    return {}


def _load_meta(manifest: Path, *, source: str) -> Optional[PluginMeta]:
    try:
        with manifest.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
    except Exception as exc:  # noqa: BLE001 - config error should not crash main flow
        logger.warning(
            "[PluginLoader] Failed to read manifest %s: %s", manifest, exc
        )
        return None

    meta = parse_plugin_meta(raw, source=source, base_path=str(manifest.parent))
    if meta is None:
        logger.warning(
            "[PluginLoader] Invalid manifest for plugin at %s", manifest
        )
        return None
    return meta


def _guard_plugin_source(module_file: Path) -> None:
    """Perform lightweight static checks against disallowed imports."""

    forbidden_roots = {"subprocess", "socket", "os"}
    try:
        tree = ast.parse(module_file.read_text(encoding="utf-8"), filename=str(module_file))
    except Exception as exc:  # noqa: BLE001
        raise UnsafePluginError(f"parse-error:{exc}") from exc

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_forbidden(alias.name, forbidden_roots):
                    raise UnsafePluginError(f"forbidden-import:{alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module_name = node.module or ""
            if _is_forbidden(module_name, forbidden_roots):
                raise UnsafePluginError(f"forbidden-import:{module_name}")


def _is_forbidden(name: str, forbidden_roots: set[str]) -> bool:
    root = name.split(".")[0]
    return root in forbidden_roots

