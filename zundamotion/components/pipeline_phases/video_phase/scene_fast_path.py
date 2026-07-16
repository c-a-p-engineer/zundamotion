"""Eligibility, state calculation, and rendering for the simple-scene fast path.

This module is an internal SceneRenderer mixin; use scene_renderer.SceneRenderer.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from ....exceptions import PipelineError
from ....utils.ffmpeg_hw import get_profile_flags
from ....utils.ffmpeg_ops import (
    BACKGROUND_FIT_STRETCH,
    build_background_filter_complex,
    build_background_fit_steps,
    calculate_overlay_position,
)
from ....utils.ffmpeg_runner import run_ffmpeg_async as _run_ffmpeg_async
from ....utils.logger import logger
from ....utils.subtitle_text import is_effective_subtitle_text
from ...video.clip.face import _enable_expr, _resolve_face_asset
from ...video.clip.movement import (
    build_dynamic_scale_filter,
    build_move_expressions,
    build_scale_expression,
)


class SceneFastPathMixin:
    """Render eligible static-background talk scenes in one FFmpeg graph."""

    @staticmethod
    def _escape_overlay_expr(expr: str) -> str:
        return str(expr).replace(",", "\\,")

    def _resolve_char_base_image(self, name: str, expression: str) -> Optional[Path]:
        base_dir = Path(f"assets/characters/{name}")
        candidates = [
            base_dir / expression / "base.png",
            base_dir / f"{expression}.png",
            base_dir / "default" / "base.png",
            base_dir / "default.png",
        ]
        for candidate in candidates:
            try:
                if candidate.exists():
                    return candidate
            except Exception:
                continue
        return None

    def _extract_simple_character_state(
        self, line: Dict[str, Any]
    ) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
        visible = [ch for ch in (line.get("characters") or []) if ch.get("visible", False)]
        if not visible:
            return None, "no_visible_character"
        if len(visible) != 1:
            return None, "multiple_visible_characters"
        char = dict(visible[0])
        if char.get("color_filter") is not None:
            return None, "color_filter_requires_standard_renderer"
        name = char.get("name")
        if not name:
            return None, "missing_character_name"
        expression = str(char.get("expression", "default"))
        image_path = self._resolve_char_base_image(str(name), expression)
        if image_path is None:
            return None, f"missing_character_asset:{name}/{expression}"
        try:
            from PIL import Image as _PILImage  # type: ignore

            with _PILImage.open(image_path) as image:
                source_width, source_height = image.size
        except Exception:
            return None, f"invalid_character_asset:{name}/{expression}"
        try:
            scale = float(char.get("scale", 1.0))
        except Exception:
            scale = 1.0
        anchor = str(char.get("anchor", "bottom_center"))
        position = char.get("position") or {"x": "0", "y": "0"}
        return (
            {
                "name": str(name),
                "expression": expression,
                "image_path": image_path,
                "source_width": source_width,
                "source_height": source_height,
                "scale": scale,
                "anchor": anchor,
                "position": {
                    "x": str(position.get("x", "0")),
                    "y": str(position.get("y", "0")),
                },
                "enter": char.get("enter"),
                "enter_duration": char.get("enter_duration", 0.3),
                "leave": char.get("leave"),
                "leave_duration": char.get("leave_duration", 0.3),
                "move": char.get("move"),
            },
            None,
        )

    def _character_signature(self, char_state: Dict[str, Any]) -> tuple[Any, ...]:
        return (
            char_state.get("name"),
            char_state.get("expression"),
            Path(str(char_state.get("image_path"))).resolve(),
            float(char_state.get("scale", 1.0)),
            str(char_state.get("anchor", "bottom_center")),
            str((char_state.get("position") or {}).get("x", "0")),
            str((char_state.get("position") or {}).get("y", "0")),
            repr(char_state.get("move")),
        )

    def _compute_global_char_position(
        self,
        char_state: Dict[str, Any],
        *,
        start_time: float,
        end_time: float,
    ) -> Dict[str, Any]:
        x_base, y_base = calculate_overlay_position(
            "W",
            "H",
            "w",
            "h",
            str(char_state.get("anchor", "bottom_center")),
            str((char_state.get("position") or {}).get("x", "0")),
            str((char_state.get("position") or {}).get("y", "0")),
        )

        def _normalize_effect(raw: Any) -> str:
            if not raw:
                return ""
            return str(raw).lower() if not isinstance(raw, bool) else "fade"

        def _to_float(value: Any, fallback: float) -> float:
            try:
                return float(value)
            except Exception:
                return fallback

        enter_effect = _normalize_effect(char_state.get("enter"))
        leave_effect = _normalize_effect(char_state.get("leave"))
        enter_duration = _to_float(char_state.get("enter_duration", 0.3), 0.3)
        leave_duration = _to_float(char_state.get("leave_duration", 0.3), 0.3)
        leave_start = max(start_time, end_time - leave_duration)

        fade_filters: List[str] = []
        if enter_effect == "fade" and enter_duration > 0:
            fade_filters.append(f"fade=t=in:st={start_time:.3f}:d={enter_duration:.3f}:alpha=1")
        if leave_effect == "fade" and leave_duration > 0:
            fade_filters.append(f"fade=t=out:st={leave_start:.3f}:d={leave_duration:.3f}:alpha=1")

        x_expr, y_expr, _move_dynamic = build_move_expressions(
            move_config=char_state.get("move"),
            anchor=str(char_state.get("anchor", "bottom_center")),
            from_position=None,
            to_position=char_state.get("position") or {},
            to_x_expr=x_base,
            to_y_expr=y_base,
            time_base=start_time,
        )
        try:
            final_scale = float(char_state.get("scale", 1.0))
        except Exception:
            final_scale = 1.0
        scale_expr, scale_dynamic = build_scale_expression(
            move_config=char_state.get("move"),
            to_scale=final_scale,
            time_base=start_time,
        )
        if enter_effect == "slide_left" and enter_duration > 0:
            x_expr = (
                f"if(lt(t,{start_time + enter_duration:.3f}), "
                f"-w+({x_base}+w)*(t-{start_time:.3f})/{enter_duration:.3f}, {x_expr})"
            )
        elif enter_effect == "slide_right" and enter_duration > 0:
            x_expr = (
                f"if(lt(t,{start_time + enter_duration:.3f}), "
                f"W+({x_base}-W)*(t-{start_time:.3f})/{enter_duration:.3f}, {x_expr})"
            )
        elif enter_effect == "slide_top" and enter_duration > 0:
            y_expr = (
                f"if(lt(t,{start_time + enter_duration:.3f}), "
                f"-h+({y_base}+h)*(t-{start_time:.3f})/{enter_duration:.3f}, {y_expr})"
            )
        elif enter_effect == "slide_bottom" and enter_duration > 0:
            y_expr = (
                f"if(lt(t,{start_time + enter_duration:.3f}), "
                f"H+({y_base}-H)*(t-{start_time:.3f})/{enter_duration:.3f}, {y_expr})"
            )

        if leave_effect == "slide_left" and leave_duration > 0:
            x_expr = (
                f"if(gt(t,{leave_start:.3f}), "
                f"{x_base} + (-w-{x_base})*(t-{leave_start:.3f})/{leave_duration:.3f}, {x_expr})"
            )
        elif leave_effect == "slide_right" and leave_duration > 0:
            x_expr = (
                f"if(gt(t,{leave_start:.3f}), "
                f"{x_base} + (W-{x_base})*(t-{leave_start:.3f})/{leave_duration:.3f}, {x_expr})"
            )
        elif leave_effect == "slide_top" and leave_duration > 0:
            y_expr = (
                f"if(gt(t,{leave_start:.3f}), "
                f"{y_base} + (-h-{y_base})*(t-{leave_start:.3f})/{leave_duration:.3f}, {y_expr})"
            )
        elif leave_effect == "slide_bottom" and leave_duration > 0:
            y_expr = (
                f"if(gt(t,{leave_start:.3f}), "
                f"{y_base} + (H-{y_base})*(t-{leave_start:.3f})/{leave_duration:.3f}, {y_expr})"
            )

        return {
            "x_expr": self._escape_overlay_expr(x_expr),
            "y_expr": self._escape_overlay_expr(y_expr),
            "enter_effect": enter_effect,
            "leave_effect": leave_effect,
            "enter_duration": enter_duration,
            "fade_filters": fade_filters,
            "scale_expr": scale_expr,
            "scale_dynamic": scale_dynamic,
        }

    def _can_use_simple_scene_fast_path(
        self,
        *,
        scene_duration: float,
        bg_image: Optional[str],
        generate_no_sub_video: bool,
        start_time_by_idx: Dict[int, float],
    ) -> tuple[bool, str]:
        subtitle_gen = self.video_renderer.subtitle_gen
        subtitle_mode_resolver = getattr(
            subtitle_gen, "resolve_render_mode_for_line_configs", None
        )
        if callable(subtitle_mode_resolver):
            scene_subtitle_mode = subtitle_mode_resolver(
                [
                    (self.line_data_map.get(f"{self.scene['id']}_{idx}") or {}).get(
                        "line_config", {}
                    )
                    for idx, _line in enumerate(self.scene.get("lines", []) or [], start=1)
                ]
            )
        else:
            scene_subtitle_mode = subtitle_gen.subtitle_render_mode()

        if not self.hw_kind:
            return False, "cpu_encoder"
        if generate_no_sub_video:
            return False, "generate_no_sub_enabled"
        if not bg_image or Path(bg_image).suffix.lower() in self.video_extensions:
            return False, "scene_background_not_static_image"
        if (self.scene.get("fg_overlays") or []) or any(line.get("fg_overlays") for line in self.scene.get("lines", [])):
            return False, "foreground_overlays_present"
        if scene_duration <= 0:
            return False, "empty_scene"
        if scene_subtitle_mode == "png":
            return False, "subtitle_render_mode_png"

        lines = self.scene.get("lines", []) or []
        for idx, line in enumerate(lines, start=1):
            line_id = f"{self.scene['id']}_{idx}"
            line_data = self.line_data_map.get(line_id) or {}
            if line_data.get("type") != "talk":
                return False, f"non_talk_line:{idx}"
            if line.get("insert") or line.get("image_layers"):
                return False, f"complex_line_media:{idx}"
            if line.get("voice_layers"):
                return False, f"voice_layers:{idx}"
            if line.get("screen_effects") or line.get("background_effects"):
                return False, f"effects:{idx}"
            if line.get("video_filter") or self.scene.get("video_filter"):
                return False, f"video_filter:{idx}"
            bg_layout = self._resolve_background_layout(line_data.get("line_config") or {})
            if bg_layout["fit"] != BACKGROUND_FIT_STRETCH:
                return False, f"background_fit:{idx}"
            line_bg = self._resolve_background_source(line_data.get("line_config") or {}, bg_image)
            if not line_bg:
                return False, f"missing_background:{idx}"
            if Path(line_bg).suffix.lower() in self.video_extensions:
                return False, f"line_background_video:{idx}"
            if start_time_by_idx.get(idx) is None:
                return False, f"missing_start_time:{idx}"
            _char_state, reason = self._extract_simple_character_state(line)
            if reason:
                return False, f"character:{idx}:{reason}"

        return True, "ok"

    async def _render_simple_scene_fast(
        self,
        *,
        scene_id: str,
        bg_default: str,
        scene_duration: float,
        start_time_by_idx: Dict[int, float],
        scene_hash_data: Dict[str, Any],
    ) -> Optional[Path]:
        lines = self.scene.get("lines", []) or []
        if not lines:
            return None

        output_path = self.temp_dir / f"scene_output_{scene_id}.mp4"
        cmd: List[str] = [
            self.video_renderer.ffmpeg_path,
            "-y",
            "-hide_banner",
            "-loglevel",
            "warning",
            *get_profile_flags(),
        ]
        cmd.extend(self.video_renderer.ffmpeg_thread_flags())

        filter_parts: List[str] = []
        subtitle_entries: List[Dict[str, Any]] = []
        current_stream = "[bg_base]"
        next_input_index = 0

        bg_changes: List[Dict[str, Any]] = []
        char_intervals: List[Dict[str, Any]] = []
        face_overlays: List[Dict[str, Any]] = []
        audio_specs: List[Dict[str, Any]] = []
        character_input_idx = 0
        face_input_idx = 0

        def _add_looped_image_input(path: Path) -> int:
            nonlocal next_input_index
            cmd.extend(
                [
                    "-loop",
                    "1",
                    "-framerate",
                    str(self.video_params.fps),
                    "-t",
                    f"{scene_duration:.3f}",
                    "-i",
                    str(path.resolve()),
                ]
            )
            idx = next_input_index
            next_input_index += 1
            return idx

        first_bg_path_str = self._resolve_background_source(lines[0], bg_default)
        if not first_bg_path_str:
            raise PipelineError(f"Scene '{scene_id}' does not define a background.")
        first_bg_path = Path(first_bg_path_str)
        _add_looped_image_input(first_bg_path)

        base_layout = self._resolve_background_layout(lines[0])
        base_steps = build_background_fit_steps(
            width=self.video_params.width,
            height=self.video_params.height,
            fit_mode=base_layout["fit"],
            fill_color=base_layout["fill_color"],
            anchor=base_layout["anchor"],
            offset_x=base_layout["position"]["x"],
            offset_y=base_layout["position"]["y"],
            scale_flags=self.video_renderer.scale_flags,
        )
        filter_parts.extend(
            build_background_filter_complex(
                input_label="0:v",
                output_label="bg_fitted_0",
                steps=base_steps,
                apply_fps=self.video_renderer.apply_fps_filter,
                fps=self.video_params.fps,
            )
        )
        filter_parts.append(
            f"[bg_fitted_0]trim=duration={scene_duration:.3f}[bg_base]"
        )

        current_bg = str(first_bg_path.resolve())
        current_char_state: Optional[Dict[str, Any]] = None
        current_char_start = 0.0
        current_char_count = 0

        def _append_character_interval(end_time: float) -> None:
            nonlocal current_char_state
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
            face_anims = face_anim_raw if isinstance(face_anim_raw, list) else ([face_anim_raw] if face_anim_raw else [])
            for face_anim in face_anims:
                target_name = str((face_anim or {}).get("target_name") or "")
                if not target_name or not current_char_state or current_char_state.get("name") != target_name:
                    continue
                scale = float(current_char_state.get("scale", 1.0))
                expression = str(current_char_state.get("expression", "default"))
                placement = self._compute_global_char_position(
                    current_char_state,
                    start_time=line_start,
                    end_time=line_end,
                )
                enter_effect = placement.get("enter_effect", "")
                enter_duration_val = float(placement.get("enter_duration", 0.0) or 0.0)
                delayed_effects = {"fade", "slide_left", "slide_right", "slide_top", "slide_bottom"}
                start_offset = (line_start + enter_duration_val) if (enter_effect in delayed_effects and enter_duration_val > 0.0) else 0.0
                mouth_time_shift = line_start + pre_dur
                fade_filters = list(placement.get("fade_filters") or [])

                def _append_face_overlay(asset_path: Path, enable_expr: Optional[str]) -> None:
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
                eyes_close_expr = _enable_expr(eyes_segments, time_shift=line_start) if eyes_segments else None
                _append_face_overlay(
                    _resolve_face_asset(base_dir, expression, "eyes", "close.png"),
                    eyes_close_expr,
                )

                mouth_segments = (face_anim or {}).get("mouth") or []
                half_segments = [seg for seg in mouth_segments if seg.get("state") == "half"]
                open_segments = [seg for seg in mouth_segments if seg.get("state") == "open"]
                half_expr = _enable_expr(
                    half_segments,
                    start_offset=start_offset,
                    time_shift=mouth_time_shift,
                ) if half_segments else None
                open_expr = _enable_expr(
                    open_segments,
                    start_offset=start_offset,
                    time_shift=mouth_time_shift,
                ) if open_segments else None
                _append_face_overlay(
                    _resolve_face_asset(base_dir, expression, "mouth", "half.png"),
                    half_expr,
                )
                _append_face_overlay(
                    _resolve_face_asset(base_dir, expression, "mouth", "open.png"),
                    open_expr,
                )

        _append_character_interval(scene_duration)

        bg_overlay_count = 0
        for bg_change in bg_changes:
            input_idx = _add_looped_image_input(bg_change["path"])
            layout = bg_change["layout"]
            fitted_label = f"bg_fitted_{bg_overlay_count + 1}"
            bg_steps = build_background_fit_steps(
                width=self.video_params.width,
                height=self.video_params.height,
                fit_mode=layout["fit"],
                fill_color=layout["fill_color"],
                anchor=layout["anchor"],
                offset_x=layout["position"]["x"],
                offset_y=layout["position"]["y"],
                scale_flags=self.video_renderer.scale_flags,
            )
            filter_parts.extend(
                build_background_filter_complex(
                    input_label=f"{input_idx}:v",
                    output_label=fitted_label,
                    steps=bg_steps,
                    apply_fps=self.video_renderer.apply_fps_filter,
                    fps=self.video_params.fps,
                )
            )
            next_stream = f"[bg_mix_{bg_overlay_count}]"
            filter_parts.append(
                f"{current_stream}[{fitted_label}]overlay="
                f"x=0:y=0:enable='gte(t,{float(bg_change['start']):.3f})'"
                f"{next_stream}"
            )
            current_stream = next_stream
            bg_overlay_count += 1

        for interval in char_intervals:
            state = interval["state"]
            input_idx = _add_looped_image_input(Path(str(state["image_path"])))
            position = self._compute_global_char_position(
                state,
                start_time=float(interval["start"]),
                end_time=float(interval["end"]),
            )
            try:
                scale = float(state.get("scale", 1.0))
            except Exception:
                scale = 1.0
            char_label = f"char_src_{character_input_idx}"
            if position["scale_dynamic"]:
                scale_step = build_dynamic_scale_filter(
                    scale_expr=str(position["scale_expr"]),
                    move_config=state.get("move"),
                    to_scale=scale,
                    source_width=int(state["source_width"]),
                    source_height=int(state["source_height"]),
                    anchor=str(state["anchor"]),
                    scale_flags=self.video_renderer.scale_flags,
                )
            else:
                scale_step = (
                    f"scale=iw*{scale}:ih*{scale}:"
                    f"flags={self.video_renderer.scale_flags}"
                )
            steps = [
                "format=rgba",
                scale_step,
            ]
            steps.extend(position["fade_filters"])
            filter_parts.append(f"[{input_idx}:v]{','.join(steps)}[{char_label}]")
            next_stream = f"[char_mix_{current_char_count}]"
            filter_parts.append(
                f"{current_stream}[{char_label}]overlay="
                f"x={position['x_expr']}:y={position['y_expr']}:"
                f"enable='between(t,{float(interval['start']):.3f},{float(interval['end']):.3f})'"
                f"{next_stream}"
            )
            current_stream = next_stream
            character_input_idx += 1
            current_char_count += 1

        for face in face_overlays:
            input_idx = _add_looped_image_input(face["path"])
            face_label = f"face_src_{face_input_idx}"
            if face["scale_dynamic"]:
                scale_step = build_dynamic_scale_filter(
                    scale_expr=str(face["scale_expr"]),
                    move_config=face.get("move"),
                    to_scale=float(face["scale"]),
                    source_width=int(face["source_width"]),
                    source_height=int(face["source_height"]),
                    anchor=str(face["anchor"]),
                    scale_flags=self.video_renderer.scale_flags,
                )
            else:
                scale_step = (
                    f"scale=iw*{float(face['scale']):.6f}:"
                    f"ih*{float(face['scale']):.6f}:"
                    f"flags={self.video_renderer.scale_flags}"
                )
            steps = [
                "format=rgba",
                scale_step,
            ]
            steps.extend(face.get("fade_filters") or [])
            filter_parts.append(f"[{input_idx}:v]{','.join(steps)}[{face_label}]")
            next_stream = f"[face_mix_{face_input_idx}]"
            filter_parts.append(
                f"{current_stream}[{face_label}]overlay="
                f"x={face['x_expr']}:y={face['y_expr']}:"
                f"enable='{face['enable']}'{next_stream}"
            )
            current_stream = next_stream
            face_input_idx += 1

        if subtitle_entries:
            subtitle_entries.sort(key=lambda item: item["start"])
            ass_path = self.video_renderer.subtitle_gen.build_ass_subtitle_file(
                subtitle_entries,
                self.temp_dir / f"{scene_id}_fast.ass",
            )
            filter_parts.append(
                f"{current_stream}{self.video_renderer._build_ass_filter(ass_path)}[scene_fast_sub]"
            )
            current_stream = "[scene_fast_sub]"

        audio_input_labels: List[str] = []
        if audio_specs:
            for audio_spec in audio_specs:
                cmd.extend(["-i", str(Path(audio_spec["path"]).resolve())])
                audio_input_index = next_input_index
                next_input_index += 1
                audio_label = f"a_line_{audio_spec['line_idx']}"
                filter_parts.append(
                    f"[{audio_input_index}:a]adelay={int(audio_spec['delay_ms'])}|{int(audio_spec['delay_ms'])},asetpts=PTS-STARTPTS[{audio_label}]"
                )
                audio_input_labels.append(f"[{audio_label}]")
            if len(audio_input_labels) == 1:
                filter_parts.append(
                    f"{audio_input_labels[0]}apad=whole_dur={scene_duration:.3f},atrim=duration={scene_duration:.3f}[scene_fast_audio]"
                )
            else:
                filter_parts.append(
                    "".join(audio_input_labels)
                    + f"amix=inputs={len(audio_input_labels)}:normalize=0,"
                    + f"apad=whole_dur={scene_duration:.3f},atrim=duration={scene_duration:.3f}[scene_fast_audio]"
                )
        else:
            cmd.extend(
                [
                    "-f",
                    "lavfi",
                    "-i",
                    f"anullsrc=channel_layout=stereo:sample_rate={self.audio_params.sample_rate}",
                ]
            )
            null_audio_index = next_input_index
            filter_parts.append(
                f"[{null_audio_index}:a]atrim=duration={scene_duration:.3f},"
                "asetpts=PTS-STARTPTS[scene_fast_audio]"
            )

        filter_parts.append(f"{current_stream}setpts=PTS-STARTPTS[scene_fast_video_out]")
        filter_parts.append(
            "[scene_fast_audio]aresample=async=1:first_pts=0,"
            "asetpts=PTS-STARTPTS[scene_fast_audio_out]"
        )

        cmd.extend(
            [
                "-filter_complex",
                ";".join(filter_parts),
                "-map",
                "[scene_fast_video_out]",
                "-map",
                "[scene_fast_audio_out]",
            ]
        )
        cmd.extend(self.video_params.to_ffmpeg_opts(self.hw_kind))
        cmd.extend(self.audio_params.to_ffmpeg_opts())
        cmd.extend(["-t", f"{scene_duration:.3f}", str(output_path)])

        try:
            await _run_ffmpeg_async(cmd)
        except subprocess.CalledProcessError as exc:
            logger.warning(
                "Scene fast path failed for '%s': %s",
                scene_id,
                (exc.stderr or exc.stdout or "").strip(),
            )
            return None

        self.cache_manager.cache_file(
            source_path=output_path,
            key_data=scene_hash_data,
            file_name=f"scene_{scene_id}",
            extension="mp4",
        )
        logger.info("Scene %s: rendered via simple fast path -> %s", scene_id, output_path.name)
        return output_path
