"""Resolve CPU/GPU filter policy for one clip render."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from ...utils.ffmpeg_hw import get_hw_filter_mode
from ...utils.subtitle_text import is_effective_subtitle_text
from ...utils.logger import logger
from .clip_input_collection import ClipInputCollection

if TYPE_CHECKING:
    from .renderer import VideoRenderer


@dataclass(frozen=True)
class ClipFilterPolicy:
    global_mode: str
    use_cuda_filters: bool
    use_gpu_scale_only: bool
    use_opencl_overlays: bool
    uses_alpha_overlay: bool
    background_effects: Optional[List[Any]]


def _alpha_overlay_required(
    inputs: ClipInputCollection,
    insert_config: Optional[Dict[str, Any]],
    subtitle_text: Optional[str],
) -> bool:
    return (
        inputs.any_character_visible
        or bool(insert_config and inputs.insert_is_image)
        or bool(inputs.image_layer_inputs)
        or is_effective_subtitle_text(subtitle_text)
    )


def _initial_gpu_policy(
    renderer: "VideoRenderer", *, global_mode: str,
    uses_alpha_overlay: bool, force_cpu: bool,
) -> tuple[bool, bool]:
    use_cuda = (
        renderer.has_cuda_filters
        and renderer.hw_kind == "nvenc"
        and (renderer.gpu_overlay_experimental or not uses_alpha_overlay)
        and not force_cpu
        and global_mode != "cpu"
    )
    scale_available = bool(
        renderer.scale_only_backend or renderer.has_gpu_scale or renderer.has_cuda_filters
    )
    allow_scale = bool(
        renderer.config.get("video", {}).get("gpu_scale_with_cpu_overlay", True)
    )
    use_scale_only = (
        not use_cuda and scale_available and renderer.hw_kind == "nvenc"
        and allow_scale and not force_cpu
        and (global_mode != "cpu" or renderer.cuda_scale_only_ok)
    )
    return use_cuda, use_scale_only


def _apply_cpu_constraints(
    *, inputs: ClipInputCollection, background_effects: Optional[List[Any]],
    use_cuda: bool, use_scale_only: bool,
) -> tuple[bool, bool]:
    if background_effects:
        if use_cuda or use_scale_only:
            logger.info("[Effects] Background effects requested; falling back to CPU-compatible overlay path.")
        use_cuda = use_scale_only = False
    if inputs.requires_cpu_fit and (use_cuda or use_scale_only):
        logger.info(
            "[Filters] Background fit '%s' requires CPU filters; disabling GPU background scaling.",
            inputs.background_fit,
        )
        use_cuda = use_scale_only = False
    return use_cuda, use_scale_only


def _record_filter_path(
    renderer: "VideoRenderer", *, global_mode: str, uses_alpha_overlay: bool,
    use_cuda: bool, use_scale_only: bool,
) -> None:
    if use_cuda:
        label, message = "cuda_overlay", "[Filters] CUDA path: scaling/overlay on GPU (no RGBA overlays)"
    elif use_scale_only:
        label = "gpu_scale_only"
        message = "[Filters] Hybrid path: GPU scale + CPU overlay (background only)%s"
        logger.info(message, " [cpu-mode-override]" if global_mode == "cpu" else "")
        try:
            renderer.path_counters[label] += 1
        except Exception:
            pass
        return
    elif renderer.hw_kind == "nvenc" and uses_alpha_overlay:
        label, message = "cpu", "[Filters] CPU path: RGBA overlays detected; forcing CPU overlays while keeping NVENC encoding"
    else:
        label, message = "cpu", "[Filters] CPU path: using CPU filters for scaling/overlay"
    logger.info(message)
    try:
        renderer.path_counters[label] += 1
    except Exception:
        pass


def resolve_clip_filter_policy(
    *, renderer: "VideoRenderer", inputs: ClipInputCollection,
    background_config: Dict[str, Any], insert_config: Optional[Dict[str, Any]],
    subtitle_text: Optional[str], background_effects: Optional[List[Any]],
    force_cpu: bool,
) -> ClipFilterPolicy:
    resolved_effects = background_effects or background_config.get("effects")
    uses_alpha = _alpha_overlay_required(inputs, insert_config, subtitle_text)
    global_mode = get_hw_filter_mode()
    use_cuda, use_scale_only = _initial_gpu_policy(
        renderer, global_mode=global_mode, uses_alpha_overlay=uses_alpha, force_cpu=force_cpu
    )
    use_cuda, use_scale_only = _apply_cpu_constraints(
        inputs=inputs, background_effects=resolved_effects,
        use_cuda=use_cuda, use_scale_only=use_scale_only,
    )
    _record_filter_path(
        renderer, global_mode=global_mode, uses_alpha_overlay=uses_alpha,
        use_cuda=use_cuda, use_scale_only=use_scale_only,
    )
    use_opencl = (
        renderer.gpu_overlay_backend == "opencl" and not force_cpu
        and (global_mode != "cpu" or renderer.allow_opencl_overlay_in_cpu_mode)
    )
    return ClipFilterPolicy(
        global_mode=global_mode, use_cuda_filters=use_cuda,
        use_gpu_scale_only=use_scale_only, use_opencl_overlays=use_opencl,
        uses_alpha_overlay=uses_alpha, background_effects=resolved_effects,
    )
