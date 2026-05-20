"""Lightweight per-render performance counters."""

from __future__ import annotations

import json
import time
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Dict, Optional


_CURRENT: ContextVar[Optional["PerfStats"]] = ContextVar("zundamotion_perf_stats", default=None)


class PerfStats:
    """Collect counters needed to judge render performance changes."""

    def __init__(self) -> None:
        self.started_at = time.perf_counter()
        self.counters: Dict[str, int] = {
            "ffmpeg_calls": 0,
            "ffprobe_calls": 0,
            "ffprobe_duration_calls": 0,
            "ffprobe_stream_calls": 0,
            "ffprobe_other_calls": 0,
            "line_clips": 0,
            "subtitle_chunks": 0,
            "subtitle_png": 0,
            "cache_hit": 0,
            "cache_miss": 0,
            "cache_write": 0,
        }
        self.timings_ms: Dict[str, float] = {
            "video_line_clip_ms": 0.0,
            "subtitle_burn_ms": 0.0,
            "face_precache_ms": 0.0,
            "scene_concat_ms": 0.0,
        }
        self.phase_ms: Dict[str, float] = {}
        self.intermediate_files = 0
        self.intermediate_size_bytes = 0

    def incr(self, name: str, value: int = 1) -> None:
        self.counters[name] = int(self.counters.get(name, 0)) + int(value)

    def add_ms(self, name: str, value: float) -> None:
        self.timings_ms[name] = float(self.timings_ms.get(name, 0.0)) + float(value)

    def set_phase_ms(self, phase_name: str, value: float) -> None:
        self.phase_ms[phase_name] = float(value)

    def scan_intermediates(self, temp_dir: Path) -> None:
        count = 0
        size = 0
        if temp_dir.exists():
            for path in temp_dir.rglob("*"):
                try:
                    if path.is_file():
                        count += 1
                        size += path.stat().st_size
                except OSError:
                    continue
        self.intermediate_files = count
        self.intermediate_size_bytes = size

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = dict(self.counters)
        data["intermediate_files"] = int(self.intermediate_files)
        data["intermediate_size_mb"] = round(self.intermediate_size_bytes / (1024 * 1024), 3)
        data.update({key: round(value, 1) for key, value in self.timings_ms.items()})
        data["phase_ms"] = {key: round(value, 1) for key, value in self.phase_ms.items()}
        data["total_wall_ms"] = round((time.perf_counter() - self.started_at) * 1000.0, 1)
        return data

    def write_json(self, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )


def start_perf_stats() -> PerfStats:
    stats = PerfStats()
    _CURRENT.set(stats)
    return stats


def current_perf_stats() -> Optional[PerfStats]:
    return _CURRENT.get()


def incr(name: str, value: int = 1) -> None:
    stats = current_perf_stats()
    if stats is not None:
        stats.incr(name, value)


def add_ms(name: str, value: float) -> None:
    stats = current_perf_stats()
    if stats is not None:
        stats.add_ms(name, value)
