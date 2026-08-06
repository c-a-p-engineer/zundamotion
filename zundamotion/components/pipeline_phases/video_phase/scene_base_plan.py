"""Scene base eligibility and shared-layer planning.

This module is an internal SceneRenderer mixin; use scene_renderer.SceneRenderer.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


CharacterKey = Tuple[Any, ...]
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
_VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".avi", ".mkv"}


@dataclass(frozen=True)
class SceneBasePlan:
    """Resolved inputs and eligibility for one scene-level base video."""

    static_overlays: List[Dict[str, Any]]
    static_character_keys: Set[CharacterKey]
    static_insert_in_base: bool
    common_insert_video_path: Optional[Path]
    should_generate_base: bool
    base_background_layout: Dict[str, Any]
    total_lines: int
    minimum_lines: int
    scene_copy: bool
    detection_error: Optional[str] = None


def _talk_lines(scene: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        line
        for line in scene.get("lines", [])
        if not ("wait" in line or line.get("type") == "wait")
    ]


def _common_character_overlays(
    *,
    talk_lines: List[Dict[str, Any]],
    normalize_characters,
) -> tuple[List[Dict[str, Any]], Set[CharacterKey]]:
    if not talk_lines:
        return [], set()
    character_maps = [normalize_characters(line) for line in talk_lines]
    if not character_maps:
        return [], set()
    common_keys = set(character_maps[0])
    for character_map in character_maps[1:]:
        common_keys &= set(character_map)
    overlays: List[Dict[str, Any]] = []
    available_keys: Set[CharacterKey] = set()
    for key in sorted(common_keys):
        overlay = character_maps[0][key]
        if not Path(overlay["path"]).exists():
            continue
        overlays.append(overlay)
        available_keys.add(key)
    return overlays, available_keys


def _common_insert_plan(
    talk_lines: List[Dict[str, Any]],
) -> tuple[Optional[Dict[str, Any]], Optional[Path]]:
    if not talk_lines:
        return None, None
    first_insert = talk_lines[0].get("insert")
    if not first_insert or not all(
        line.get("insert") == first_insert for line in talk_lines
    ):
        return None, None
    insert_path = Path(first_insert.get("path", ""))
    if not insert_path.exists():
        return None, None
    suffix = insert_path.suffix.lower()
    if suffix in _IMAGE_EXTENSIONS:
        return (
            {
                "path": str(insert_path),
                "scale": first_insert.get("scale", 1.0),
                "anchor": first_insert.get("anchor", "middle_center"),
                "position": first_insert.get(
                    "position",
                    {"x": "0", "y": "0"},
                ),
            },
            None,
        )
    if suffix in _VIDEO_EXTENSIONS:
        return None, insert_path
    return None, None


def _should_generate_scene_base(
    *,
    has_line_background_override: bool,
    static_overlays: List[Dict[str, Any]],
    is_background_video: bool,
    total_lines: int,
    minimum_lines: int,
) -> bool:
    if has_line_background_override:
        return False
    if static_overlays:
        return True
    if is_background_video:
        return total_lines >= minimum_lines
    return total_lines >= 2


class SceneBasePlanMixin:
    """Resolve scene-level base inputs without invoking FFmpeg."""

    def _build_scene_base_plan(
        self,
        *,
        scene: Dict[str, Any],
        scene_copy: bool,
        is_background_video: bool,
        has_line_background_override: bool,
    ) -> SceneBasePlan:
        talk_lines = _talk_lines(scene)
        try:
            static_overlays, static_character_keys = _common_character_overlays(
                talk_lines=talk_lines,
                normalize_characters=self._norm_char_entries,
            )
            insert_overlay, common_insert_video_path = _common_insert_plan(
                talk_lines
            )
            static_insert_in_base = insert_overlay is not None
            if insert_overlay is not None:
                static_overlays.append(insert_overlay)
        except Exception as error:
            static_overlays = []
            static_character_keys = set()
            static_insert_in_base = False
            common_insert_video_path = None
            detection_error = str(error)
        else:
            detection_error = None

        if scene_copy:
            static_overlays = []
            static_character_keys = set()
            static_insert_in_base = False

        total_lines = len(scene.get("lines", []))
        minimum_lines = int(
            self.config.get("video", {}).get("scene_base_min_lines", 6)
        )
        should_generate_base = _should_generate_scene_base(
            has_line_background_override=has_line_background_override,
            static_overlays=static_overlays,
            is_background_video=is_background_video,
            total_lines=total_lines,
            minimum_lines=minimum_lines,
        )
        return SceneBasePlan(
            static_overlays=static_overlays,
            static_character_keys=static_character_keys,
            static_insert_in_base=static_insert_in_base,
            common_insert_video_path=common_insert_video_path,
            should_generate_base=should_generate_base,
            base_background_layout=self._resolve_background_layout({}),
            total_lines=total_lines,
            minimum_lines=minimum_lines,
            scene_copy=scene_copy,
            detection_error=detection_error,
        )
