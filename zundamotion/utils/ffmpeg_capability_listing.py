"""Low-cost FFmpeg version, encoder, and filter capability listings."""

from __future__ import annotations

import os
import re
from typing import Dict, Optional

from .ffmpeg_runner import run_ffmpeg_async as _run_ffmpeg_async
from .logger import logger

_FILTERS_CACHE: Dict[str, str] = {}
_PREFERRED_SCALE_FILTER_CACHE: Dict[str, str] = {}


def get_nproc_value() -> str:
    try:
        value = os.cpu_count() or 1
        if value < 1:
            logger.warning("Could not detect CPU count, defaulting to 1 thread.")
            return "1"
        return str(value)
    except Exception as exc:
        logger.error("Error getting nproc value: %s, defaulting to 1 thread.", exc)
        return "1"


async def get_ffmpeg_version(ffmpeg_path: str = "ffmpeg") -> Optional[str]:
    try:
        result = await _run_ffmpeg_async([ffmpeg_path, "-version"])
        match = re.search(r"ffmpeg version (\S+)", result.stdout)
        return match.group(1) if match else None
    except Exception as exc:
        logger.error("Error getting FFmpeg version: %s", exc)
        return None


async def _list_encoders(ffmpeg_path: str = "ffmpeg") -> str:
    try:
        result = await _run_ffmpeg_async([ffmpeg_path, "-encoders"])
        return result.stdout.lower()
    except Exception as exc:
        logger.error("Error listing FFmpeg encoders: %s", exc)
        return ""


async def _list_ffmpeg_filters(ffmpeg_path: str = "ffmpeg") -> str:
    cached = _FILTERS_CACHE.get(ffmpeg_path)
    if cached is not None:
        return cached
    try:
        result = await _run_ffmpeg_async([ffmpeg_path, "-hide_banner", "-filters"])
        output = result.stdout or ""
        _FILTERS_CACHE[ffmpeg_path] = output
        return output
    except Exception:
        return ""


async def has_cuda_filters(ffmpeg_path: str = "ffmpeg") -> bool:
    try:
        filters = await _list_ffmpeg_filters(ffmpeg_path)
        return "overlay_cuda" in filters and (
            "scale_cuda" in filters or "hwupload_cuda" in filters
        )
    except Exception:
        return False


async def has_gpu_scale_filters(ffmpeg_path: str = "ffmpeg") -> bool:
    try:
        filters = await _list_ffmpeg_filters(ffmpeg_path)
        return "hwupload_cuda" in filters and (
            "scale_cuda" in filters or "scale_npp" in filters
        )
    except Exception:
        return False


async def get_preferred_cuda_scale_filter(ffmpeg_path: str = "ffmpeg") -> str:
    cached = _PREFERRED_SCALE_FILTER_CACHE.get(ffmpeg_path)
    if cached:
        return cached
    filters = await _list_ffmpeg_filters(ffmpeg_path)
    chosen = "scale_cuda" if "scale_cuda" in filters else (
        "scale_npp" if "scale_npp" in filters else "scale_cuda"
    )
    _PREFERRED_SCALE_FILTER_CACHE[ffmpeg_path] = chosen
    return chosen


async def has_opencl_filters(ffmpeg_path: str = "ffmpeg") -> bool:
    try:
        filters = await _list_ffmpeg_filters(ffmpeg_path)
        return "overlay_opencl" in filters and (
            "scale_opencl" in filters or "hwupload" in filters
        )
    except Exception:
        return False
