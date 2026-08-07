"""State-only render planning for the simple-scene fast path.

The plan resolves scene timeline inputs, character intervals, face overlays,
subtitle entries, and delayed audio specifications. It does not build or execute
an FFmpeg command.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from ....exceptions import PipelineError
from ....utils.subtitle_text import is_effective_subtitle_text
from ...video.clip.face import _enable_expr, _resolve_face_asset


class SceneFastPathPlanMixin:
    """Build the semantic plan consumed by the fast-path FFmpeg graph builder."""

    def _build_simple_scene_fast_plan(
        self,
        *,
        scene_id: str,
        bg_default: str,
        scene_duration: float,
        start_time_by_idx: Dict[int, float],
    ) -> Dict[str, Any]:
        lines = self.scene.get("lines", []) or []
        if not lines:
            raise PipelineError(f"Scene '{scene_id}' has no lines for fast rendering.")

        first_bg_path_str = self._resolve_background_source(lines[0], bg_default)
        if not first_bg_path_str:
            raise PipelineError(f"Scene '{scene_id}' does not define a background.")
        first_bg_path = Path(first_bg_path_str)
        base_layout = self._resolve_background_layout(lines[0])

        subtitle_entries: list[Dict[str, Any]] = []
        bg_changes: list[Dict[str, Any]] = []
        char_intervals: list[Dict[str, Any]] = []
        face_overlays: list[Dict[str, Any]] = []
        audio_specs: list[Dict[str, Any]] = []

        current_bg = str(first_bg_path.resolve())
        current_char_state: Optional[Dict[str, Any]] = None
        current_char_start = 0.0

        def _append_character_interval(end_time: float) -> None:
            if not current_char_state or end_time <= current_char_start:
                return
            char_intervals.append(
                {
                    "state": dict(current_char_state),
                    "start": current_char_start,
                    "end": end_time,
                }
            )

        for idx, line in enumerate(lines, start=1):
            line_id = f"{scene_id}_{idx}"
            line_data = self.line_data_map[line_id]
            line_start = float(start_time_by_idx[idx])
            line_end = line_start + float(line_data["duration"])
            text = line_data.get("text")
            if is_effective_subtitle_text(text):
                subtitle_entries.append(
                    {
                        "text": text,
                        "line_config": line_data.get("line_config", {}),
                        "duration": float(line_data["duration"]),
                        "start": line_start,
                    }
                )

            bg_path_str = self._resolve_background_source(line, bg_default)
            if not bg_path_str:
                raise PipelineError(
                    f"Background is not defined for scene '{scene_id}', line {idx}."
                )
            bg_path = str(Path(bg_path_str).resolve())
            if bg_path != current_bg:
                bg_changes.append(
                    {
                        "path": Path(bg_path),
                        "layout": self._resolve_background_layout(line),
                        "start": line_start,
                    }
                )
                current_bg = bg_path

            char_state, reason = self._extract_simple_character_state(line)
            if reason:
                raise PipelineError(
                    f"Fast scene renderer could not resolve character for scene '{scene_id}', line {idx}: {reason}"
                )
            assert char_state is not None
            char_signature = self._character_signature(char_state)
            if current_char_state is None:
                current_char_state = char_state
                current_char_start = line_start
            elif char_signature != self._character_signature(current_char_state):
                _append_character_interval(line_start)
                current_char_state = char_state
                current_char_start = line_start

            audio_path = Path(str(line_data["audio_path"]))
            pre_dur = float(line_data.get("pre_duration", 0.0))
            adelay_ms = max(0, int(round((line_start + pre_dur) * 1000)))
            audio_specs.append(
                {
                    "path": audio_path,
                    "delay_ms": adelay_ms,
                    "line_idx": idx,
                }
            )

            face_anim_raw = line_data.get("face_anim")
            face_anims = (
                face_anim_raw
                if isinstance(face_anim_raw, list)
                else ([face_anim_raw] if face_anim_raw else [])
            )
            for face_anim in face_anims:
                target_name = str((face_anim or {}).get("target_name") or "")
                if (
                    not target_name
                    or not current_char_state
                    or current_char_state.get("name") != target_name
                ):
                    continue
                scale = float(current_char_state.get("scale", 1.0))
                expression = str(current_char_state.get("expression", "default"))
                placement = self._compute_global_char_position(
                    current_char_state,
                    start_time=line_start,
                    end_time=line_end,
                )
                enter_effect = placement.get("enter_effect", "")
                enter_duration_val = float(
                    placement.get("enter_duration", 0.0) or 0.0
                )
                delayed_effects = {
                    "fade",
                    "slide_left",
                    "slide_right",
                    "slide_top",
                    "slide_bottom",
                }
                start_offset = (
                    line_start + enter_duration_val
                    if enter_effect in delayed_effects and enter_duration_val > 0.0
                    else 0.0
                )
                mouth_time_shift = line_start + pre_dur
                fade_filters = list(placement.get("fade_filters") or [])

                def _append_face_overlay(
                    asset_path: Path, enable_expr: Optional[str]
                ) -> None:
                    if not enable_expr or not asset_path.exists():
                        return
                    face_overlays.append(
                        {
                            "path": asset_path,
                            "scale": scale,
                            "scale_expr": placement["scale_expr"],
                            "scale_dynamic": placement["scale_dynamic"],
                            "source_width": current_char_state["source_width"],
                            "source_height": current_char_state["source_height"],
                            "anchor": current_char_state["anchor"],
                            "move": current_char_state.get("move"),
                            "x_expr": placement["x_expr"],
                            "y_expr": placement["y_expr"],
                            "enable": enable_expr,
                            "fade_filters": fade_filters,
                        }
                    )

                base_dir = Path(f"assets/characters/{target_name}")
                eyes_segments = (face_anim or {}).get("eyes") or []
                eyes_close_expr = (
                    _enable_expr(eyes_segments, time_shift=line_start)
                    if eyes_segments
                    else None
                )
                _append_face_overlay(
                    _resolve_face_asset(
                        base_dir, expression, "eyes", "close.png"
                    ),
                    eyes_close_expr,
                )

                mouth_segments = (face_anim or {}).get("mouth") or []
                half_segments = [
                    seg for seg in mouth_segments if seg.get("state") == "half"
                ]
                open_segments = [
                    seg for seg in mouth_segments if seg.get("state") == "open"
                ]
                half_expr = (
                    _enable_expr(
                        half_segments,
                        start_offset=start_offset,
                        time_shift=mouth_time_shift,
                    )
                    if half_segments
                    else None
                )
                open_expr = (
                    _enable_expr(
                        open_segments,
                        start_offset=start_offset,
                        time_shift=mouth_time_shift,
                    )
                    if open_segments
                    else None
                )
                _append_face_overlay(
                    _resolve_face_asset(
                        base_dir, expression, "mouth", "half.png"
                    ),
                    half_expr,
                )
                _append_face_overlay(
                    _resolve_face_asset(
                        base_dir, expression, "mouth", "open.png"
                    ),
                    open_expr,
                )

        _append_character_interval(scene_duration)
        return {
            "first_bg_path": first_bg_path,
            "base_layout": base_layout,
            "background_changes": bg_changes,
            "character_intervals": char_intervals,
            "face_overlays": face_overlays,
            "subtitle_entries": subtitle_entries,
            "audio_specs": audio_specs,
        }
