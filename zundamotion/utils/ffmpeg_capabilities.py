# -*- coding: utf-8 -*-
"""Compatibility facade for modular FFmpeg capability detection."""

from .ffmpeg_capability_listing import (
    _list_encoders,
    _list_ffmpeg_filters,
    get_ffmpeg_version,
    get_nproc_value,
    get_preferred_cuda_scale_filter,
    has_cuda_filters,
    has_gpu_scale_filters,
    has_opencl_filters,
)
from .ffmpeg_encoder_capabilities import (
    get_encoder_options,
    get_hardware_encoder_kind,
    get_hw_encoder_kind_for_video_params,
    is_nvenc_available,
    is_qsv_available,
)
from .ffmpeg_filter_smoke import (
    _dump_cuda_diag_once,
    get_filter_diagnostics,
    smoke_test_cuda_filters,
    smoke_test_cuda_scale_only,
    smoke_test_opencl_filters,
    smoke_test_opencl_scale_only,
)
from .ffmpeg_threading import _threading_flags

__all__ = [
    "get_nproc_value",
    "get_ffmpeg_version",
    "_list_encoders",
    "is_nvenc_available",
    "is_qsv_available",
    "has_cuda_filters",
    "_list_ffmpeg_filters",
    "get_preferred_cuda_scale_filter",
    "has_gpu_scale_filters",
    "smoke_test_cuda_scale_only",
    "_dump_cuda_diag_once",
    "smoke_test_cuda_filters",
    "has_opencl_filters",
    "smoke_test_opencl_filters",
    "smoke_test_opencl_scale_only",
    "get_filter_diagnostics",
    "get_hardware_encoder_kind",
    "get_encoder_options",
    "get_hw_encoder_kind_for_video_params",
    "_threading_flags",
]
