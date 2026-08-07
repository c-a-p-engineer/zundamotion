"""Observable CacheManager runtime built on the compatibility implementation."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional

from .cache_base import (
    CacheManager as _BaseCacheManager,
    _IMAGE_CACHE_KEY_SUFFIXES,
)
from .cache_observability import CacheRunDiagnostics
from .cache_signatures import FileSignatureMemo
from .exceptions import CacheError
from .utils import perf_stats
from .utils.logger import logger


class CacheManager(_BaseCacheManager):
    """Public cache manager with run-local signatures and additive diagnostics."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # Base initialization can call cleanup, so diagnostic state exists first.
        self._cache_diagnostics = CacheRunDiagnostics()
        self._signature_memo = FileSignatureMemo(self._cache_diagnostics)
        super().__init__(*args, **kwargs)

    def _cache_key_file_signature(self, file_path: Path) -> Dict[str, Any]:
        stat = file_path.stat()
        if file_path.suffix.lower() in _IMAGE_CACHE_KEY_SUFFIXES:
            return dict(self._signature_memo.image_signature(file_path))
        return {
            "path": str(file_path),
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        }

    def _generate_hash(self, data: Dict[str, Any]) -> str:
        with self._cache_diagnostics.measure("key_serialization_hash"):
            return super()._generate_hash(data)

    async def _refresh_cached_path_once(
        self,
        refresh_token: str,
        cached_path: Path,
        *,
        log_label: str,
    ) -> None:
        existed = self.cache_refresh and cached_path.exists()
        await super()._refresh_cached_path_once(
            refresh_token,
            cached_path,
            log_label=log_label,
        )
        if existed and not cached_path.exists():
            self._cache_diagnostics.record_status("refresh")
            self._cache_diagnostics.record_deletion("manual_refresh_clear")

    def _refresh_cached_path_once_sync(
        self,
        refresh_token: str,
        cached_path: Path,
        *,
        log_label: str,
    ) -> None:
        existed = self.cache_refresh and cached_path.exists()
        super()._refresh_cached_path_once_sync(
            refresh_token,
            cached_path,
            log_label=log_label,
        )
        if existed and not cached_path.exists():
            self._cache_diagnostics.record_status("refresh")
            self._cache_diagnostics.record_deletion("manual_refresh_clear")

    def get_cached_path(
        self,
        key_data: Dict[str, Any],
        file_name: str,
        extension: str,
    ) -> Optional[Path]:
        self._consume_pending_invalidation()
        if self.no_cache:
            self._cache_diagnostics.record_status("disabled")
            return None
        cache_key = self._generate_hash(key_data)
        cached_path = self.cache_dir / f"{file_name}_{cache_key}.{extension}"
        self._refresh_cached_path_once_sync(
            f"get:{file_name}:{cache_key}",
            cached_path,
            log_label="cache",
        )
        with self._cache_diagnostics.measure("path_existence"):
            exists = cached_path.exists()
        if exists:
            logger.info(
                "Cache HIT for %s.%s (key: %s) -> %s",
                file_name,
                extension,
                cache_key[:8],
                cached_path.name,
            )
            perf_stats.incr("cache_hit")
            self._cache_diagnostics.classify_hit(cached_path)
            return cached_path
        logger.info("Cache MISS for %s.%s (key: %s)", file_name, extension, cache_key[:8])
        perf_stats.incr("cache_miss")
        self._cache_diagnostics.record_status("miss")
        return None

    def cache_file(
        self,
        source_path: Path,
        key_data: Dict[str, Any],
        file_name: str,
        extension: str,
    ) -> Path:
        cache_key = self._generate_hash(key_data)
        cached_path = self.cache_dir / f"{file_name}_{cache_key}.{extension}"
        with self._cache_diagnostics.measure("copy_store"):
            shutil.copy(source_path, cached_path)
        perf_stats.incr("cache_write")
        self._cache_diagnostics.mark_write(cached_path)
        logger.debug("Cached file -> %s", cached_path.name)
        self._clean_cache()
        return cached_path

    async def get_or_create(
        self,
        key_data: Dict[str, Any],
        file_name: str,
        extension: str,
        creator_func: Callable[[Path], Awaitable[Path]],
    ) -> Path:
        cache_key = self._generate_hash(key_data)
        cached_path = self.cache_dir / f"{file_name}_{cache_key}.{extension}"
        logger.debug(
            "Attempting to get_or_create for key: %s, expected path: %s",
            cache_key[:8],
            cached_path.name,
        )

        if self.no_cache:
            self._cache_diagnostics.record_status("disabled")
            base_dir = self.ephemeral_dir or self.cache_dir
            temp_output_path = base_dir / f"temp_{file_name}_{cache_key}.{extension}"
            with self._cache_diagnostics.measure("path_existence"):
                temp_exists = temp_output_path.exists()
            if temp_exists:
                logger.info(
                    "Cache disabled: Reusing existing ephemeral output for key %s -> %s",
                    cache_key[:8],
                    temp_output_path.name,
                )
                perf_stats.incr("cache_hit")
                self._cache_diagnostics.record_status("same_run_hit")
                return temp_output_path
            async with self._inflight_lock:
                existing = self._inflight_tasks.get(cache_key)
                if existing is None:
                    logger.info(
                        "Cache disabled. Generating temporary file: (Ephemeral) %s",
                        temp_output_path,
                    )
                    perf_stats.incr("cache_miss")
                    self._cache_diagnostics.record_status("miss")

                    async def _create() -> Path:
                        try:
                            generated_path = await creator_func(temp_output_path)
                            if generated_path != temp_output_path:
                                with self._cache_diagnostics.measure("copy_store"):
                                    shutil.copy(generated_path, temp_output_path)
                                try:
                                    generated_path.unlink()
                                except Exception:
                                    pass
                            return temp_output_path
                        finally:
                            async with self._inflight_lock:
                                self._inflight_tasks.pop(cache_key, None)

                    task = asyncio.create_task(_create())
                    self._inflight_tasks[cache_key] = task
                else:
                    self._cache_diagnostics.record_status("in_flight_wait")
                    task = existing
            return await task

        await self._refresh_cached_path_once(
            f"file:{cache_key}",
            cached_path,
            log_label="cache",
        )
        with self._cache_diagnostics.measure("path_existence"):
            cached_exists = cached_path.exists()
        if cached_exists:
            logger.info(
                "Cache HIT for %s.%s (key: %s) -> %s",
                file_name,
                extension,
                cache_key[:8],
                cached_path.name,
            )
            perf_stats.incr("cache_hit")
            self._cache_diagnostics.classify_hit(cached_path)
            return cached_path

        task_key = f"cache:{cache_key}"
        async with self._inflight_lock:
            existing = self._inflight_tasks.get(task_key)
            if existing is None:
                logger.info(
                    "Cache MISS. Calling creator_func to generate file for %s.%s "
                    "(key: %s) to cache: %s",
                    file_name,
                    extension,
                    cache_key[:8],
                    cached_path.name,
                )
                perf_stats.incr("cache_miss")
                self._cache_diagnostics.record_status("miss")

                async def _create_cached() -> Path:
                    try:
                        with self._cache_diagnostics.measure("path_existence"):
                            exists_after_lock = cached_path.exists()
                        if exists_after_lock:
                            self._cache_diagnostics.classify_hit(cached_path)
                            return cached_path
                        generated_path = await creator_func(cached_path)
                        if generated_path != cached_path:
                            with self._cache_diagnostics.measure("copy_store"):
                                shutil.copy(generated_path, cached_path)
                            generated_path.unlink()
                        logger.debug("Generated and cached file -> %s", cached_path.name)
                        perf_stats.incr("cache_write")
                        self._cache_diagnostics.mark_write(cached_path)
                        self._clean_cache()
                        return cached_path
                    except Exception as exc:
                        raise CacheError(
                            f"Failed to generate or cache file {file_name}.{extension}: {exc}"
                        ) from exc
                    finally:
                        async with self._inflight_lock:
                            self._inflight_tasks.pop(task_key, None)

                task = asyncio.create_task(_create_cached())
                self._inflight_tasks[task_key] = task
            else:
                self._cache_diagnostics.record_status("in_flight_wait")
                task = existing
        return await task
