"""Lifecycle management for the shared subtitle PNG process pool."""

from __future__ import annotations

import logging
from concurrent.futures import ProcessPoolExecutor

logger = logging.getLogger(__name__)


def shutdown_subtitle_executor() -> None:
    """Stop subtitle PNG workers and clear shared module state.

    CPython 3.14 provides ``terminate_workers()`` specifically for process pools
    that do not exit cleanly through normal interpreter shutdown. Zundamotion's
    supported runtime uses that path after all subtitle futures have completed.
    Older runtimes fall back to a blocking ``shutdown()``.
    """

    from . import png as subtitle_png

    executor: ProcessPoolExecutor | None = subtitle_png._SUBTITLE_EXECUTOR
    subtitle_png._SUBTITLE_EXECUTOR = None
    subtitle_png._SUBTITLE_EXECUTOR_WORKERS = None

    if executor is None:
        return

    try:
        terminate_workers = getattr(executor, "terminate_workers", None)
        if callable(terminate_workers):
            terminate_workers()
        else:
            executor.shutdown(wait=True, cancel_futures=True)
    except Exception:
        logger.exception("Failed to shut down subtitle PNG executor cleanly")
