"""Pure planning for standard talk-line rendering inputs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from ....utils.subtitle_text import is_effective_subtitle_text
from .scene_line_context import SceneLineContext


_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".bmp", ".webp")


@dataclass(frozen=True)
class SceneTalkPlan:
    """Resolved character, insert, animation, and classification inputs."""

    effective_characters: tuple[Dict[str, Any], ...]
    effective_insert: Optional[Dict[str, Any]]
    face_animations: tuple[Any, ...]
    animation_meta: Dict[str, Any]
    has_subtitle: bool
    has_visible_characters: bool
    insert_is_image: bool
    has_move: bool
    has_effect: bool


class SceneTalkPlanMixin:
    """Resolve talk-line inputs without cache or FFmpeg side effects."""

    def _build_scene_talk_plan(
        self,
        *,
        context: SceneLineContext,
        static_character_keys: Iterable[Any],
        static_insert_in_base: bool,
        scene_level_insert_video: Optional[Path],
    ) -> SceneTalkPlan:
        characters = list(context.visual_container.get("characters", []) or [])
        base_character_keys = set(static_character_keys)
        if context.run_base is not None:
            base_character_keys.update(context.run_base.character_keys)

        if base_character_keys:
            effective_characters = []
            for character in characters:
                if not character.get("visible", False):
                    effective_characters.append(character)
                    continue
                entry_keys = set(
                    self._norm_char_entries(
                        {"characters": [character]}
                    ).keys()
                )
                if entry_keys & base_character_keys:
                    continue
                effective_characters.append(character)
        else:
            effective_characters = characters

        effective_insert = self._resolve_effective_talk_insert(
            context=context,
            static_insert_in_base=static_insert_in_base,
            scene_level_insert_video=scene_level_insert_video,
        )
        face_animations = self._normalize_face_animations(
            context.line_data.get("face_anim")
        )
        first_animation = face_animations[0] if face_animations else {}
        animation_meta = dict((first_animation or {}).get("meta") or {})

        raw_insert = context.line_config.get("insert") or {}
        insert_path = str(raw_insert.get("path", ""))
        return SceneTalkPlan(
            effective_characters=tuple(effective_characters),
            effective_insert=effective_insert,
            face_animations=tuple(face_animations),
            animation_meta=animation_meta,
            has_subtitle=is_effective_subtitle_text(
                context.line_data.get("text")
            ),
            has_visible_characters=any(
                (character or {}).get("visible", False)
                for character in characters
            ),
            insert_is_image=insert_path.lower().endswith(_IMAGE_EXTENSIONS),
            has_move=bool(context.line_config.get("move"))
            or any(
                bool((character or {}).get("move"))
                for character in characters
            ),
            has_effect=bool(
                context.line_config.get("background_effects")
                or context.line_config.get("screen_effects")
            ),
        )

    @staticmethod
    def _normalize_face_animations(raw: Any) -> list[Any]:
        if isinstance(raw, list):
            return list(raw)
        if raw:
            return [raw]
        return []

    @staticmethod
    def _resolve_effective_talk_insert(
        *,
        context: SceneLineContext,
        static_insert_in_base: bool,
        scene_level_insert_video: Optional[Path],
    ) -> Optional[Dict[str, Any]]:
        if static_insert_in_base or (
            context.run_base is not None
            and context.run_base.has_insert_image
        ):
            return None

        raw_insert = context.line_config.get("insert")
        if (
            scene_level_insert_video is not None
            and raw_insert
            and Path(raw_insert.get("path", "")).exists()
        ):
            return {
                **raw_insert,
                "path": str(scene_level_insert_video),
                "normalized": True,
                "pre_scaled": True,
            }
        return raw_insert
