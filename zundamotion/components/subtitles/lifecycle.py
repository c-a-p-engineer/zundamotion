"""Lifecycle management for the shared subtitle PNG process pool."""

from __future__ import annotations

import logging
from concurrent.futures import ProcessPoolExecutor

logger = logging.getLogger(__name__)


def shutdown_subtitle_executor() -> None:
    """Synchronously stop subtitle PNG workers and clear shared module state.

    ``png.py`` keeps one shared ``ProcessPoolExecutor`` for render throughput and
    also registers a non-blocking ``atexit`` fallback. Normal render completion
    must explicitly wait for the workers so the CLI process cannot remain alive
    after the video and sidecars have already been written.
    """

    from . import png as subtitle_png

    executor: ProcessPoolExecutor | None = subtitle_png._SUBTITLE_EXECUTOR
    subtitle_png._SUBTITLE_EXECUTOR = None
    subtitle_png._SUBTITLE_EXECUTOR_WORKERS = None

    if executor is None:
        return

    try:
        executor.shutdown(wait=True, cancel_futures=True)
    except Exception:
        logger.exception("Failed to shut down subtitle PNG executor cleanly")
