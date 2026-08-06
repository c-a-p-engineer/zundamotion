"""Scene timing mutation and derived render context.

This module is an internal SceneRenderer mixin; use scene_renderer.SceneRenderer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple


SceneLine = Tuple[int, Dict[str, Any]]


@dataclass(frozen=True)
class SceneTimingPlan:
    """Derived timing and cache context for one scene render."""

    lines: List[SceneLine]
    scene_duration: float
    start_time_by_idx: Dict[int, float]
    badge_line_markers: Dict[str, float]
    subtitle_entries: List[Dict[str, Any]]
    subtitle_timing_key: str
    component_keys: Dict[str, Any]


def _max_enabled_character_duration(
    characters: List[Dict[str, Any]],
    duration_key: str,
) -> float:
    """Return the maximum enabled enter/leave duration."""
    duration = 0.0
    enabled_key = duration_key.replace("_duration", "")
    for character in characters:
        if not character.get(enabled_key):
            continue
        try:
            candidate = float(character.get(duration_key, 0.0))
        except Exception:
            candidate = 0.0
        duration = max(duration, candidate)
    return duration


def _resolve_j_cut_padding(line: Dict[str, Any]) -> float:
    """Resolve non-negative J-cut padding while preserving legacy fallback."""
    j_cut_config = line.get("j_cut")
    try:
        value = float(
            (j_cut_config or {}).get(
                "duration",
                line.get("audio_delay", 0.0),
            )
            if isinstance(j_cut_config, dict)
            else line.get("audio_delay", 0.0)
        )
    except Exception:
        value = 0.0
    return max(0.0, value)


def _apply_line_duration_padding(
    *,
    scene_id: str,
    lines: List[SceneLine],
    line_data_map: Dict[str, Dict[str, Any]],
) -> None:
    """Mutate line timing with enter, J-cut, and leave padding."""
    for line_index, line in lines:
        line_data = line_data_map.get(f"{scene_id}_{line_index}")
        if not line_data:
            continue
        characters = line.get("characters", []) or []
        enter_padding = _max_enabled_character_duration(
            characters,
            "enter_duration",
        )
        leave_padding = _max_enabled_character_duration(
            characters,
            "leave_duration",
        )
        j_cut_padding = _resolve_j_cut_padding(line)
        line_data["pre_duration"] = enter_padding + j_cut_padding
        line_data["post_duration"] = leave_padding
        line_data["duration"] = (
            float(line_data.get("duration", 0.0))
            + enter_padding
            + j_cut_padding
            + leave_padding
        )


def _build_start_times(
    *,
    scene_id: str,
    lines: List[SceneLine],
    line_data_map: Dict[str, Dict[str, Any]],
) -> tuple[float, Dict[int, float]]:
    """Return scene duration and cumulative line start times."""
    scene_duration = sum(
        line_data_map[f"{scene_id}_{line_index}"]["duration"]
        for line_index, _line in lines
    )
    start_time_by_idx: Dict[int, float] = {}
    elapsed = 0.0
    for line_index, _line in lines:
        start_time_by_idx[line_index] = elapsed
        elapsed += line_data_map[f"{scene_id}_{line_index}"]["duration"]
    return scene_duration, start_time_by_idx


class SceneTimingMixin:
    """Build timing and cache-derived context before scene rendering."""

    def _build_scene_timing_plan(
        self,
        *,
        scene: Dict[str, Any],
        scene_hash_data: Dict[str, Any],
        scene_base_hash_data: Dict[str, Any],
    ) -> SceneTimingPlan:
        scene_id = scene["id"]
        lines = list(enumerate(scene.get("lines", []), start=1))
        _apply_line_duration_padding(
            scene_id=scene_id,
            lines=lines,
            line_data_map=self.line_data_map,
        )
        scene_duration, start_time_by_idx = _build_start_times(
            scene_id=scene_id,
            lines=lines,
            line_data_map=self.line_data_map,
        )
        badge_line_markers = self._build_badge_line_markers(
            start_time_by_idx=start_time_by_idx,
        )
        subtitle_entries = self._build_subtitle_entries(
            scene_id,
            start_time_by_idx,
        )
        component_keys = self._scene_cache_component_keys(
            scene_hash_data,
            scene_base_hash_data,
        )
        subtitle_timing_key = self._subtitle_timing_key(subtitle_entries)
        component_keys["subtitle_timing_key"] = subtitle_timing_key
        return SceneTimingPlan(
            lines=lines,
            scene_duration=scene_duration,
            start_time_by_idx=start_time_by_idx,
            badge_line_markers=badge_line_markers,
            subtitle_entries=subtitle_entries,
            subtitle_timing_key=subtitle_timing_key,
            component_keys=component_keys,
        )
