"""Shared ProcessPoolExecutor lifecycle for subtitle PNG rendering."""

from __future__ import annotations

import atexit
import os
from concurrent.futures import ProcessPoolExecutor

_SUBTITLE_EXECUTOR: ProcessPoolExecutor | None = None
_SUBTITLE_EXECUTOR_WORKERS: int | None = None


def _resolve_subtitle_png_workers() -> int:
    try:
        env_workers = os.getenv("SUB_PNG_WORKERS")
        if env_workers and env_workers.isdigit():
            return max(1, int(env_workers))
        return max(1, (os.cpu_count() or 2) // 2)
    except Exception:
        return 1


def _shutdown_subtitle_executor() -> None:
    global _SUBTITLE_EXECUTOR, _SUBTITLE_EXECUTOR_WORKERS
    if _SUBTITLE_EXECUTOR is None:
        return
    try:
        _SUBTITLE_EXECUTOR.shutdown(wait=False, cancel_futures=True)
    except Exception:
        pass
    _SUBTITLE_EXECUTOR = None
    _SUBTITLE_EXECUTOR_WORKERS = None


def _get_shared_subtitle_executor() -> tuple[ProcessPoolExecutor, int]:
    global _SUBTITLE_EXECUTOR, _SUBTITLE_EXECUTOR_WORKERS
    workers = _resolve_subtitle_png_workers()
    if _SUBTITLE_EXECUTOR is None or _SUBTITLE_EXECUTOR_WORKERS != workers:
        if _SUBTITLE_EXECUTOR is not None:
            _shutdown_subtitle_executor()
        _SUBTITLE_EXECUTOR = ProcessPoolExecutor(max_workers=workers)
        _SUBTITLE_EXECUTOR_WORKERS = workers
        atexit.register(_shutdown_subtitle_executor)
    return _SUBTITLE_EXECUTOR, workers
