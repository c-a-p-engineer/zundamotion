"""Async subprocess lifecycle for FFmpeg and ffprobe."""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import time
from typing import Any, List, Optional

from .ffmpeg_progress import _ProgressState, log_ffmpeg_heartbeat, watch_ffmpeg_stall
from .logger import logger


@dataclass(frozen=True)
class FFmpegProcessResult:
    returncode: int
    stdout: str
    stderr: str
    elapsed_seconds: float
    pid: int


def _parse_target_duration(args: List[str]) -> Optional[float]:
    for index, token in enumerate(args[:-1]):
        if str(token) == "-t":
            try:
                return float(args[index + 1])
            except Exception:
                return None
    return None


def _inject_progress_args(args: List[str]) -> List[str]:
    if not args or not os.path.basename(str(args[0])).startswith("ffmpeg"):
        return list(args)
    if any(str(token) == "-progress" for token in args):
        return list(args)
    return [str(args[0]), "-progress", "pipe:1", "-nostats", *map(str, args[1:])]


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)) or default)
    except Exception:
        return default


async def _read_stdout(
    process: asyncio.subprocess.Process, progress: _ProgressState, chunks: list[bytes]
) -> None:
    assert process.stdout is not None
    while True:
        line = await process.stdout.readline()
        if not line:
            return
        chunks.append(line)
        text = line.decode(errors="ignore").strip()
        if "=" in text:
            key, value = text.split("=", 1)
            progress.update(key.strip(), value.strip())


async def _read_stderr(process: asyncio.subprocess.Process, chunks: list[bytes]) -> None:
    assert process.stderr is not None
    while True:
        chunk = await process.stderr.read(4096)
        if not chunk:
            return
        chunks.append(chunk)


async def _terminate_process(
    process: asyncio.subprocess.Process, *, timeout_value: Any, args: List[str]
) -> None:
    grace = _env_float("FFMPEG_KILL_GRACE_SEC", 5.0)
    logger.error(
        "Command timed out/stalled after %ss (PID=%s). Sending terminate...",
        f"{timeout_value:.1f}" if isinstance(timeout_value, (int, float)) else timeout_value,
        process.pid,
    )
    with contextlib.suppress(Exception):
        process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=max(0.1, grace))
    except asyncio.TimeoutError:
        logger.error(
            "Process did not terminate in %.1fs; killing PID=%s...", grace, process.pid
        )
        with contextlib.suppress(Exception):
            process.kill()
        await process.wait()
    raise subprocess.TimeoutExpired(args, timeout_value)


async def _cancel_process(process: asyncio.subprocess.Process, base: str) -> None:
    logger.warning(
        "Task cancelled while running %s (PID=%s); terminating...", base, process.pid
    )
    with contextlib.suppress(Exception):
        process.terminate()
    with contextlib.suppress(asyncio.TimeoutError, Exception):
        await asyncio.wait_for(process.wait(), timeout=3.0)
    with contextlib.suppress(Exception):
        process.kill()


async def _await_process(
    *,
    process: asyncio.subprocess.Process,
    base: str,
    args: List[str],
    output_path: Optional[Path],
    progress: _ProgressState,
    started_at: float,
    timeout: Optional[float],
    heartbeat_interval: float,
    stall_timeout: float,
    stdout_task: asyncio.Task[None],
    stderr_task: asyncio.Task[None],
) -> None:
    heartbeat = asyncio.create_task(
        log_ffmpeg_heartbeat(
            process, base, output_path, started_at, heartbeat_interval, progress
        )
    )
    stall: Optional[asyncio.Task[None]] = None
    if base.startswith("ffmpeg") and stall_timeout > 0:
        stall = asyncio.create_task(
            watch_ffmpeg_stall(
                process, base, output_path, progress, stall_timeout, heartbeat_interval
            )
        )
    wait_task = asyncio.gather(process.wait(), stdout_task, stderr_task)
    try:
        watches: set[asyncio.Future[Any]] = {wait_task}
        if stall is not None:
            watches.add(stall)
        done, _ = await asyncio.wait(
            watches,
            timeout=timeout if timeout and timeout > 0 else None,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if not done:
            raise asyncio.TimeoutError
        if stall is not None and stall in done and stall.exception() is not None:
            raise stall.exception()  # type: ignore[misc]
        await wait_task
    except (asyncio.TimeoutError, subprocess.TimeoutExpired) as exc:
        await _terminate_process(
            process, timeout_value=getattr(exc, "timeout", timeout), args=args
        )
    except asyncio.CancelledError:
        await _cancel_process(process, base)
        raise
    finally:
        for task in (heartbeat, stall, wait_task, stdout_task, stderr_task):
            if task is None:
                continue
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task


async def execute_ffmpeg_process(
    args: List[str],
    *,
    base: str,
    output_path: Optional[Path],
    timeout: Optional[float],
) -> tuple[List[str], FFmpegProcessResult]:
    """Spawn, monitor, drain, and terminate one FFmpeg/ffprobe process."""
    command = _inject_progress_args(args)
    started_at = time.monotonic()
    heartbeat_interval = _env_float("FFMPEG_PROGRESS_LOG_INTERVAL_SEC", 15.0)
    stall_timeout = _env_float("FFMPEG_STALL_TIMEOUT_SEC", 900.0)
    progress = _ProgressState(_parse_target_duration(command))
    process = await asyncio.create_subprocess_exec(
        *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    logger.debug("Spawned PID=%s for %s", process.pid, base)
    stdout_chunks: list[bytes] = []
    stderr_chunks: list[bytes] = []
    stdout_task = asyncio.create_task(_read_stdout(process, progress, stdout_chunks))
    stderr_task = asyncio.create_task(_read_stderr(process, stderr_chunks))
    await _await_process(
        process=process,
        base=base,
        args=command,
        output_path=output_path,
        progress=progress,
        started_at=started_at,
        timeout=timeout,
        heartbeat_interval=heartbeat_interval,
        stall_timeout=stall_timeout,
        stdout_task=stdout_task,
        stderr_task=stderr_task,
    )
    result = FFmpegProcessResult(
        returncode=process.returncode if process.returncode is not None else 0,
        stdout=b"".join(stdout_chunks).decode(errors="ignore"),
        stderr=b"".join(stderr_chunks).decode(errors="ignore"),
        elapsed_seconds=time.monotonic() - started_at,
        pid=process.pid,
    )
    return command, result
