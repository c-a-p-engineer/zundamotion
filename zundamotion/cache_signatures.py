"""Run-local file fingerprint memo used by CacheManager cache-key generation."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Dict, Tuple

from .cache_observability import CacheRunDiagnostics
from .utils import perf_stats


FileStatKey = Tuple[str, int, int]


class FileSignatureMemo:
    """Memoize SHA-256 by resolved path, mtime_ns, and size.

    The returned cache-key signature remains byte-for-byte compatible with the
    historical CacheManager representation; only digest computation is memoized.
    """

    def __init__(self, diagnostics: CacheRunDiagnostics) -> None:
        self._diagnostics = diagnostics
        self._sha256_by_stat: Dict[FileStatKey, str] = {}
        self._latest_key_by_path: Dict[str, FileStatKey] = {}

    def image_signature(self, file_path: Path) -> dict[str, object]:
        resolved = file_path.resolve()
        stat = resolved.stat()
        path_text = str(resolved)
        key: FileStatKey = (path_text, stat.st_mtime_ns, stat.st_size)
        digest = self._sha256_by_stat.get(key)
        if digest is None:
            perf_stats.incr("cache_signature_memo_miss")
            with self._diagnostics.measure("file_fingerprint"):
                hasher = hashlib.sha256()
                with resolved.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        hasher.update(chunk)
                digest = hasher.hexdigest()
            previous = self._latest_key_by_path.get(path_text)
            if previous is not None and previous != key:
                self._sha256_by_stat.pop(previous, None)
            self._sha256_by_stat[key] = digest
            self._latest_key_by_path[path_text] = key
        else:
            perf_stats.incr("cache_signature_memo_hit")
        return {
            "path": path_text,
            "size": stat.st_size,
            "sha256": digest,
        }
