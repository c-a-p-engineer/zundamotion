from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Dict, List, Optional

import yaml
from yaml import YAMLError

from ...exceptions import ValidationError
from ..markdown import load_markdown_script


VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


@dataclass
class ResolvedScript:
    data: Dict[str, Any]
    trace: Dict[str, Any]
    flattened_yaml_text: Optional[str] = None


def resolve_script(
    entry_path: Path,
    *,
    dump_resolved_path: Optional[Path] = None,
    debug_include: bool = False,
) -> ResolvedScript:
    resolver = ScriptResolver()
    data = resolver.resolve(entry_path)
    flattened = yaml.safe_dump(
        data,
        allow_unicode=True,
        sort_keys=False,
    )
    if dump_resolved_path:
        dump_resolved_path.parent.mkdir(parents=True, exist_ok=True)
        dump_resolved_path.write_text(flattened, encoding="utf-8")
    if debug_include and resolver.include_chains:
        print("[include] resolved chains:")
        for chain in resolver.include_chains:
            print(f"- {chain}")
    return ResolvedScript(
        data=data,
        trace={"include_chains": resolver.include_chains},
        flattened_yaml_text=flattened,
    )


class ScriptResolver:
    def __init__(self) -> None:
        self.include_chains: List[str] = []

    def resolve(self, entry_path: Path) -> Dict[str, Any]:
        resolved = self._resolve_file(entry_path, inherited_vars={}, stack=[])
        if not isinstance(resolved, dict):
            raise ValidationError("Entry script must be a mapping at the top level.")
        return resolved

    def _resolve_file(
        self,
        path: Path,
        *,
        inherited_vars: Dict[str, Any],
        stack: List[Path],
    ) -> Any:
        resolved_path = path.resolve()
        if resolved_path in stack:
            chain = " -> ".join(str(p) for p in stack + [resolved_path])
            raise ValidationError(f"Include cycle detected: {chain}")

        data = self._load_source(resolved_path)
        current_stack = stack + [resolved_path]
        base_dir = resolved_path.parent

        if isinstance(data, list):
            scenes = self._resolve_scenes(
                data,
                base_dir=base_dir,
                inherited_vars=inherited_vars,
                stack=current_stack,
            )
            return substitute_vars(scenes, inherited_vars)

        if not isinstance(data, dict):
            raise ValidationError(
                f"Included YAML must be a mapping or a list: {resolved_path}"
            )

        local_vars = data.get("vars") or {}
        if not isinstance(local_vars, dict):
            raise ValidationError(
                f"'vars' must be a mapping in {resolved_path}"
            )
        merged_vars = {**inherited_vars, **local_vars}

        resolved: Dict[str, Any] = {}
        for key, value in data.items():
            if key == "vars":
                continue
            if key == "scenes":
                resolved[key] = self._resolve_scenes(
                    value,
                    base_dir=base_dir,
                    inherited_vars=merged_vars,
                    stack=current_stack,
                )
                continue
            if isinstance(value, dict) and "include" in value:
                resolved[key] = self._resolve_non_scene_section(
                    value,
                    base_dir=base_dir,
                    inherited_vars=merged_vars,
                    stack=current_stack,
                )
                continue
            resolved[key] = value

        return substitute_vars(resolved, merged_vars)

    def _resolve_scenes(
        self,
        scenes: Any,
        *,
        base_dir: Path,
        inherited_vars: Dict[str, Any],
        stack: List[Path],
    ) -> List[Dict[str, Any]]:
        if not isinstance(scenes, list):
            raise ValidationError("'scenes' must be a list.")

        resolved_scenes: List[Dict[str, Any]] = []
        for idx, item in enumerate(scenes):
            if isinstance(item, dict) and "include" in item:
                include_path = self._resolve_include_path(
                    item["include"], base_dir=base_dir
                )
                self.include_chains.append(
                    " -> ".join(str(p) for p in stack + [include_path])
                )
                included = self._resolve_file(
                    include_path,
                    inherited_vars=inherited_vars,
                    stack=stack,
                )
                included_scenes = self._extract_scenes(included)
                if not included_scenes:
                    raise ValidationError(
                        f"Include '{include_path}' expanded to 0 scenes."
                    )
                transition = item.get("transition")
                if transition is not None:
                    if not resolved_scenes:
                        raise ValidationError(
                            "Transition specified on include but no previous scene exists."
                        )
                    prev_scene = resolved_scenes[-1]
                    if prev_scene.get("transition") is not None:
                        raise ValidationError(
                            "Previous scene already has a transition; include boundary transition is ambiguous."
                        )
                    prev_scene["transition"] = normalize_transition(transition)
                resolved_scenes.extend(included_scenes)
                continue
            if not isinstance(item, dict):
                raise ValidationError(
                    f"Scene at index {idx} must be a dictionary or include directive."
                )
            resolved_scenes.append(item)

        return resolved_scenes

    def _resolve_non_scene_section(
        self,
        section: Dict[str, Any],
        *,
        base_dir: Path,
        inherited_vars: Dict[str, Any],
        stack: List[Path],
    ) -> Dict[str, Any]:
        include_value = section.get("include")
        include_paths = normalize_include_list(include_value)

        merged: Dict[str, Any] = {}
        for include_item in include_paths:
            include_path = self._resolve_include_path(include_item, base_dir=base_dir)
            self.include_chains.append(
                " -> ".join(str(p) for p in stack + [include_path])
            )
            included = self._resolve_file(
                include_path,
                inherited_vars=inherited_vars,
                stack=stack,
            )
            if not isinstance(included, dict):
                raise ValidationError(
                    f"Include '{include_path}' must resolve to a mapping for non-scene sections."
                )
            merged = deep_merge(merged, included)

        local_section = {k: v for k, v in section.items() if k != "include"}
        merged = deep_merge(merged, local_section)
        return merged

    def _resolve_include_path(self, value: Any, *, base_dir: Path) -> Path:
        if not isinstance(value, str):
            raise ValidationError("Include path must be a string.")
        return (base_dir / value).resolve()

    def _extract_scenes(self, data: Any) -> List[Dict[str, Any]]:
        if isinstance(data, dict):
            if "scenes" in data:
                scenes = data["scenes"]
                if not isinstance(scenes, list):
                    raise ValidationError("Included 'scenes' must be a list.")
                return self._ensure_scene_dicts(scenes)
            return self._ensure_scene_dicts([data])
        if isinstance(data, list):
            return self._ensure_scene_dicts(data)
        raise ValidationError("Included scene content must be a list or mapping.")

    def _ensure_scene_dicts(self, scenes: List[Any]) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []
        for idx, scene in enumerate(scenes):
            if not isinstance(scene, dict):
                raise ValidationError(
                    f"Included scene at index {idx} must be a dictionary."
                )
            result.append(scene)
        return result

    def _load_source(self, path: Path) -> Any:
        if path.suffix.lower() in {".md", ".markdown"}:
            return load_markdown_script(path)

        try:
            with path.open("r", encoding="utf-8") as fh:
                return yaml.safe_load(fh) or {}
        except YAMLError as e:
            mark = getattr(e, "mark", None)
            line = mark.line + 1 if mark else None
            column = mark.column + 1 if mark else None
            raise ValidationError(
                f"Invalid YAML syntax in {path}: {e}",
                line_number=line,
                column_number=column,
            )
        except FileNotFoundError:
            raise ValidationError(f"Configuration file not found: {path}")


