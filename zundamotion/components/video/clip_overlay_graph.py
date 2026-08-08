"""Build insert, image-layer, and composed overlay filter stages."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TYPE_CHECKING

from ...utils.ffmpeg_hw import get_hw_filter_mode
from ...utils.ffmpeg_ops import calculate_overlay_position
from .clip_filter_policy import ClipFilterPolicy
from .clip_input_collection import ClipInputCollection

if TYPE_CHECKING:
    from .renderer import VideoRenderer


def _offset(value: Any) -> str:
    if isinstance(value, (int, float)):
        return str(value)
    return "0" if value is None else str(value)


def append_insert_overlay(
    *, renderer: "VideoRenderer", inputs: ClipInputCollection,
    insert_config: Optional[Dict[str, Any]], policy: ClipFilterPolicy,
    force_cpu: bool, parts: List[str], streams: List[str], filters: List[str],
) -> None:
    if not insert_config or inputs.insert_ffmpeg_index == -1:
        return
    scale = float(insert_config.get("scale", 1.0))
    pos = insert_config.get("position", {"x": "0", "y": "0"})
    source = f"[{inputs.insert_ffmpeg_index}:v]"
    if not inputs.insert_is_image and abs(inputs.insert_speed - 1.0) > 1e-6:
        parts.append(f"{source}setpts=PTS/{inputs.insert_speed:.6f}[insert_speed_v]")
        source = "[insert_speed_v]"
    x_expr, y_expr = calculate_overlay_position(
        "W", "H", "w", "h", insert_config.get("anchor", "middle_center"),
        str(pos.get("x", "0")), str(pos.get("y", "0")),
    )
    if policy.use_cuda_filters:
        pixel_format = "rgba" if inputs.insert_is_image else "nv12"
        parts.append(
            f"{source}format={pixel_format},hwupload_cuda,"
            f"{renderer.scale_filter}=iw*{scale}:ih*{scale}[insert_scaled]"
        )
        streams.append("[insert_scaled]")
        filters.append(f"overlay_cuda=x={x_expr}:y={y_expr}")
    elif policy.use_opencl_overlays:
        parts.extend([
            f"{source}scale=iw*{scale}:ih*{scale}[insert_scaled]",
            "[insert_scaled]format=rgba,hwupload[insert_gpu]",
        ])
        streams.append("[insert_gpu]")
        filters.append(f"overlay_opencl=x={x_expr}:y={y_expr}")
    else:
        parts.append(
            f"{source}scale=iw*{scale}:ih*{scale}:flags={renderer.scale_flags}[insert_scaled]"
        )
        streams.append("[insert_scaled]")
        filters.append(f"overlay=x={x_expr}:y={y_expr}")


def _scale_steps(renderer: "VideoRenderer", overlay: Dict[str, Any]) -> List[str]:
    scale = overlay.get("scale", 1.0)
    if isinstance(scale, dict):
        width, height = scale.get("w"), scale.get("h")
        if not (width and height):
            return []
        if scale.get("keep_aspect"):
            return [
                f"scale={width}:{height}:flags={renderer.scale_flags}:"
                f"force_original_aspect_ratio=decrease,pad={width}:{height}:"
                "(ow-iw)/2:(oh-ih)/2:color=0x00000000"
            ]
        return [f"scale={width}:{height}:flags={renderer.scale_flags}"]
    try:
        value = float(scale)
    except Exception:
        value = 1.0
    return [f"scale=iw*{value}:ih*{value}:flags={renderer.scale_flags}"]


def _fade_steps(overlay: Dict[str, Any], duration: float) -> List[str]:
    steps: List[str] = []
    fade_in = overlay.get("fade_in") or {}
    if isinstance(fade_in, dict) and fade_in.get("type") == "fade":
        try:
            value = float(fade_in.get("duration", 0.0))
        except Exception:
            value = 0.0
        if value > 0:
            steps.append(f"fade=t=in:st=0.000:d={value:.3f}:alpha=1")
    fade_out = overlay.get("fade_out") or {}
    if isinstance(fade_out, dict) and fade_out.get("type") == "fade":
        try:
            value = float(fade_out.get("duration", 0.0))
        except Exception:
            value = 0.0
        if value > 0:
            start = max(0.0, duration - value) if fade_out.get("align") == "end" else 0.0
            steps.append(f"fade=t=out:st={start:.3f}:d={value:.3f}:alpha=1")
    return steps


def image_layer_steps(
    renderer: "VideoRenderer", overlay: Dict[str, Any], duration: float
) -> List[str]:
    steps = ["format=rgba"]
    if bool(overlay.get("opaque", True)):
        steps.append("colorchannelmixer=aa=1")
    steps.extend(_fade_steps(overlay, duration))
    if overlay.get("opacity") is not None:
        try:
            opacity = float(overlay.get("opacity"))
        except Exception:
            opacity = 1.0
        steps.append(f"lut=a='val*{max(0.0, min(1.0, opacity)):.6f}'")
    steps.extend(_scale_steps(renderer, overlay))
    return steps


def append_image_layer_overlays(
    *, renderer: "VideoRenderer", inputs: ClipInputCollection, duration: float,
    parts: List[str], streams: List[str], filters: List[str],
) -> None:
    for index, overlay in enumerate(inputs.image_layer_inputs):
        ff_idx = overlay.get("_ff_idx")
        if ff_idx is None:
            continue
        label = f"[img_layer_{index}]"
        parts.append(f"[{ff_idx}:v]{','.join(image_layer_steps(renderer, overlay, duration))}{label}")
        pos = overlay.get("position", {"x": "0", "y": "0"}) or {}
        x_expr, y_expr = calculate_overlay_position(
            "W", "H", "w", "h", str(overlay.get("anchor", "middle_center")),
            _offset(pos.get("x", "0")), _offset(pos.get("y", "0")),
        )
        streams.append(label)
        filters.append(f"overlay=x={x_expr}:y={y_expr}")


def append_overlay_chain(
    *, renderer: "VideoRenderer", background_label: str, current_label: str,
    streams: List[str], filters: List[str], force_cpu: bool, parts: List[str],
) -> str:
    if not streams:
        return background_label
    use_opencl = (
        renderer.gpu_overlay_backend == "opencl" and not force_cpu
        and get_hw_filter_mode() != "cpu"
    )
    if use_opencl:
        filters[:] = [
            value.replace("overlay=", "overlay_opencl=") if value.startswith("overlay=") else value
            for value in filters
        ]
        try:
            renderer.path_counters["opencl_overlay"] += 1
        except Exception:
            pass
    chain = current_label
    for index, stream in enumerate(streams):
        chain += f"{stream}{filters[index]}"
        chain += f"[tmp_overlay_{index}];[tmp_overlay_{index}]" if index < len(streams) - 1 else "[final_v_overlays]"
    parts.append(chain)
    if not use_opencl:
        return "[final_v_overlays]"
    parts.append("[final_v_overlays]hwdownload,format=yuv420p[final_v_overlays_cpu]")
    return "[final_v_overlays_cpu]"
