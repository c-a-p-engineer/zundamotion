"""Pure eligibility facts and SceneRenderer adapters for simple scene fast paths.

GPU eligibility preserves the historical rules. CPU eligibility is deliberately
stricter and is reachable only through the opt-in environment flag
``ZUNDAMOTION_CPU_SCENE_FAST_PATH=1``.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from ....utils.ffmpeg_ops import BACKGROUND_FIT_STRETCH


_CPU_FAST_PATH_ENV = "ZUNDAMOTION_CPU_SCENE_FAST_PATH"


@dataclass(frozen=True)
class FastPathLineEligibility:
    index: int
    line_type: str
    has_complex_media: bool
    has_voice_layers: bool
    has_effects: bool
    has_video_filter: bool
    background_fit: str
    has_background: bool
    background_is_video: bool
    has_start_time: bool
    character_error: Optional[str]
    background_matches_scene: bool = True
    character_signature: Optional[Tuple[Any, ...]] = None
    has_character_motion: bool = False


@dataclass(frozen=True)
class FastPathEligibility:
    has_hw_encoder: bool
    generate_no_sub_video: bool
    scene_background_is_static_image: bool
    has_foreground_overlays: bool
    scene_duration: float
    subtitle_mode: str
    lines: Tuple[FastPathLineEligibility, ...]


def evaluate_fast_path_eligibility(facts: FastPathEligibility) -> tuple[bool, str]:
    """Return the historical GPU fast-path decision without side effects."""
    if not facts.has_hw_encoder:
        return False, "cpu_encoder"
    if facts.generate_no_sub_video:
        return False, "generate_no_sub_enabled"
    if not facts.scene_background_is_static_image:
        return False, "scene_background_not_static_image"
    if facts.has_foreground_overlays:
        return False, "foreground_overlays_present"
    if facts.scene_duration <= 0:
        return False, "empty_scene"
    if facts.subtitle_mode == "png":
        return False, "subtitle_render_mode_png"

    for line in facts.lines:
        if line.line_type != "talk":
            return False, f"non_talk_line:{line.index}"
        if line.has_complex_media:
            return False, f"complex_line_media:{line.index}"
        if line.has_voice_layers:
            return False, f"voice_layers:{line.index}"
        if line.has_effects:
            return False, f"effects:{line.index}"
        if line.has_video_filter:
            return False, f"video_filter:{line.index}"
        if line.background_fit != BACKGROUND_FIT_STRETCH:
            return False, f"background_fit:{line.index}"
        if not line.has_background:
            return False, f"missing_background:{line.index}"
        if line.background_is_video:
            return False, f"line_background_video:{line.index}"
        if not line.has_start_time:
            return False, f"missing_start_time:{line.index}"
        if line.character_error:
            return False, f"character:{line.index}:{line.character_error}"
    return True, "ok"


def evaluate_cpu_fast_path_eligibility(
    facts: FastPathEligibility,
) -> tuple[bool, str]:
    """Return the conservative opt-in CPU fast-path decision."""
    if facts.generate_no_sub_video:
        return False, "generate_no_sub_enabled"
    if not facts.scene_background_is_static_image:
        return False, "scene_background_not_static_image"
    if facts.has_foreground_overlays:
        return False, "foreground_overlays_present"
    if facts.scene_duration <= 0:
        return False, "empty_scene"
    if facts.subtitle_mode == "png":
        return False, "subtitle_render_mode_png"

    expected_character_signature: Optional[Tuple[Any, ...]] = None
    for line in facts.lines:
        if line.line_type not in {"talk", "wait"}:
            return False, f"unsupported_cpu_line:{line.index}:{line.line_type}"
        if line.has_complex_media:
            return False, f"complex_line_media:{line.index}"
        if line.has_voice_layers:
            return False, f"voice_layers:{line.index}"
        if line.has_effects:
            return False, f"effects:{line.index}"
        if line.has_video_filter:
            return False, f"video_filter:{line.index}"
        if line.background_fit != BACKGROUND_FIT_STRETCH:
            return False, f"background_fit:{line.index}"
        if not line.has_background:
            return False, f"missing_background:{line.index}"
        if line.background_is_video:
            return False, f"line_background_video:{line.index}"
        if not line.background_matches_scene:
            return False, f"line_background_changed:{line.index}"
        if not line.has_start_time:
            return False, f"missing_start_time:{line.index}"
        if line.character_error:
            return False, f"character:{line.index}:{line.character_error}"
        if line.has_character_motion:
            return False, f"character_motion:{line.index}"
        if line.character_signature is None:
            return False, f"character_signature_missing:{line.index}"
        if expected_character_signature is None:
            expected_character_signature = line.character_signature
        elif line.character_signature != expected_character_signature:
            return False, f"character_changed:{line.index}"
    return True, "ok_cpu_experimental"


class SceneFastPathEligibilityMixin:
    """Collect renderer-dependent facts, then delegate to pure evaluators."""

    def _resolve_fast_path_subtitle_mode(self) -> str:
        subtitle_gen = self.video_renderer.subtitle_gen
        resolver = getattr(subtitle_gen, "resolve_render_mode_for_line_configs", None)
        if callable(resolver):
            return str(
                resolver(
                    [
                        (self.line_data_map.get(f"{self.scene['id']}_{idx}") or {}).get(
                            "line_config", {}
                        )
                        for idx, _line in enumerate(
                            self.scene.get("lines", []) or [], start=1
                        )
                    ]
                )
            )
        return str(subtitle_gen.subtitle_render_mode())

    @staticmethod
    def _cpu_fast_path_enabled() -> bool:
        return os.environ.get(_CPU_FAST_PATH_ENV, "0") == "1"

    def _top_level_fast_path_facts(
        self,
        *,
        scene_duration: float,
        bg_image: Optional[str],
        generate_no_sub_video: bool,
    ) -> FastPathEligibility:
        return FastPathEligibility(
            has_hw_encoder=bool(self.hw_kind),
            generate_no_sub_video=generate_no_sub_video,
            scene_background_is_static_image=bool(
                bg_image and Path(bg_image).suffix.lower() not in self.video_extensions
            ),
            has_foreground_overlays=bool(
                (self.scene.get("fg_overlays") or [])
                or any(line.get("fg_overlays") for line in self.scene.get("lines", []))
            ),
            scene_duration=scene_duration,
            subtitle_mode=self._resolve_fast_path_subtitle_mode(),
            lines=(),
        )

    def _collect_fast_path_line_facts(
        self,
        *,
        bg_image: Optional[str],
        start_time_by_idx: Dict[int, float],
        cpu_experimental: bool,
    ) -> Tuple[FastPathLineEligibility, ...]:
        scene_background = str(Path(bg_image).resolve()) if bg_image else ""
        facts = []
        for idx, line in enumerate(self.scene.get("lines", []) or [], start=1):
            line_id = f"{self.scene['id']}_{idx}"
            line_data = self.line_data_map.get(line_id) or {}
            line_config = line_data.get("line_config") or {}
            layout = self._resolve_background_layout(line_config)
            line_bg = self._resolve_background_source(line_config, bg_image)
            char_state, character_error = self._extract_simple_character_state(line)
            signature = (
                self._character_signature(char_state)
                if char_state is not None and character_error is None
                else None
            )
            has_motion = False
            if cpu_experimental and char_state is not None:
                has_motion = bool(
                    char_state.get("enter")
                    or char_state.get("leave")
                    or char_state.get("move")
                )
            facts.append(
                FastPathLineEligibility(
                    index=idx,
                    line_type=str(line_data.get("type") or ""),
                    has_complex_media=bool(line.get("insert") or line.get("image_layers")),
                    has_voice_layers=bool(line.get("voice_layers")),
                    has_effects=bool(
                        line.get("screen_effects") or line.get("background_effects")
                    ),
                    has_video_filter=bool(
                        line.get("video_filter") or self.scene.get("video_filter")
                    ),
                    background_fit=str(layout["fit"]),
                    has_background=bool(line_bg),
                    background_is_video=bool(
                        line_bg
                        and Path(line_bg).suffix.lower() in self.video_extensions
                    ),
                    has_start_time=start_time_by_idx.get(idx) is not None,
                    character_error=character_error,
                    background_matches_scene=(
                        bool(line_bg)
                        and str(Path(str(line_bg)).resolve()) == scene_background
                    ),
                    character_signature=signature,
                    has_character_motion=has_motion,
                )
            )
        return tuple(facts)

    def _build_fast_path_eligibility(
        self,
        *,
        scene_duration: float,
        bg_image: Optional[str],
        generate_no_sub_video: bool,
        start_time_by_idx: Dict[int, float],
    ) -> FastPathEligibility:
        top_level = self._top_level_fast_path_facts(
            scene_duration=scene_duration,
            bg_image=bg_image,
            generate_no_sub_video=generate_no_sub_video,
        )
        if evaluate_fast_path_eligibility(top_level) != (True, "ok"):
            return top_level
        return FastPathEligibility(
            **{**top_level.__dict__, "lines": self._collect_fast_path_line_facts(
                bg_image=bg_image,
                start_time_by_idx=start_time_by_idx,
                cpu_experimental=False,
            )}
        )

    def _build_cpu_fast_path_eligibility(
        self,
        *,
        scene_duration: float,
        bg_image: Optional[str],
        generate_no_sub_video: bool,
        start_time_by_idx: Dict[int, float],
    ) -> FastPathEligibility:
        top_level = self._top_level_fast_path_facts(
            scene_duration=scene_duration,
            bg_image=bg_image,
            generate_no_sub_video=generate_no_sub_video,
        )
        return FastPathEligibility(
            **{**top_level.__dict__, "lines": self._collect_fast_path_line_facts(
                bg_image=bg_image,
                start_time_by_idx=start_time_by_idx,
                cpu_experimental=True,
            )}
        )

    def _can_use_simple_scene_fast_path(
        self,
        *,
        scene_duration: float,
        bg_image: Optional[str],
        generate_no_sub_video: bool,
        start_time_by_idx: Dict[int, float],
    ) -> tuple[bool, str]:
        if not self.hw_kind:
            if not self._cpu_fast_path_enabled():
                # Preserve the historical CPU short-circuit: no line asset/layout I/O.
                return False, "cpu_encoder"
            return evaluate_cpu_fast_path_eligibility(
                self._build_cpu_fast_path_eligibility(
                    scene_duration=scene_duration,
                    bg_image=bg_image,
                    generate_no_sub_video=generate_no_sub_video,
                    start_time_by_idx=start_time_by_idx,
                )
            )
        return evaluate_fast_path_eligibility(
            self._build_fast_path_eligibility(
                scene_duration=scene_duration,
                bg_image=bg_image,
                generate_no_sub_video=generate_no_sub_video,
                start_time_by_idx=start_time_by_idx,
            )
        )
