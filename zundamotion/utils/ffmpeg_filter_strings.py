"""FFmpeg filter string helpers (string-only, no subprocess)."""

from __future__ import annotations

from typing import Union

SizeToken = Union[int, str]


def build_scale_opencl_filter(width: SizeToken, height: SizeToken) -> str:
    """Return a scale_opencl filter using named options for FFmpeg 7+ compatibility."""
    return f"scale_opencl=w={width}:h={height}"
