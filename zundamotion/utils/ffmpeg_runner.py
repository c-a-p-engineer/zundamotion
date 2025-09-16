"""FFmpegコマンドを非同期実行するヘルパー。"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import subprocess
import time
from typing import List, Optional

from .logger import logger


async def run_ffmpeg_async(
    args: List[str], *, timeout: Optional[float] = None, error_log_level: int | None = logging.ERROR
) -> subprocess.CompletedProcess:
    """
    FFmpeg/ffprobe を非同期で起動し、ログとタイムアウトを管理する。

    :param error_log_level: 非0終了コード時に出力するログレベル。
        `None` を指定するとログ出力しない。
    """
    try:
        exe = str(args[0]) if args else "ffmpeg"
        base = os.path.basename(exe)
        if timeout is None and base.startswith("ffmpeg"):
            try:
                env_to = float(os.getenv("FFMPEG_RUN_TIMEOUT_SEC", "0") or 0)
                timeout = env_to if env_to > 0 else None
            except Exception:
                timeout = None

        cmd_str = " ".join(map(str, args))
        if os.getenv("FFMPEG_LOG_CMD", "0") == "1":
            logger.info(f"Running command: {cmd_str}")
        else:
            logger.debug(f"Running command: {cmd_str}")

        t0 = time.monotonic()
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        logger.debug(f"Spawned PID={process.pid} for {base}")

        try:
            if timeout is not None and timeout > 0:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
            else:
                stdout, stderr = await process.communicate()
        except asyncio.TimeoutError:
            grace = 5.0
            try:
                grace = float(os.getenv("FFMPEG_KILL_GRACE_SEC", "5"))
            except Exception:
                grace = 5.0
            logger.error(
                f"Command timed out after {timeout:.1f}s (PID={process.pid}). Sending terminate..."
            )
            with contextlib.suppress(Exception):
                process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=max(0.1, grace))
            except asyncio.TimeoutError:
                logger.error(f"Process did not terminate in {grace:.1f}s; killing PID={process.pid}...")
                with contextlib.suppress(Exception):
                    process.kill()
                await process.wait()
            raise subprocess.TimeoutExpired(args, timeout)
        except asyncio.CancelledError:
            logger.warning(f"Task cancelled while running {base} (PID={process.pid}); terminating...")
            with contextlib.suppress(Exception):
                process.terminate()
            with contextlib.suppress(asyncio.TimeoutError, Exception):
                await asyncio.wait_for(process.wait(), timeout=3.0)
            with contextlib.suppress(Exception):
                process.kill()
            raise

        stdout_str = stdout.decode(errors="ignore")
        stderr_str = stderr.decode(errors="ignore")

        rc = process.returncode if process.returncode is not None else 0
        dt = time.monotonic() - t0
        logger.debug(f"Command finished rc={rc} in {dt:.2f}s (PID={process.pid})")

        if rc != 0:
            if error_log_level is not None:
                logger.log(
                    error_log_level,
                    f"FFmpeg command failed rc={rc}. Command: {cmd_str}",
                )
                if stderr_str:
                    logger.log(error_log_level, f"stderr:\n{stderr_str}")
                if stdout_str:
                    logger.debug(f"stdout:\n{stdout_str}")
            else:
                if stdout_str:
                    logger.debug(f"stdout:\n{stdout_str}")
                if stderr_str:
                    logger.debug(f"stderr:\n{stderr_str}")
            raise subprocess.CalledProcessError(
                rc,
                args,
                output=stdout_str,
                stderr=stderr_str,
            )

        if stderr_str:
            logger.debug(f"FFmpeg stderr (on success):\n{stderr_str}")

        return subprocess.CompletedProcess(args, rc, stdout_str, stderr_str)

    except subprocess.CalledProcessError:
        # 上位で処理される想定（必要に応じてログ済み）
        raise
    except FileNotFoundError:
        logger.error(
            "FFmpeg or FFprobe command not found. Please ensure it's installed and in your PATH."
        )
        raise
    except Exception as e:
        logger.error(f"An unexpected error occurred while running FFmpeg command: {e}")
        raise