def normalize_include_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return value
    raise ValidationError("'include' must be a string or list of strings.")


def deep_merge(base: Any, override: Any) -> Any:
    if isinstance(base, dict) and isinstance(override, dict):
        merged: Dict[str, Any] = base.copy()
        for key, value in override.items():
            if key in merged:
                merged[key] = deep_merge(merged[key], value)
            else:
                merged[key] = value
        return merged
    if isinstance(override, list):
        return list(override)
    return override


def normalize_transition(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    if "type" in value:
        return value
    if "video" in value:
        normalized = dict(value)
        normalized["type"] = value.get("video")
        return normalized
    return value


def substitute_vars(value: Any, vars_dict: Dict[str, Any], path: str = "") -> Any:
    if isinstance(value, dict):
        return {
            key: substitute_vars(
                val,
                vars_dict,
                path=f"{path}.{key}" if path else str(key),
            )
            for key, val in value.items()
        }
    if isinstance(value, list):
        return [
            substitute_vars(item, vars_dict, path=f"{path}[{idx}]")
            for idx, item in enumerate(value)
        ]
    if isinstance(value, str):
        def _replace(match: re.Match[str]) -> str:
            key = match.group(1)
            if key not in vars_dict:
                raise ValidationError(
                    f"Undefined variable '{key}' at '{path or '$'}'."
                )
            return str(vars_dict[key])

        return VAR_PATTERN.sub(_replace, value)
    return value
