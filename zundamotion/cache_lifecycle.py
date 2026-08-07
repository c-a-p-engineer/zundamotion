"""Cache deletion lifecycle overrides with reason diagnostics."""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Iterable

from .utils.logger import logger


class CacheLifecycleMixin:
    """Delete cache entries physically and report why each lifecycle action occurred."""

    @staticmethod
    def _normalized_companion_paths(path: Path) -> tuple[Path, ...]:
        name = path.name
        if name.startswith("temp_normalized_") and name.endswith(".mp4"):
            return (path.with_suffix(".meta.json"),)
        if name.startswith("temp_normalized_") and name.endswith(".meta.json"):
            return (path.with_name(name[: -len(".meta.json")] + ".mp4"),)
        return ()

    def _delete_cache_path(self, path: Path, *, reason: str) -> bool:
        removed = False
        targets = (path, *self._normalized_companion_paths(path))
        for target in targets:
            try:
                if target.exists():
                    target.unlink()
                    removed = True
            except OSError as exc:
                logger.warning("Failed to delete cache file %s: %s", target.name, exc)
        if removed:
            self._cache_diagnostics.record_deletion(reason)
        return removed

    def record_duration_mismatch_deletion(self, path: Path) -> bool:
        """Delete an invalid cached media file and report duration mismatch explicitly."""
        return self._delete_cache_path(path, reason="duration_mismatch")

    def _remove_expired_files(self, files):
        if self.ttl_hours is None:
            return files
        threshold = time.time() - (self.ttl_hours * 3600)
        remaining = []
        deleted_count = 0
        for item in files:
            path, _size, atime = item
            if atime > threshold:
                remaining.append(item)
                continue
            if self._delete_cache_path(path, reason="ttl_expired"):
                deleted_count += 1
        if deleted_count:
            logger.info(
                "Deleted %d expired cache files (TTL: %s hours).",
                deleted_count,
                self.ttl_hours,
            )
        return [item for item in remaining if item[0].exists()]

    def _enforce_size_limit(self, files):
        if self.max_size_mb is None:
            return
        max_bytes = self.max_size_mb * 1024 * 1024
        current_size = sum(size for path, size, _atime in files if path.exists())
        if current_size <= max_bytes:
            return
        files = sorted(files, key=lambda item: item[2])
        deleted_size = 0
        deleted_count = 0
        for path, size, _atime in files:
            if current_size <= max_bytes:
                break
            if not path.exists():
                continue
            if self._delete_cache_path(path, reason="size_evicted"):
                current_size -= size
                deleted_size += size
                deleted_count += 1
        if deleted_count:
            logger.info(
                "Deleted %d cache files (%.2f MB) to stay within max size limit (%s MB).",
                deleted_count,
                deleted_size / (1024 * 1024),
                self.max_size_mb,
            )

    def _invalidate_exact_patterns(
        self, patterns: Iterable[re.Pattern[str]]
    ) -> list[Path]:
        compiled = tuple(patterns)
        removed: list[Path] = []
        for path in self.cache_dir.iterdir():
            if not path.is_file() or not any(
                pattern.fullmatch(path.name) for pattern in compiled
            ):
                continue
            if self._delete_cache_path(path, reason="manual_refresh_clear"):
                removed.append(path)
        return removed
