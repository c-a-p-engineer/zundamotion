"""Pure planning for consecutive static Run Base sections.

Rendering I/O remains outside this module. The planner deliberately keeps the
original 1-based scene line index so waits and non-render lines cannot shift
line_data_map lookups or offsets.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional


@dataclass(frozen=True)
class RunBasePlan:
    start_line: int
    end_line: int
    duration: float
    overlays: tuple[Dict[str, Any], ...]
    character_keys: frozenset[str]
    has_insert_image: bool
    offsets: Mapping[int, float]


@dataclass(frozen=True)
class _RunEntry:
    line_index: int
    duration: float
    character_map: Dict[str, Dict[str, Any]]
    insert_overlay: Optional[Dict[str, Any]]
    signature: str


def _is_boundary_line(line: Mapping[str, Any]) -> bool:
    if "wait" in line or line.get("type") in {"wait", "image_layer"}:
        return True
    background = line.get("background")
    return isinstance(background, Mapping) and bool(background.get("path"))


def _insert_image_overlay(
    line: Mapping[str, Any],
    *,
    video_extensions: Iterable[str],
) -> Optional[Dict[str, Any]]:
    insert = line.get("insert") or {}
    if not isinstance(insert, Mapping):
        return None
    raw_path = insert.get("path")
    if not raw_path:
        return None
    path = Path(str(raw_path))
    if not path.exists() or path.suffix.lower() in set(video_extensions):
        return None
    try:
        scale = float(insert.get("scale", 1.0) or 1.0)
    except (TypeError, ValueError):
        scale = 1.0
    position = insert.get("position")
    if not isinstance(position, Mapping):
        position = {"x": "0", "y": "0"}
    return {
        "path": str(path.resolve()),
        "scale": scale,
        "anchor": str(insert.get("anchor", "middle_center")),
        "position": {
            "x": position.get("x", "0"),
            "y": position.get("y", "0"),
        },
    }


def _signature(
    character_map: Mapping[str, Mapping[str, Any]],
    insert_overlay: Optional[Mapping[str, Any]],
) -> str:
    return json.dumps(
        {
            "characters": character_map,
            "insert": insert_overlay,
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )


def _build_entry(
    *,
    scene_id: str,
    line_index: int,
    line: Dict[str, Any],
    line_data_map: Mapping[str, Mapping[str, Any]],
    norm_char_entries: Callable[[Dict[str, Any]], Dict[str, Dict[str, Any]]],
    video_extensions: Iterable[str],
) -> Optional[_RunEntry]:
    if _is_boundary_line(line):
        return None
    character_map = norm_char_entries(line)
    if not character_map:
        return None
    line_data = line_data_map.get(f"{scene_id}_{line_index}") or {}
    try:
        duration = float(line_data.get("duration", 0.0) or 0.0)
    except (TypeError, ValueError):
        duration = 0.0
    if duration <= 0:
        return None
    insert_overlay = _insert_image_overlay(
        line,
        video_extensions=video_extensions,
    )
    return _RunEntry(
        line_index=line_index,
        duration=duration,
        character_map=character_map,
        insert_overlay=insert_overlay,
        signature=_signature(character_map, insert_overlay),
    )


def _finalize_run(entries: List[_RunEntry], minimum_lines: int) -> Optional[RunBasePlan]:
    if len(entries) < minimum_lines:
        return None
    first = entries[0]
    offsets: Dict[int, float] = {}
    elapsed = 0.0
    for entry in entries:
        offsets[entry.line_index] = elapsed
        elapsed += entry.duration
    overlays: List[Dict[str, Any]] = [
        first.character_map[key] for key in sorted(first.character_map)
    ]
    if first.insert_overlay is not None:
        overlays.append(first.insert_overlay)
    return RunBasePlan(
        start_line=first.line_index,
        end_line=entries[-1].line_index,
        duration=elapsed,
        overlays=tuple(overlays),
        character_keys=frozenset(first.character_map),
        has_insert_image=first.insert_overlay is not None,
        offsets=offsets,
    )


def build_run_base_plans(
    *,
    scene_id: str,
    lines: Iterable[Dict[str, Any]],
    line_data_map: Mapping[str, Mapping[str, Any]],
    norm_char_entries: Callable[[Dict[str, Any]], Dict[str, Dict[str, Any]]],
    video_extensions: Iterable[str],
    minimum_lines: int = 2,
) -> List[RunBasePlan]:
    """Return consecutive, signature-stable runs using original line indexes."""
    plans: List[RunBasePlan] = []
    current: List[_RunEntry] = []

    def close_current() -> None:
        nonlocal current
        plan = _finalize_run(current, max(2, int(minimum_lines)))
        if plan is not None:
            plans.append(plan)
        current = []

    for line_index, line in enumerate(lines, start=1):
        entry = _build_entry(
            scene_id=scene_id,
            line_index=line_index,
            line=line,
            line_data_map=line_data_map,
            norm_char_entries=norm_char_entries,
            video_extensions=video_extensions,
        )
        if entry is None:
            close_current()
            continue
        if current and current[0].signature != entry.signature:
            close_current()
        current.append(entry)
    close_current()
    return plans


class SceneRunBasePlanMixin:
    """Expose Run Base planning to SceneRenderer without rendering side effects."""

    def _build_run_base_plans(self, scene_id: str) -> List[RunBasePlan]:
        return build_run_base_plans(
            scene_id=scene_id,
            lines=self.scene.get("lines", []) or [],
            line_data_map=self.line_data_map,
            norm_char_entries=self._norm_char_entries,
            video_extensions=self.video_extensions,
        )
