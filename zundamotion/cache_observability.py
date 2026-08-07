"""Run-local cache status, latency, and lifecycle diagnostics.

The diagnostics are additive: existing ``cache_hit`` / ``cache_miss`` /
``cache_write`` counters remain unchanged for compatibility.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .utils import perf_stats


CACHE_STATUSES = {
    "persistent_hit",
    "same_run_hit",
    "in_flight_wait",
    "miss",
    "write",
    "refresh",
    "disabled",
}

CACHE_LATENCY_STAGES = {
    "key_serialization_hash",
    "file_fingerprint",
    "metadata_read_validation",
    "path_existence",
    "copy_store",
}

CACHE_DELETION_REASONS = {
    "ttl_expired",
    "size_evicted",
    "corrupted",
    "duration_mismatch",
    "manual_refresh_clear",
}


class CacheRunDiagnostics:
    """Track run-local cache provenance without changing cache semantics."""

    def __init__(self) -> None:
        self._written_paths: set[str] = set()

    @staticmethod
    def _resolved(path: Path) -> str:
        try:
            return str(path.resolve())
        except Exception:
            return str(path)

    def mark_write(self, path: Path) -> None:
        self._written_paths.add(self._resolved(path))
        self.record_status("write")

    def classify_hit(self, path: Path) -> str:
        status = (
            "same_run_hit"
            if self._resolved(path) in self._written_paths
            else "persistent_hit"
        )
        self.record_status(status)
        return status

    @staticmethod
    def record_status(status: str) -> None:
        if status not in CACHE_STATUSES:
            raise ValueError(f"Unknown cache status: {status}")
        perf_stats.incr(f"cache_status_{status}")

    @staticmethod
    def record_latency(stage: str, elapsed_ms: float) -> None:
        if stage not in CACHE_LATENCY_STAGES:
            raise ValueError(f"Unknown cache latency stage: {stage}")
        perf_stats.incr(f"cache_latency_{stage}_count")
        perf_stats.add_ms(f"cache_latency_{stage}_ms", max(0.0, elapsed_ms))

    @staticmethod
    def record_deletion(reason: str, count: int = 1) -> None:
        if reason not in CACHE_DELETION_REASONS:
            raise ValueError(f"Unknown cache deletion reason: {reason}")
        if count > 0:
            perf_stats.incr(f"cache_delete_{reason}", count)

    @contextmanager
    def measure(self, stage: str) -> Iterator[None]:
        started = time.perf_counter()
        try:
            yield
        finally:
            self.record_latency(stage, (time.perf_counter() - started) * 1000.0)
