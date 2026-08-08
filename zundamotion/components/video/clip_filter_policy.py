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
    """Filter backend choice derived from clip inputs and renderer capabilities."""

    global_mode: str
    use_cuda_filters: bool
    use_gpu_scale_only: bool
    use_opencl_overlays: bool
    uses_alpha_overlay: bool
    background_effects: Optional[List[Any]]


def resolve_clip_filter_policy(
    *,
    renderer: "VideoRenderer",
    inputs: ClipInputCollection,
    background_config: Dict[str, Any],
    insert_config: Optional[Dict[str, Any]],
    subtitle_text: Optional[str],
    background_effects: Optional[List[Any]],
    force_cpu: bool,
) -> ClipFilterPolicy:
    """Choose the same filter backend as the historical inline renderer logic."""

    resolved_background_effects = background_effects or background_config.get("effects")
    uses_alpha_overlay = (
        inputs.any_character_visible
        or bool(insert_config and inputs.insert_is_image)
        or bool(inputs.image_layer_inputs)
        or is_effective_subtitle_text(subtitle_text)
    )

    global_mode = get_hw_filter_mode()
    use_cuda_filters = (
        renderer.has_cuda_filters
        and renderer.hw_kind == "nvenc"
        and (renderer.gpu_overlay_experimental or not uses_alpha_overlay)
        and not force_cpu
        and global_mode != "cpu"
    )
    allow_gpu_scale_only_cfg = bool(
        renderer.config.get("video", {}).get("gpu_scale_with_cpu_overlay", True)
    )
    allow_in_cpu_mode = renderer.cuda_scale_only_ok
    scale_only_available = bool(
        renderer.scale_only_backend
        or renderer.has_gpu_scale
        or renderer.has_cuda_filters
    )
    use_gpu_scale_only = (
        (not use_cuda_filters)
        and scale_only_available
        and renderer.hw_kind == "nvenc"
        and allow_gpu_scale_only_cfg
        and (not force_cpu)
        and ((global_mode != "cpu") or allow_in_cpu_mode)
    )

    if resolved_background_effects:
        if use_cuda_filters or use_gpu_scale_only:
            logger.info(
                "[Effects] Background effects requested; falling back to CPU-compatible overlay path."
            )
        use_cuda_filters = False
        use_gpu_scale_only = False

    if inputs.requires_cpu_fit and (use_cuda_filters or use_gpu_scale_only):
        logger.info(
            "[Filters] Background fit '%s' requires CPU filters; disabling GPU background scaling.",
            inputs.background_fit,
        )
        use_cuda_filters = False
        use_gpu_scale_only = False

    if use_cuda_filters:
        logger.info("[Filters] CUDA path: scaling/overlay on GPU (no RGBA overlays)")
        try:
            renderer.path_counters["cuda_overlay"] += 1
        except Exception:
            pass
    elif use_gpu_scale_only:
        logger.info(
            "[Filters] Hybrid path: GPU scale + CPU overlay (background only)%s",
            " [cpu-mode-override]" if global_mode == "cpu" else "",
        )
        try:
            renderer.path_counters["gpu_scale_only"] += 1
        except Exception:
            pass
    elif renderer.hw_kind == "nvenc" and uses_alpha_overlay:
        logger.info(
            "[Filters] CPU path: RGBA overlays detected; forcing CPU overlays while keeping NVENC encoding"
        )
        try:
            renderer.path_counters["cpu"] += 1
        except Exception:
            pass
    else:
        logger.info("[Filters] CPU path: using CPU filters for scaling/overlay")
        try:
            renderer.path_counters["cpu"] += 1
        except Exception:
            pass

    use_opencl_overlays = (
        renderer.gpu_overlay_backend == "opencl"
        and not force_cpu
        and (
            get_hw_filter_mode() != "cpu"
            or renderer.allow_opencl_overlay_in_cpu_mode
        )
    )

    return ClipFilterPolicy(
        global_mode=global_mode,
        use_cuda_filters=use_cuda_filters,
        use_gpu_scale_only=use_gpu_scale_only,
        use_opencl_overlays=use_opencl_overlays,
        uses_alpha_overlay=uses_alpha_overlay,
        background_effects=resolved_background_effects,
    )
