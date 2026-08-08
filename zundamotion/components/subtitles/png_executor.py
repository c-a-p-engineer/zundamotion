"""Shared ProcessPoolExecutor lifecycle for subtitle PNG rendering."""

from __future__ import annotations

import atexit
import os
from concurrent.futures import ProcessPoolExecutor


def _resolve_subtitle_png_workers() -> int:
    try:
        env_workers = os.getenv("SUB_PNG_WORKERS")
        if env_workers and env_workers.isdigit():
            return max(1, int(env_workers))
        return max(1, (os.cpu_count() or 2) // 2)
    except Exception:
        return 1


def _subtitle_png_module():
    # Import lazily so the public facade can own the historical shared-state slots
    # without creating an import cycle during module initialization.
    from . import png as subtitle_png

    return subtitle_png


def _shutdown_subtitle_executor() -> None:
    subtitle_png = _subtitle_png_module()
    executor = subtitle_png._SUBTITLE_EXECUTOR
    if executor is None:
        return
    try:
        executor.shutdown(wait=False, cancel_futures=True)
    except Exception:
        pass
    subtitle_png._SUBTITLE_EXECUTOR = None
    subtitle_png._SUBTITLE_EXECUTOR_WORKERS = None


def _get_shared_subtitle_executor() -> tuple[ProcessPoolExecutor, int]:
    subtitle_png = _subtitle_png_module()
    workers = _resolve_subtitle_png_workers()
    if (
        subtitle_png._SUBTITLE_EXECUTOR is None
        or subtitle_png._SUBTITLE_EXECUTOR_WORKERS != workers
    ):
        if subtitle_png._SUBTITLE_EXECUTOR is not None:
            _shutdown_subtitle_executor()
        subtitle_png._SUBTITLE_EXECUTOR = ProcessPoolExecutor(max_workers=workers)
        subtitle_png._SUBTITLE_EXECUTOR_WORKERS = workers
        atexit.register(_shutdown_subtitle_executor)
    return subtitle_png._SUBTITLE_EXECUTOR, workers
