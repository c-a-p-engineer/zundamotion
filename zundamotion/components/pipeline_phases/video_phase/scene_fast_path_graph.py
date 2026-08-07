"""FFmpeg input/filter/command construction for the simple scene fast path.

The builder consumes a semantic plan and returns argv. It never starts a subprocess
or writes to cache.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from ....utils.ffmpeg_hw import get_profile_flags
from ....utils.ffmpeg_ops import (
    build_background_filter_complex,
    build_background_fit_steps,
)
from ...video.clip.movement import build_dynamic_scale_filter


class SceneFastPathGraphMixin:
    """Convert a fast-scene plan into one FFmpeg command."""

    def _build_simple_scene_fast_command(
        self,
        *,
        scene_id: str,
        scene_duration: float,
        output_path: Path,
        plan: Dict[str, Any],
    ) -> List[str]:
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
        current_stream = "[bg_base]"
        next_input_index = 0
        character_input_idx = 0
        face_input_idx = 0
        current_char_count = 0

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

        first_bg_path = Path(plan["first_bg_path"])
        _add_looped_image_input(first_bg_path)
        base_layout = plan["base_layout"]
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

        bg_overlay_count = 0
        for bg_change in plan["background_changes"]:
            input_idx = _add_looped_image_input(Path(bg_change["path"]))
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

        for interval in plan["character_intervals"]:
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
            steps = ["format=rgba", scale_step]
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

        for face in plan["face_overlays"]:
            input_idx = _add_looped_image_input(Path(face["path"]))
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
            steps = ["format=rgba", scale_step]
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

        subtitle_entries = list(plan["subtitle_entries"])
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
        audio_specs = plan["audio_specs"]
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

        filter_parts.append(
            f"{current_stream}setpts=PTS-STARTPTS[scene_fast_video_out]"
        )
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
        return cmd
