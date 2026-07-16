"""Lightweight per-render performance counters."""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections import Counter, defaultdict
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


_CURRENT: ContextVar[Optional["PerfStats"]] = ContextVar("zundamotion_perf_stats", default=None)


class PerfStats:
    """Collect counters needed to judge render performance changes."""

    def __init__(self) -> None:
        self.started_at = time.perf_counter()
        self.run_id = f"{datetime.now().strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:8]}"
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
        self._av_warning_limit = 100
        self.av_warning_items: list[Dict[str, Any]] = []
        self.subtitle_burn_chunks: list[Dict[str, Any]] = []
        self.ffprobe_calls_detail: list[Dict[str, Any]] = []
        self.ffprobe_cache_hits_detail: list[Dict[str, Any]] = []
        self.scene_cache_events: list[Dict[str, Any]] = []
        self.line_clip_items: list[Dict[str, Any]] = []
        self._lock = threading.RLock()

    def incr(self, name: str, value: int = 1) -> None:
        with self._lock:
            self.counters[name] = int(self.counters.get(name, 0)) + int(value)

    def add_ms(self, name: str, value: float) -> None:
        with self._lock:
            self.timings_ms[name] = float(self.timings_ms.get(name, 0.0)) + float(value)

    def record_line_clip(self, item: Dict[str, Any]) -> None:
        """行クリップ取得の内訳を競合なく集約する。"""
        normalized = dict(item)
        for key in (
            "duration_ms",
            "cache_lookup_ms",
            "render_ms",
            "prepare_ms",
            "cache_store_ms",
        ):
            normalized[key] = round(float(normalized.get(key, 0.0) or 0.0), 1)
        with self._lock:
            self.line_clip_items.append(normalized)
            self.counters["line_clips"] = int(self.counters.get("line_clips", 0)) + 1
            self.timings_ms["video_line_clip_ms"] = float(
                self.timings_ms.get("video_line_clip_ms", 0.0)
            ) + normalized["duration_ms"]
            self.timings_ms["video_line_clip_render_ms"] = float(
                self.timings_ms.get("video_line_clip_render_ms", 0.0)
            ) + normalized["render_ms"]
            self.timings_ms["video_line_clip_cache_lookup_ms"] = float(
                self.timings_ms.get("video_line_clip_cache_lookup_ms", 0.0)
            ) + normalized["cache_lookup_ms"]
            self.timings_ms["video_line_clip_cache_store_ms"] = float(
                self.timings_ms.get("video_line_clip_cache_store_ms", 0.0)
            ) + normalized["cache_store_ms"]

    def set_phase_ms(self, phase_name: str, value: float) -> None:
        self.phase_ms[phase_name] = float(value)

    def record_av_warning(self, item: Dict[str, Any]) -> None:
        if len(self.av_warning_items) >= self._av_warning_limit:
            return
        self.av_warning_items.append(dict(item))

    def record_subtitle_burn_chunk(
        self,
        *,
        scene_id: str,
        chunk_index: int,
        chunk_count: int,
        subtitle_count: int,
        input_video_duration: float,
        burn_duration_ms: float,
        output_path: str,
        ffmpeg_call_count: int = 1,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
    ) -> None:
        item: Dict[str, Any] = {
            "scene_id": scene_id,
            "chunk_index": int(chunk_index),
            "chunk_count": int(chunk_count),
            "subtitle_count": int(subtitle_count),
            "duration_sec": round(float(input_video_duration), 3),
            "burn_duration_ms": round(float(burn_duration_ms), 1),
            "ffmpeg_call_count": int(ffmpeg_call_count),
            "output_path": str(output_path),
        }
        if start_time is not None:
            item["start_time"] = round(float(start_time), 3)
        if end_time is not None:
            item["end_time"] = round(float(end_time), 3)
        self.subtitle_burn_chunks.append(item)

    def record_ffprobe_call(
        self,
        *,
        kind: str,
        caller: str,
        path: str,
        elapsed_ms: float,
        cache_hit: bool = False,
    ) -> None:
        item = {
            "kind": str(kind),
            "caller": str(caller or "unknown"),
            "path": str(path),
            "elapsed_ms": round(float(elapsed_ms), 1),
            "cache_hit": bool(cache_hit),
        }
        if cache_hit:
            self.ffprobe_cache_hits_detail.append(item)
        else:
            self.ffprobe_calls_detail.append(item)

    def record_scene_cache_event(
        self,
        *,
        scene_id: str,
        layer: str,
        status: str,
        key: str = "-",
        reason: Optional[str] = None,
        detail: Optional[Dict[str, Any]] = None,
    ) -> None:
        item: Dict[str, Any] = {
            "scene_id": str(scene_id),
            "layer": str(layer),
            "status": str(status),
            "key": str(key),
        }
        if reason:
            item["reason"] = str(reason)
        if detail:
            item["detail"] = dict(detail)
        self.scene_cache_events.append(item)

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

    def _build_av_warning_summary(self) -> Dict[str, Any]:
        by_type = Counter()
        by_operation = Counter()
        for item in self.av_warning_items:
            by_type[str(item.get("type", "unknown"))] += 1
            by_operation[str(item.get("operation", "unknown"))] += 1
        return {
            "total": sum(by_type.values()),
            "by_type": dict(sorted(by_type.items())),
            "by_operation": dict(sorted(by_operation.items())),
            "items": self.av_warning_items,
        }

    def _build_subtitle_burn_summary(self) -> Dict[str, Any]:
        by_scene: Dict[str, Dict[str, Any]] = {}
        for item in self.subtitle_burn_chunks:
            scene_id = str(item.get("scene_id", "unknown"))
            scene_entry = by_scene.setdefault(
                scene_id,
                {
                    "scene_id": scene_id,
                    "subtitle_png": 0,
                    "chunk_count": 0,
                    "total_ms": 0.0,
                    "chunks": [],
                },
            )
            scene_entry["subtitle_png"] += int(item.get("subtitle_count", 0) or 0)
            scene_entry["chunk_count"] += 1
            scene_entry["total_ms"] += float(item.get("burn_duration_ms", 0.0) or 0.0)
            scene_entry["chunks"].append(dict(item))

        by_scene_list = []
        for scene_id in sorted(by_scene):
            scene_entry = by_scene[scene_id]
            scene_entry["total_ms"] = round(float(scene_entry["total_ms"]), 1)
            by_scene_list.append(scene_entry)

        top_chunks = sorted(
            (dict(item) for item in self.subtitle_burn_chunks),
            key=lambda item: float(item.get("burn_duration_ms", 0.0) or 0.0),
            reverse=True,
        )[:5]
        return {
            "total_ms": round(float(self.timings_ms.get("subtitle_burn_ms", 0.0) or 0.0), 1),
            "chunk_count": int(self.counters.get("subtitle_chunks", 0)),
            "subtitle_png": int(self.counters.get("subtitle_png", 0)),
            "by_scene": by_scene_list,
            "top_chunks": top_chunks,
        }

    def _build_ffprobe_summary(self) -> Dict[str, Any]:
        by_caller = Counter()
        top_path_counter: Dict[tuple[str, str], int] = defaultdict(int)
        elapsed_by_caller: Dict[str, float] = defaultdict(float)
        cache_hits_by_caller = Counter()

        for item in self.ffprobe_calls_detail:
            caller = str(item.get("caller", "unknown"))
            path = str(item.get("path", ""))
            kind = str(item.get("kind", "other"))
            by_caller[caller] += 1
            elapsed_by_caller[caller] += float(item.get("elapsed_ms", 0.0) or 0.0)
            top_path_counter[(path, kind)] += 1

        for item in self.ffprobe_cache_hits_detail:
            caller = str(item.get("caller", "unknown"))
            cache_hits_by_caller[caller] += 1

        top_paths = [
            {"path": path, "calls": calls, "kind": kind}
            for (path, kind), calls in sorted(
                top_path_counter.items(),
                key=lambda pair: (-pair[1], pair[0][0], pair[0][1]),
            )[:5]
        ]
        top_callers = [
            {
                "caller": caller,
                "calls": by_caller[caller],
                "elapsed_ms": round(float(elapsed_by_caller[caller]), 1),
            }
            for caller in sorted(
                by_caller,
                key=lambda name: (-by_caller[name], -elapsed_by_caller[name], name),
            )[:5]
        ]
        return {
            "total_calls": int(self.counters.get("ffprobe_calls", 0)),
            "by_kind": {
                "duration": int(self.counters.get("ffprobe_duration_calls", 0)),
                "stream": int(self.counters.get("ffprobe_stream_calls", 0)),
                "other": int(self.counters.get("ffprobe_other_calls", 0)),
            },
            "by_caller": dict(sorted(by_caller.items())),
            "top_paths": top_paths,
            "top_callers": top_callers,
            "cache_hits_by_caller": dict(sorted(cache_hits_by_caller.items())),
        }

    def _build_scene_cache_summary(self) -> Dict[str, Any]:
        by_layer_status = Counter()
        miss_reasons = Counter()
        misses: list[Dict[str, Any]] = []
        for item in self.scene_cache_events:
            layer = str(item.get("layer", "unknown"))
            status = str(item.get("status", "unknown"))
            by_layer_status[f"{layer}:{status}"] += 1
            if status.upper() == "MISS":
                reason = str(item.get("reason", "unknown"))
                miss_reasons[reason] += 1
                if len(misses) < 50:
                    misses.append(dict(item))
        return {
            "total_events": len(self.scene_cache_events),
            "by_layer_status": dict(sorted(by_layer_status.items())),
            "miss_reasons": dict(sorted(miss_reasons.items())),
            "misses": misses,
        }

    @staticmethod
    def _percentile(values: list[float], ratio: float) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        position = (len(ordered) - 1) * ratio
        lower = int(position)
        upper = min(len(ordered) - 1, lower + 1)
        weight = position - lower
        return ordered[lower] * (1.0 - weight) + ordered[upper] * weight

    def _build_line_clip_summary(self) -> Dict[str, Any]:
        with self._lock:
            items = [dict(item) for item in self.line_clip_items]
        durations = [float(item.get("duration_ms", 0.0) or 0.0) for item in items]
        total_ms = sum(durations)
        cache_hits = sum(1 for item in items if item.get("cache_status") == "hit")
        cache_misses = len(items) - cache_hits
        top = sorted(
            items,
            key=lambda item: float(item.get("duration_ms", 0.0) or 0.0),
            reverse=True,
        )[:10]
        return {
            "line_clip_count": len(items),
            "line_clip_cache_hit_count": cache_hits,
            "line_clip_cache_miss_count": cache_misses,
            "line_clip_total_ms": round(total_ms, 1),
            "line_clip_render_ms": round(
                sum(float(item.get("render_ms", 0.0) or 0.0) for item in items), 1
            ),
            "line_clip_cache_lookup_ms": round(
                sum(float(item.get("cache_lookup_ms", 0.0) or 0.0) for item in items), 1
            ),
            "line_clip_cache_store_ms": round(
                sum(float(item.get("cache_store_ms", 0.0) or 0.0) for item in items), 1
            ),
            "line_clip_average_ms": round(total_ms / len(items), 1) if items else 0.0,
            "line_clip_p50_ms": round(self._percentile(durations, 0.50), 1),
            "line_clip_p95_ms": round(self._percentile(durations, 0.95), 1),
            "line_clip_max_ms": round(max(durations), 1) if durations else 0.0,
            "items": items,
            "slowest": top,
        }

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = dict(self.counters)
        data["run_id"] = self.run_id
        data["intermediate_files"] = int(self.intermediate_files)
        data["intermediate_size_mb"] = round(self.intermediate_size_bytes / (1024 * 1024), 3)
        data.update({key: round(value, 1) for key, value in self.timings_ms.items()})
        data["phase_ms"] = {key: round(value, 1) for key, value in self.phase_ms.items()}
        data["total_wall_ms"] = round((time.perf_counter() - self.started_at) * 1000.0, 1)
        data["av_warnings"] = self._build_av_warning_summary()
        data["subtitle_burn"] = self._build_subtitle_burn_summary()
        data["ffprobe"] = self._build_ffprobe_summary()
        data["scene_cache"] = self._build_scene_cache_summary()
        line_clips = self._build_line_clip_summary()
        data["line_clip"] = line_clips
        for key, value in line_clips.items():
            if key not in {"items", "slowest"}:
                data[key] = value
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


def record_line_clip(item: Dict[str, Any]) -> None:
    stats = current_perf_stats()
    if stats is not None:
        stats.record_line_clip(item)


def record_scene_cache_event(
    *,
    scene_id: str,
    layer: str,
    status: str,
    key: str = "-",
    reason: Optional[str] = None,
    detail: Optional[Dict[str, Any]] = None,
) -> None:
    stats = current_perf_stats()
    if stats is not None:
        stats.record_scene_cache_event(
            scene_id=scene_id,
            layer=layer,
            status=status,
            key=key,
            reason=reason,
            detail=detail,
        )
