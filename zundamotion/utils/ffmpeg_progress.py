"""FFmpeg progress parsing, heartbeat logging, and stall detection."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
import subprocess
import time
from typing import Optional

from .logger import logger


def _format_progress_size(path: Optional[Path]) -> str:
    if path is None:
        return "size:unknown"
    try:
        if not path.exists():
            return "size:pending"
        return f"size:{path.stat().st_size / (1024 * 1024):.1f}MB"
    except Exception:
        return "size:unavailable"


def _read_output_size(path: Optional[Path]) -> Optional[int]:
    if path is None:
        return None
    try:
        return path.stat().st_size if path.exists() else None
    except Exception:
        return None


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
        self.last_percent = 0.0

    def update(self, key: str, value: str) -> None:
        if key != "out_time_ms":
            return
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
        return max(0.0, elapsed / (pct / 100.0) - elapsed)

    def stall_marker(self) -> Optional[float]:
        return self.out_time_seconds


@dataclass
class _StallSnapshot:
    marker: Optional[float]
    output_size: Optional[int]


class _StallDetector:
    def __init__(self, timeout_sec: float):
        self.timeout_sec = timeout_sec
        self.snapshot: Optional[_StallSnapshot] = None
        self.snapshot_at: Optional[float] = None

    def update(self, snapshot: _StallSnapshot, now: float) -> Optional[float]:
        if self.timeout_sec <= 0 or (
            snapshot.marker is None and snapshot.output_size is None
        ):
            return None
        if self.snapshot != snapshot:
            self.snapshot, self.snapshot_at = snapshot, now
            return None
        if self.snapshot_at is None:
            self.snapshot_at = now
            return None
        stagnant_for = now - self.snapshot_at
        return stagnant_for if stagnant_for >= self.timeout_sec else None


def _estimate_eta_seconds(
    output_path: Optional[Path], last_size: Optional[int], last_at: Optional[float]
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
        elapsed, delta = now - last_at, current_size - last_size
        if elapsed > 0 and delta > 0:
            growth = delta / elapsed
            eta = current_size / growth if growth > 0 else None
    return eta, current_size, now


async def log_ffmpeg_heartbeat(
    process: asyncio.subprocess.Process, base: str, output_path: Optional[Path],
    started_at: float, interval_sec: float, progress: Optional[_ProgressState] = None,
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
        logger.info(
            "%s | pid:%-5s | +%-5s | ETA:%s | pct:%s | %s",
            time.strftime("%H:%M:%S"), process.pid, _format_seconds(elapsed),
            _format_seconds(eta), f"{pct:5.1f}%" if pct is not None else "  --.-%",
            _format_progress_size(output_path),
        )


async def watch_ffmpeg_stall(
    process: asyncio.subprocess.Process, base: str, output_path: Optional[Path],
    progress: _ProgressState, timeout_sec: float, check_interval_sec: float,
) -> None:
    if timeout_sec <= 0:
        return
    interval = max(1.0, min(check_interval_sec if check_interval_sec > 0 else 15.0, 15.0))
    detector = _StallDetector(timeout_sec)
    while process.returncode is None:
        await asyncio.sleep(interval)
        if process.returncode is not None:
            return
        stagnant = detector.update(
            _StallSnapshot(progress.stall_marker(), _read_output_size(output_path)),
            time.monotonic(),
        )
        if stagnant is None:
            continue
        logger.error(
            "[FFmpegStall] %s PID=%s stalled for %.1fs (timeout=%.1fs, marker=%s, output=%s).",
            base, process.pid, stagnant, timeout_sec, progress.stall_marker(),
            _format_progress_size(output_path),
        )
        raise subprocess.TimeoutExpired(
            cmd=[base], timeout=timeout_sec,
            output=f"ffmpeg progress stalled for {stagnant:.1f}s",
        )
