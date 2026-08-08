"""Public async FFmpeg/ffprobe execution facade."""

from __future__ import annotations

import logging
import os
import subprocess
from typing import Any, Dict, List, Optional

from .ffmpeg_diagnostics import (
    _classify_ffprobe_call,
    _extract_av_warning_items,
    _guess_ffmpeg_input_paths,
    _guess_ffmpeg_output_path,
    _normalize_warning_type,
    prepare_ffmpeg_context,
    record_av_warnings,
    record_ffprobe_duration,
    record_invocation,
)
from .ffmpeg_process import (
    _inject_progress_args,
    _parse_target_duration as _parse_ffmpeg_target_duration,
    execute_ffmpeg_process,
)
from .ffmpeg_progress import (
    _ProgressState,
    _StallDetector,
    _StallSnapshot,
    _format_progress_size,
    _format_seconds,
    _progress_percent,
    _read_output_size,
)
from .logger import logger


def _default_timeout(base: str, timeout: Optional[float]) -> Optional[float]:
    if timeout is not None or not base.startswith("ffmpeg"):
        return timeout
    try:
        value = float(os.getenv("FFMPEG_RUN_TIMEOUT_SEC", "0") or 0)
        return value if value > 0 else None
    except Exception:
        return None


def _log_command_failure(
    *,
    returncode: int,
    command: List[str],
    stdout: str,
    stderr: str,
    error_log_level: int | None,
) -> None:
    if error_log_level is not None:
        logger.log(
            error_log_level,
            "FFmpeg command failed rc=%s. Command: %s",
            returncode,
            " ".join(map(str, command)),
        )
        if stderr:
            logger.log(error_log_level, "stderr:\n%s", stderr)
        if stdout:
            logger.debug("stdout:\n%s", stdout)
        return
    if stdout:
        logger.debug("stdout:\n%s", stdout)
    if stderr:
        logger.debug("stderr:\n%s", stderr)


async def run_ffmpeg_async(
    args: List[str],
    *,
    timeout: Optional[float] = None,
    error_log_level: int | None = logging.ERROR,
    context: Optional[Dict[str, Any]] = None,
) -> subprocess.CompletedProcess:
    """Run FFmpeg/ffprobe asynchronously with progress, stall, and A/V diagnostics."""
    try:
        executable = str(args[0]) if args else "ffmpeg"
        base = os.path.basename(executable)
        resolved_context = prepare_ffmpeg_context(args, context)
        output_path = _guess_ffmpeg_output_path(args)
        record_invocation(args, base)
        resolved_timeout = _default_timeout(base, timeout)
        command_preview = " ".join(map(str, _inject_progress_args(args)))
        if os.getenv("FFMPEG_LOG_CMD", "0") == "1":
            logger.info("Running command: %s", command_preview)
        else:
            logger.debug("Running command: %s", command_preview)
        command, result = await execute_ffmpeg_process(
            args, base=base, output_path=output_path, timeout=resolved_timeout
        )
        logger.debug(
            "Command finished rc=%s in %.2fs (PID=%s)",
            result.returncode,
            result.elapsed_seconds,
            result.pid,
        )
        record_ffprobe_duration(command, resolved_context, result.elapsed_seconds)
        record_av_warnings(result.stderr, resolved_context, base)
        if result.returncode != 0:
            _log_command_failure(
                returncode=result.returncode,
                command=command,
                stdout=result.stdout,
                stderr=result.stderr,
                error_log_level=error_log_level,
            )
            raise subprocess.CalledProcessError(
                result.returncode, command, output=result.stdout, stderr=result.stderr
            )
        if result.stderr:
            logger.debug("FFmpeg stderr (on success):\n%s", result.stderr)
        return subprocess.CompletedProcess(
            command, result.returncode, result.stdout, result.stderr
        )
    except subprocess.CalledProcessError:
        raise
    except FileNotFoundError:
        logger.error(
            "FFmpeg or FFprobe command not found. Please ensure it's installed and in your PATH."
        )
        raise
    except Exception as exc:
        logger.error("An unexpected error occurred while running FFmpeg command: %s", exc)
        raise


__all__ = [
    "run_ffmpeg_async",
    "_classify_ffprobe_call",
    "_guess_ffmpeg_output_path",
    "_guess_ffmpeg_input_paths",
    "_normalize_warning_type",
    "_extract_av_warning_items",
    "_format_progress_size",
    "_read_output_size",
    "_format_seconds",
    "_progress_percent",
    "_ProgressState",
    "_StallSnapshot",
    "_StallDetector",
    "_parse_ffmpeg_target_duration",
    "_inject_progress_args",
]
