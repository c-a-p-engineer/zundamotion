"""FFmpegコマンドを非同期実行するヘルパー。"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from pathlib import Path
import subprocess
import time
from typing import List, Optional

from .logger import logger


def _guess_ffmpeg_output_path(args: List[str]) -> Optional[Path]:
    if not args:
        return None
    if os.path.basename(str(args[0])).startswith("ffprobe"):
        return None

    for token in reversed(args[1:]):
        value = str(token)
        if not value or value.startswith("-"):
            continue
        if value in {"pipe:1", "pipe:2", "-", "NUL", "/dev/null"}:
            return None
        return Path(value)
    return None


def _format_progress_size(path: Optional[Path]) -> str:
    if path is None:
        return "size:unknown"
    try:
        if not path.exists():
            return "size:pending"
        size = path.stat().st_size
        return f"size:{size / (1024 * 1024):.1f}MB"
    except Exception:
        return "size:unavailable"


def _format_seconds(value: Optional[float]) -> str:
    if value is None:
        return "--"
    seconds = max(0, int(round(value)))
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{sec:02d}"
    if minutes:
        return f"{minutes:d}:{sec:02d}"
    return f"{sec:d}s"


def _progress_percent(elapsed: float, eta: Optional[float]) -> Optional[float]:
    if eta is None:
        return None
    total = elapsed + eta
    if total <= 0:
        return None
    return max(0.0, min(99.9, elapsed / total * 100.0))


class _ProgressState:
    def __init__(self, total_seconds: Optional[float]):
        self.total_seconds = total_seconds if total_seconds and total_seconds > 0 else None
        self.out_time_seconds: Optional[float] = None
        self.last_percent: float = 0.0

    def update(self, key: str, value: str) -> None:
        if key == "out_time_ms":
            try:
                seconds = max(0.0, float(value) / 1_000_000.0)
            except Exception:
                return
            if self.out_time_seconds is None or seconds > self.out_time_seconds:
                self.out_time_seconds = seconds

    def percent(self) -> Optional[float]:
        if self.total_seconds is None or self.out_time_seconds is None:
            return None
        pct = max(0.0, min(99.9, self.out_time_seconds / self.total_seconds * 100.0))
        if pct < self.last_percent:
            pct = self.last_percent
        self.last_percent = pct
        return pct

    def eta(self, elapsed: float) -> Optional[float]:
        pct = self.percent()
        if pct is None or pct <= 0:
            return None
        total_est = elapsed / (pct / 100.0)
        return max(0.0, total_est - elapsed)


def _parse_ffmpeg_target_duration(args: List[str]) -> Optional[float]:
    for i, token in enumerate(args[:-1]):
        if str(token) == "-t":
            try:
                return float(args[i + 1])
            except Exception:
                return None
    return None


def _inject_progress_args(args: List[str]) -> List[str]:
    if not args or not os.path.basename(str(args[0])).startswith("ffmpeg"):
        return args
    if any(str(token) == "-progress" for token in args):
        return args
    injected = [str(args[0]), "-progress", "pipe:1", "-nostats"]
    injected.extend(str(token) for token in args[1:])
    return injected


def _estimate_eta_seconds(
    output_path: Optional[Path],
    last_size: Optional[int],
    last_at: Optional[float],
) -> tuple[Optional[float], Optional[int], Optional[float]]:
    if output_path is None or not output_path.exists():
        return None, last_size, last_at

    try:
        current_size = output_path.stat().st_size
    except Exception:
        return None, last_size, last_at

    now = time.monotonic()
    eta = None
    if last_size is not None and last_at is not None and current_size > last_size:
        elapsed = now - last_at
        delta = current_size - last_size
        if elapsed > 0 and delta > 0:
            growth_per_sec = delta / elapsed
            # Heuristic: current size to roughly 2x current size for long-running subtitle finalize.
            remaining = current_size
            eta = remaining / growth_per_sec if growth_per_sec > 0 else None

    return eta, current_size, now


async def _log_ffmpeg_heartbeat(
    process: asyncio.subprocess.Process,
    base: str,
    output_path: Optional[Path],
    started_at: float,
    interval_sec: float,
    progress: Optional[_ProgressState] = None,
) -> None:
    if interval_sec <= 0:
        return

    last_size: Optional[int] = None
    last_at: Optional[float] = None
    while process.returncode is None:
        await asyncio.sleep(interval_sec)
        if process.returncode is not None:
            break
        elapsed = time.monotonic() - started_at
        eta = progress.eta(elapsed) if progress is not None else None
        pct = progress.percent() if progress is not None else None
        if eta is None:
            eta, last_size, last_at = _estimate_eta_seconds(output_path, last_size, last_at)
        if pct is None:
            pct = _progress_percent(elapsed, eta)
        now_str = time.strftime("%H:%M:%S")
        eta_str = f"ETA:{_format_seconds(eta)}"
        pct_str = f"{pct:5.1f}%" if pct is not None else "  --.-%"
        logger.info(
            "%s | pid:%-5s | +%-5s | %s | %s | %s",
            now_str,
            process.pid,
            _format_seconds(elapsed),
            eta_str,
            f"pct:{pct_str}",
            _format_progress_size(output_path),
        )


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

        args = _inject_progress_args(args)
        cmd_str = " ".join(map(str, args))
        if os.getenv("FFMPEG_LOG_CMD", "0") == "1":
            logger.info(f"Running command: {cmd_str}")
        else:
            logger.debug(f"Running command: {cmd_str}")

        t0 = time.monotonic()
        output_path = _guess_ffmpeg_output_path(args)
        try:
            heartbeat_interval = float(os.getenv("FFMPEG_PROGRESS_LOG_INTERVAL_SEC", "15") or 15)
        except Exception:
            heartbeat_interval = 15.0
        progress = _ProgressState(_parse_ffmpeg_target_duration(args))
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        logger.debug(f"Spawned PID={process.pid} for {base}")
        heartbeat_task = asyncio.create_task(
            _log_ffmpeg_heartbeat(process, base, output_path, t0, heartbeat_interval, progress)
        )

        stdout_chunks: list[bytes] = []
        stderr_chunks: list[bytes] = []

        async def _read_stdout() -> None:
            assert process.stdout is not None
            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                stdout_chunks.append(line)
                text = line.decode(errors="ignore").strip()
                if "=" in text:
                    key, value = text.split("=", 1)
                    progress.update(key.strip(), value.strip())

        async def _read_stderr() -> None:
            assert process.stderr is not None
            while True:
                chunk = await process.stderr.read(4096)
                if not chunk:
                    break
                stderr_chunks.append(chunk)

        stdout_task = asyncio.create_task(_read_stdout())
        stderr_task = asyncio.create_task(_read_stderr())

        try:
            if timeout is not None and timeout > 0:
                await asyncio.wait_for(
                    asyncio.gather(process.wait(), stdout_task, stderr_task),
                    timeout=timeout,
                )
            else:
                await asyncio.gather(process.wait(), stdout_task, stderr_task)
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
        finally:
            heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await heartbeat_task
            for task in (stdout_task, stderr_task):
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task

        stdout_str = b"".join(stdout_chunks).decode(errors="ignore")
        stderr_str = b"".join(stderr_chunks).decode(errors="ignore")

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
