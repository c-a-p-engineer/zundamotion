"""Execute a clip FFmpeg command and apply the legacy CPU fallback policy."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING, Union

from ...utils.ffmpeg_capabilities import _dump_cuda_diag_once
from ...utils.ffmpeg_hw import set_hw_filter_mode
from ...utils.ffmpeg_runner import run_ffmpeg_async as _run_ffmpeg_async
from ...utils.logger import logger

if TYPE_CHECKING:
    from .renderer import VideoRenderer


def _is_gpu_failure(error: subprocess.CalledProcessError) -> bool:
    message = (error.stderr or "") + "\n" + (error.stdout or "")
    return_code = getattr(error, "returncode", None)
    return (
        "exit status 234" in message
        or "exit code 234" in message
        or return_code == 234
        or "exit status 218" in message
        or "exit code 218" in message
        or "h264_nvenc" in message
        or "nvenc" in message.lower()
        or "overlay_cuda" in message
        or "scale_cuda" in message
    )


async def _retry_cpu(
    *,
    renderer: "VideoRenderer",
    retry_kwargs: Dict[str, Any],
) -> Optional[Path]:
    try:
        await _dump_cuda_diag_once(renderer.ffmpeg_path)
    except Exception:
        pass
    try:
        set_hw_filter_mode("cpu")
    except Exception:
        pass

    previous = {
        "DISABLE_HWENC": os.environ.get("DISABLE_HWENC"),
        "FFMPEG_FILTER_THREADS": os.environ.get("FFMPEG_FILTER_THREADS"),
        "FFMPEG_FILTER_COMPLEX_THREADS": os.environ.get("FFMPEG_FILTER_COMPLEX_THREADS"),
        "DISABLE_ALPHA_HARD_THRESHOLD": os.environ.get("DISABLE_ALPHA_HARD_THRESHOLD"),
    }
    os.environ["DISABLE_HWENC"] = "1"
    os.environ["FFMPEG_FILTER_THREADS"] = "1"
    os.environ["FFMPEG_FILTER_COMPLEX_THREADS"] = "1"
    os.environ["DISABLE_ALPHA_HARD_THRESHOLD"] = "1"
    try:
        return await renderer.render_clip(**retry_kwargs, _force_cpu=True)
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


async def execute_clip_command(
    *,
    renderer: "VideoRenderer",
    cmd: List[str],
    output_filename: str,
    output_path: Path,
    started_at: float,
    force_cpu: bool,
    retry_kwargs: Dict[str, Any],
) -> Optional[Path]:
    """Execute FFmpeg, logging diagnostics and retrying GPU failures once on CPU."""

    try:
        logger.debug("Executing FFmpeg command: %s", " ".join(cmd))
        process = await _run_ffmpeg_async(cmd)
        if process.stderr:
            logger.debug("FFmpeg stderr (non-fatal):\n%s", process.stderr.strip())
        try:
            logger.info(
                "[Video] Finished clip %s in %.2fs",
                output_filename,
                time.time() - started_at,
            )
        except Exception:
            pass
        return output_path
    except subprocess.CalledProcessError as error:
        logger.error("ffmpeg failed for %s", output_filename)
        logger.error("FFmpeg STDERR:\n%s", (error.stderr or "").strip())
        logger.error("FFmpeg STDOUT:\n%s", (error.stdout or "").strip())
        if not force_cpu and _is_gpu_failure(error):
            logger.warning(
                "[Fallback] NVENC/CUDA path failed. Retrying with CPU filters/encoder."
            )
            return await _retry_cpu(renderer=renderer, retry_kwargs=retry_kwargs)
        raise
    except Exception as error:
        logger.error("Unexpected exception during ffmpeg: %s", error)
        raise
