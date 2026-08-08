"""Build background filter stages for a clip."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TYPE_CHECKING

from ...utils.ffmpeg_filter_strings import build_scale_opencl_filter
from ...utils.ffmpeg_hw import get_hw_filter_mode
from ...utils.ffmpeg_ops import build_background_filter_complex, build_background_fit_steps
from ...utils.filter_presets import get_video_filter_chain
from .clip.effects import resolve_background_effects
from .clip_filter_policy import ClipFilterPolicy
from .clip_input_collection import ClipInputCollection

if TYPE_CHECKING:
    from .renderer import VideoRenderer


def _append_scaled_background(
    renderer: "VideoRenderer", inputs: ClipInputCollection,
    background_config: Dict[str, Any], policy: ClipFilterPolicy,
    parts: List[str],
) -> None:
    width, height, fps = (
        renderer.video_params.width, renderer.video_params.height, renderer.video_params.fps
    )
    fps_step = f",fps={fps}" if renderer.apply_fps_filter else ""
    if bool(background_config.get("pre_scaled", False)):
        parts.append("[0:v]null[bg]")
        return
    if policy.use_cuda_filters:
        parts.extend([
            "[0:v]format=rgba,hwupload_cuda[hw_bg_in]",
            f"[hw_bg_in]{renderer.scale_filter}={width}:{height}{fps_step}[bg]",
        ])
        return
    if policy.use_gpu_scale_only:
        upload = "hwupload" if renderer.scale_only_backend == "opencl" else "hwupload_cuda"
        scale = build_scale_opencl_filter(width, height) if renderer.scale_only_backend == "opencl" else f"{renderer.scale_filter}={width}:{height}"
        parts.extend([
            f"[0:v]format=rgba,{upload}[hw_bg_in]",
            f"[hw_bg_in]{scale}{fps_step}[bg_gpu_scaled]",
            "[bg_gpu_scaled]hwdownload,format=rgba[bg]",
        ])
        return
    steps = build_background_fit_steps(
        width=width, height=height, fit_mode=inputs.background_fit,
        fill_color=inputs.fill_color, anchor=inputs.background_anchor,
        offset_x=inputs.offset_x_expr, offset_y=inputs.offset_y_expr,
        scale_flags=renderer.scale_flags,
    )
    parts.extend(build_background_filter_complex(
        input_label="0:v", output_label="bg", steps=steps,
        apply_fps=renderer.apply_fps_filter, fps=fps,
    ))


def _append_background_effects(
    renderer: "VideoRenderer", policy: ClipFilterPolicy,
    background_config: Dict[str, Any], duration: float, parts: List[str],
) -> str:
    label = "[bg]"
    snippet = resolve_background_effects(
        effects=policy.background_effects, input_label=label, duration=duration,
        width=renderer.video_params.width, height=renderer.video_params.height,
        id_prefix="bg",
    )
    if snippet:
        parts.extend(snippet.filter_chain)
        if snippet.output_label:
            label = snippet.output_label
    video_filter = background_config.get("video_filter")
    chain = get_video_filter_chain(str(video_filter)) if video_filter else []
    if chain:
        parts.append(f"{label}{','.join(chain)}[bg_filtered]")
        label = "[bg_filtered]"
    return label


def build_background_graph(
    *, renderer: "VideoRenderer", inputs: ClipInputCollection,
    background_config: Dict[str, Any], duration: float,
    policy: ClipFilterPolicy, force_cpu: bool, parts: List[str],
) -> tuple[str, Optional[str]]:
    _append_scaled_background(renderer, inputs, background_config, policy, parts)
    label = _append_background_effects(renderer, policy, background_config, duration, parts)
    opencl_label: Optional[str] = None
    if (
        not background_config.get("pre_scaled", False)
        and not policy.use_cuda_filters and not policy.use_gpu_scale_only
        and renderer.gpu_overlay_backend == "opencl" and not force_cpu
        and (get_hw_filter_mode() != "cpu" or renderer.allow_opencl_overlay_in_cpu_mode)
    ):
        opencl_label = "[bg_gpu]"
        parts.append(f"{label}format=rgba,hwupload{opencl_label}")
    return label, opencl_label
