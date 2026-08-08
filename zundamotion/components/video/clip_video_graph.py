"""Build the video side of a clip filter graph."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING, Union

from ...utils.ffmpeg_filter_strings import build_scale_opencl_filter
from ...utils.ffmpeg_hw import get_hw_filter_mode
from ...utils.ffmpeg_ops import (
    build_background_filter_complex,
    build_background_fit_steps,
    calculate_overlay_position,
)
from ...utils.filter_presets import get_video_filter_chain
from ...utils.subtitle_text import is_effective_subtitle_text
from ...utils.logger import logger
from .clip.characters import build_character_overlays
from .clip.face import apply_face_overlays
from .clip.effects import resolve_background_effects, resolve_screen_effects
from .clip_filter_policy import ClipFilterPolicy
from .clip_input_collection import ClipInputCollection

if TYPE_CHECKING:
    from .renderer import VideoRenderer


def _to_offset_expr(value: Any) -> str:
    if isinstance(value, (int, float)):
        return str(value)
    if value is None:
        return "0"
    return str(value)


@dataclass
class ClipVideoGraph:
    filter_complex_parts: List[str]
    subtitle_png_path: Optional[Path]


def _build_background_graph(
    *,
    renderer: "VideoRenderer",
    inputs: ClipInputCollection,
    background_config: Dict[str, Any],
    duration: float,
    policy: ClipFilterPolicy,
    force_cpu: bool,
    parts: List[str],
) -> tuple[str, Optional[str]]:
    width = renderer.video_params.width
    height = renderer.video_params.height
    fps = renderer.video_params.fps
    pre_scaled = bool(background_config.get("pre_scaled", False))
    opencl_upload_label: Optional[str] = None

    if pre_scaled:
        parts.append("[0:v]null[bg]")
    elif policy.use_cuda_filters:
        parts.append("[0:v]format=rgba,hwupload_cuda[hw_bg_in]")
        parts.append(
            f"[hw_bg_in]{renderer.scale_filter}={width}:{height}"
            f"{(f',fps={fps}' if renderer.apply_fps_filter else '')}[bg]"
        )
    elif policy.use_gpu_scale_only:
        if renderer.scale_only_backend == "opencl":
            parts.append("[0:v]format=rgba,hwupload[hw_bg_in]")
            parts.append(
                f"[hw_bg_in]{build_scale_opencl_filter(width, height)}"
                f"{(f',fps={fps}' if renderer.apply_fps_filter else '')}[bg_gpu_scaled]"
            )
            parts.append("[bg_gpu_scaled]hwdownload,format=rgba[bg]")
        else:
            parts.append("[0:v]format=rgba,hwupload_cuda[hw_bg_in]")
            parts.append(
                f"[hw_bg_in]{renderer.scale_filter}={width}:{height}"
                f"{(f',fps={fps}' if renderer.apply_fps_filter else '')}[bg_gpu_scaled]"
            )
            parts.append("[bg_gpu_scaled]hwdownload,format=rgba[bg]")
    else:
        fit_steps = build_background_fit_steps(
            width=width,
            height=height,
            fit_mode=inputs.background_fit,
            fill_color=inputs.fill_color,
            anchor=inputs.background_anchor,
            offset_x=inputs.offset_x_expr,
            offset_y=inputs.offset_y_expr,
            scale_flags=renderer.scale_flags,
        )
        parts.extend(
            build_background_filter_complex(
                input_label="0:v",
                output_label="bg",
                steps=fit_steps,
                apply_fps=renderer.apply_fps_filter,
                fps=fps,
            )
        )
        if (
            renderer.gpu_overlay_backend == "opencl"
            and not force_cpu
            and (
                get_hw_filter_mode() != "cpu"
                or renderer.allow_opencl_overlay_in_cpu_mode
            )
        ):
            opencl_upload_label = "[bg_gpu]"

    bg_stream_label = "[bg]"
    bg_effect_snippet = resolve_background_effects(
        effects=policy.background_effects,
        input_label=bg_stream_label,
        duration=duration,
        width=width,
        height=height,
        id_prefix="bg",
    )
    if bg_effect_snippet:
        parts.extend(bg_effect_snippet.filter_chain)
        if bg_effect_snippet.output_label:
            bg_stream_label = bg_effect_snippet.output_label

    video_filter = background_config.get("video_filter")
    if video_filter:
        chain = get_video_filter_chain(str(video_filter))
        if chain:
            filtered_label = "[bg_filtered]"
            parts.append(f"{bg_stream_label}{','.join(chain)}{filtered_label}")
            bg_stream_label = filtered_label

    if opencl_upload_label:
        parts.append(f"{bg_stream_label}format=rgba,hwupload{opencl_upload_label}")
    return bg_stream_label, opencl_upload_label


def _append_insert_overlay(
    *,
    renderer: "VideoRenderer",
    inputs: ClipInputCollection,
    insert_config: Optional[Dict[str, Any]],
    policy: ClipFilterPolicy,
    force_cpu: bool,
    parts: List[str],
    overlay_streams: List[str],
    overlay_filters: List[str],
) -> None:
    if not insert_config or inputs.insert_ffmpeg_index == -1:
        return

    scale = float(insert_config.get("scale", 1.0))
    anchor = insert_config.get("anchor", "middle_center")
    pos = insert_config.get("position", {"x": "0", "y": "0"})
    video_input = f"[{inputs.insert_ffmpeg_index}:v]"
    if not inputs.insert_is_image and abs(inputs.insert_speed - 1.0) > 1e-6:
        parts.append(
            f"{video_input}setpts=PTS/{inputs.insert_speed:.6f}[insert_speed_v]"
        )
        video_input = "[insert_speed_v]"
    x_expr, y_expr = calculate_overlay_position(
        "W", "H", "w", "h", anchor,
        str(pos.get("x", "0")), str(pos.get("y", "0")),
    )

    if policy.use_cuda_filters:
        pixel_format = "rgba" if inputs.insert_is_image else "nv12"
        parts.append(
            f"{video_input}format={pixel_format},hwupload_cuda,"
            f"{renderer.scale_filter}=iw*{scale}:ih*{scale}[insert_scaled]"
        )
        overlay_streams.append("[insert_scaled]")
        overlay_filters.append(f"overlay_cuda=x={x_expr}:y={y_expr}")
    elif (
        renderer.gpu_overlay_backend == "opencl"
        and not force_cpu
        and (
            get_hw_filter_mode() != "cpu"
            or renderer.allow_opencl_overlay_in_cpu_mode
        )
    ):
        parts.append(f"{video_input}scale=iw*{scale}:ih*{scale}[insert_scaled]")
        parts.append("[insert_scaled]format=rgba,hwupload[insert_gpu]")
        overlay_streams.append("[insert_gpu]")
        overlay_filters.append(f"overlay_opencl=x={x_expr}:y={y_expr}")
    else:
        parts.append(
            f"{video_input}scale=iw*{scale}:ih*{scale}:"
            f"flags={renderer.scale_flags}[insert_scaled]"
        )
        overlay_streams.append("[insert_scaled]")
        overlay_filters.append(f"overlay=x={x_expr}:y={y_expr}")


def _image_layer_steps(
    renderer: "VideoRenderer",
    overlay: Dict[str, Any],
    duration: float,
) -> List[str]:
    scale_cfg = overlay.get("scale", 1.0)
    scale_steps: List[str] = []
    if isinstance(scale_cfg, dict):
        width = scale_cfg.get("w")
        height = scale_cfg.get("h")
        if width and height:
            if scale_cfg.get("keep_aspect"):
                scale_steps.append(
                    f"scale={width}:{height}:flags={renderer.scale_flags}:"
                    f"force_original_aspect_ratio=decrease,pad={width}:{height}:"
                    "(ow-iw)/2:(oh-ih)/2:color=0x00000000"
                )
            else:
                scale_steps.append(
                    f"scale={width}:{height}:flags={renderer.scale_flags}"
                )
    else:
        try:
            scale_value = float(scale_cfg)
        except Exception:
            scale_value = 1.0
        scale_steps.append(
            f"scale=iw*{scale_value}:ih*{scale_value}:flags={renderer.scale_flags}"
        )

    steps: List[str] = ["format=rgba"]
    if bool(overlay.get("opaque", True)):
        steps.append("colorchannelmixer=aa=1")

    fade_in = overlay.get("fade_in") or {}
    if isinstance(fade_in, dict) and fade_in.get("type") == "fade":
        try:
            fade_duration = float(fade_in.get("duration", 0.0))
        except Exception:
            fade_duration = 0.0
        if fade_duration > 0:
            steps.append(f"fade=t=in:st=0.000:d={fade_duration:.3f}:alpha=1")

    fade_out = overlay.get("fade_out") or {}
    if isinstance(fade_out, dict) and fade_out.get("type") == "fade":
        try:
            fade_duration = float(fade_out.get("duration", 0.0))
        except Exception:
            fade_duration = 0.0
        if fade_duration > 0:
            start = max(0.0, float(duration) - fade_duration) if fade_out.get("align") == "end" else 0.0
            steps.append(f"fade=t=out:st={start:.3f}:d={fade_duration:.3f}:alpha=1")

    if overlay.get("opacity") is not None:
        try:
            opacity = float(overlay.get("opacity"))
        except Exception:
            opacity = 1.0
        opacity = max(0.0, min(1.0, opacity))
        steps.append(f"lut=a='val*{opacity:.6f}'")
    steps.extend(scale_steps)
    return steps


def _append_image_layer_overlays(
    *,
    renderer: "VideoRenderer",
    inputs: ClipInputCollection,
    duration: float,
    parts: List[str],
    overlay_streams: List[str],
    overlay_filters: List[str],
) -> None:
    for overlay_index, overlay in enumerate(inputs.image_layer_inputs):
        ff_idx = overlay.get("_ff_idx")
        if ff_idx is None:
            continue
        label = f"[img_layer_{overlay_index}]"
        parts.append(
            f"[{ff_idx}:v]{','.join(_image_layer_steps(renderer, overlay, duration))}{label}"
        )
        anchor = overlay.get("anchor", "middle_center")
        pos = overlay.get("position", {"x": "0", "y": "0"}) or {}
        x_expr, y_expr = calculate_overlay_position(
            "W", "H", "w", "h", str(anchor),
            _to_offset_expr(pos.get("x", "0")),
            _to_offset_expr(pos.get("y", "0")),
        )
        overlay_streams.append(label)
        overlay_filters.append(f"overlay=x={x_expr}:y={y_expr}")


def _append_overlay_chain(
    *,
    renderer: "VideoRenderer",
    bg_stream_label: str,
    current_video_stream: str,
    overlay_streams: List[str],
    overlay_filters: List[str],
    force_cpu: bool,
    parts: List[str],
) -> str:
    if not overlay_streams:
        return bg_stream_label

    if (
        renderer.gpu_overlay_backend == "opencl"
        and not force_cpu
        and get_hw_filter_mode() != "cpu"
    ):
        overlay_filters[:] = [
            item.replace("overlay=", "overlay_opencl=")
            if item.startswith("overlay=") else item
            for item in overlay_filters
        ]
        try:
            renderer.path_counters["opencl_overlay"] += 1
        except Exception:
            pass

    chain = current_video_stream
    for index, stream in enumerate(overlay_streams):
        chain += f"{stream}{overlay_filters[index]}"
        if index < len(overlay_streams) - 1:
            chain += f"[tmp_overlay_{index}];[tmp_overlay_{index}]"
        else:
            chain += "[final_v_overlays]"
    parts.append(chain)

    if (
        renderer.gpu_overlay_backend == "opencl"
        and not force_cpu
        and get_hw_filter_mode() != "cpu"
    ):
        parts.append("[final_v_overlays]hwdownload,format=yuv420p[final_v_overlays_cpu]")
        return "[final_v_overlays_cpu]"
    return "[final_v_overlays]"


async def _append_subtitle_overlay(
    *,
    renderer: "VideoRenderer",
    inputs: ClipInputCollection,
    subtitle_text: Optional[str],
    subtitle_line_config: Optional[Dict[str, Any]],
    subtitle_png_path: Optional[Path],
    duration: float,
    current_video_stream: str,
    policy: ClipFilterPolicy,
    force_cpu: bool,
    parts: List[str],
) -> tuple[str, Optional[Path], Any]:
    if not is_effective_subtitle_text(subtitle_text):
        return current_video_stream, subtitle_png_path, None

    subtitle_snippet = None
    try:
        subtitle_ffmpeg_index = len(inputs.input_layers)
        extra_inputs, subtitle_snippet = await renderer.subtitle_gen.build_subtitle_overlay(
            str(subtitle_text),
            duration,
            subtitle_line_config or {},
            in_label=current_video_stream.strip("[]"),
            index=subtitle_ffmpeg_index,
            force_cpu=force_cpu,
            allow_cuda=policy.use_cuda_filters,
            existing_png_path=str(subtitle_png_path) if subtitle_png_path else None,
        )
        if isinstance(extra_inputs, dict) and extra_inputs.get("-i"):
            loop_value = extra_inputs.get("-loop", "1")
            png_path = extra_inputs["-i"]
            inputs.cmd.extend(["-loop", loop_value, "-i", str(Path(png_path).resolve())])
            inputs.input_layers.append({"type": "video", "index": subtitle_ffmpeg_index})
            try:
                subtitle_png_path = Path(png_path)
            except Exception:
                pass
        else:
            logger.warning(
                "Unexpected subtitle extra inputs: %s. Skipping subtitle overlay.",
                extra_inputs,
            )
            subtitle_snippet = None
        if subtitle_snippet:
            parts.append(subtitle_snippet)
            current_video_stream = f"[with_subtitle_{subtitle_ffmpeg_index}]"
    except Exception as exc:
        logger.warning("Failed to build subtitle overlay snippet: %s", exc)
        subtitle_snippet = None
    return current_video_stream, subtitle_png_path, subtitle_snippet


async def build_clip_video_graph(
    *,
    renderer: "VideoRenderer",
    inputs: ClipInputCollection,
    duration: float,
    background_config: Dict[str, Any],
    characters_config: List[Dict[str, Any]],
    subtitle_text: Optional[str],
    subtitle_line_config: Optional[Dict[str, Any]],
    insert_config: Optional[Dict[str, Any]],
    screen_effects: Optional[List[Any]],
    subtitle_png_path: Optional[Path],
    face_anim: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]],
    audio_delay: float,
    policy: ClipFilterPolicy,
    force_cpu: bool,
) -> ClipVideoGraph:
    parts: List[str] = []
    bg_stream_label, opencl_upload_label = _build_background_graph(
        renderer=renderer,
        inputs=inputs,
        background_config=background_config,
        duration=duration,
        policy=policy,
        force_cpu=force_cpu,
        parts=parts,
    )
    current_video_stream = opencl_upload_label or bg_stream_label
    overlay_streams: List[str] = []
    overlay_filters: List[str] = []

    _append_insert_overlay(
        renderer=renderer,
        inputs=inputs,
        insert_config=insert_config,
        policy=policy,
        force_cpu=force_cpu,
        parts=parts,
        overlay_streams=overlay_streams,
        overlay_filters=overlay_filters,
    )
    _append_image_layer_overlays(
        renderer=renderer,
        inputs=inputs,
        duration=duration,
        parts=parts,
        overlay_streams=overlay_streams,
        overlay_filters=overlay_filters,
    )
    placement = build_character_overlays(
        renderer=renderer,
        characters_config=characters_config,
        duration=duration,
        character_indices=inputs.character_indices,
        char_effective_scale=inputs.char_effective_scale,
        filter_complex_parts=parts,
        overlay_streams=overlay_streams,
        overlay_filters=overlay_filters,
        use_cuda_filters=policy.use_cuda_filters,
        use_opencl=policy.use_opencl_overlays,
        metadata=inputs.char_metadata,
    )

    if isinstance(face_anim, list):
        face_entries = [entry for entry in face_anim if isinstance(entry, dict)]
    elif isinstance(face_anim, dict):
        face_entries = [face_anim]
    else:
        face_entries = []
    for face_entry in face_entries:
        await apply_face_overlays(
            renderer=renderer,
            face_anim=face_entry,
            subtitle_line_config=subtitle_line_config,
            char_overlay_placement=placement,
            duration=duration,
            cmd=inputs.cmd,
            input_layers=inputs.input_layers,
            filter_complex_parts=parts,
            overlay_streams=overlay_streams,
            overlay_filters=overlay_filters,
            audio_delay=audio_delay,
        )

    current_video_stream = _append_overlay_chain(
        renderer=renderer,
        bg_stream_label=bg_stream_label,
        current_video_stream=current_video_stream,
        overlay_streams=overlay_streams,
        overlay_filters=overlay_filters,
        force_cpu=force_cpu,
        parts=parts,
    )
    current_video_stream, subtitle_png_path, subtitle_snippet = await _append_subtitle_overlay(
        renderer=renderer,
        inputs=inputs,
        subtitle_text=subtitle_text,
        subtitle_line_config=subtitle_line_config,
        subtitle_png_path=subtitle_png_path,
        duration=duration,
        current_video_stream=current_video_stream,
        policy=policy,
        force_cpu=force_cpu,
        parts=parts,
    )

    screen_snippet = resolve_screen_effects(
        effects=screen_effects,
        input_label=current_video_stream,
        duration=duration,
        width=renderer.video_params.width,
        height=renderer.video_params.height,
        id_prefix="screen",
    )
    if screen_snippet:
        parts.extend(screen_snippet.filter_chain)
        current_video_stream = screen_snippet.output_label

    used_any_cuda = policy.use_cuda_filters or (
        isinstance(subtitle_snippet, str) and "overlay_cuda" in subtitle_snippet
    )
    if used_any_cuda and renderer.hw_kind == "nvenc":
        parts.append(f"{current_video_stream}null[final_v]")
    else:
        parts.append(
            f"{current_video_stream}setpts=PTS-STARTPTS,format=yuv420p[final_v]"
        )
    return ClipVideoGraph(parts, subtitle_png_path)
