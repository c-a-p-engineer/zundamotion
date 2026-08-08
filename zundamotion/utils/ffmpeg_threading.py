"""FFmpeg process/filter thread policy."""

from __future__ import annotations

import os
from typing import List

from .ffmpeg_capability_listing import get_nproc_value
from .ffmpeg_hw import get_hw_filter_mode


def _threading_flags(ffmpeg_path: str = "ffmpeg") -> List[str]:
    nproc = get_nproc_value()
    threads = os.getenv("FFMPEG_THREADS", "0")
    try:
        cap_ft_env = os.getenv("FFMPEG_FILTER_THREADS_CAP")
        cap_fct_env = os.getenv("FFMPEG_FILTER_COMPLEX_THREADS_CAP")
        cap_ft = int(cap_ft_env) if cap_ft_env and cap_ft_env.isdigit() else None
        cap_fct = int(cap_fct_env) if cap_fct_env and cap_fct_env.isdigit() else None
    except Exception:
        cap_ft = cap_fct = None
    effective_cpu = get_hw_filter_mode() == "cpu"
    default_cap = 4 if effective_cpu else 1
    ft_val = int(nproc)
    fct_val = int(nproc)
    if effective_cpu:
        ft_val = max(1, min(ft_val, default_cap))
        fct_val = max(1, min(fct_val, default_cap))
    else:
        ft_val = fct_val = 1
    if cap_ft is not None:
        ft_val = max(1, min(ft_val, cap_ft))
    if cap_fct is not None:
        fct_val = max(1, min(fct_val, cap_fct))
    return [
        "-threads", threads,
        "-filter_threads", str(ft_val),
        "-filter_complex_threads", str(fct_val),
    ]
