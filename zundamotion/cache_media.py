"""Unified media probe cache for CacheManager.

The public ``get_or_create_media_info`` and ``get_or_create_media_duration`` APIs
remain unchanged while both values share one persistent JSON bundle and one
in-flight task.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

from .exceptions import CacheError
from .utils import perf_stats
from .utils.ffmpeg_probe import (
    MediaInfo,
    get_media_duration as _DEFAULT_GET_MEDIA_DURATION,
    get_media_info as _DEFAULT_GET_MEDIA_INFO,
)
from .utils.logger import logger


_PROBE_BUNDLE_SCHEMA_VERSION = 1


def _public_probe_functions():
    """Resolve module-level probe functions so existing monkeypatches keep working."""
    public_module = sys.modules.get("zundamotion.cache")
    info_func = getattr(public_module, "get_media_info", _DEFAULT_GET_MEDIA_INFO)
    duration_func = getattr(
        public_module, "get_media_duration", _DEFAULT_GET_MEDIA_DURATION
    )
    return info_func, duration_func


class CacheMediaProbeMixin:
    """Store stream metadata and duration in one run/persistent cache bundle."""

    def _probe_bundle_path(self, file_path: Path) -> tuple[str, Path]:
        key_data = self._media_probe_cache_key_data(file_path, "media_probe_bundle")
        cache_key = self._generate_hash(key_data)
        return cache_key, self._probe_meta_path("probe", cache_key)

    def _legacy_probe_paths(self, file_path: Path) -> tuple[Path, Path]:
        info_key = self._generate_hash(
            self._media_probe_cache_key_data(file_path, "media_info")
        )
        duration_key = self._generate_hash(
            self._media_probe_cache_key_data(file_path, "media_duration")
        )
        return (
            self._probe_meta_path("info", info_key),
            self._probe_meta_path("duration", duration_key),
        )

    def _read_probe_bundle(self, path: Path) -> Optional[Dict[str, Any]]:
        if not path.exists():
            return None
        try:
            with self._cache_diagnostics.measure("metadata_read_validation"):
                payload = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("probe bundle must be a JSON object")
                if int(payload.get("schema_version", 0)) != _PROBE_BUNDLE_SCHEMA_VERSION:
                    raise ValueError("unsupported probe bundle schema")
                if "duration" not in payload or "media_info" not in payload:
                    raise ValueError("probe bundle is missing required fields")
            return payload
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            logger.warning("Corrupted media probe cache %s: %s. Regenerating.", path.name, exc)
            path.unlink(missing_ok=True)
            self._cache_diagnostics.record_deletion("corrupted")
            return None

    def _read_legacy_probe_bundle(self, file_path: Path) -> Optional[Dict[str, Any]]:
        if self.cache_refresh:
            return None
        info_path, duration_path = self._legacy_probe_paths(file_path)
        media_info: Optional[MediaInfo] = None
        duration: Optional[float] = None
        try:
            with self._cache_diagnostics.measure("metadata_read_validation"):
                if info_path.exists():
                    info_payload = json.loads(info_path.read_text(encoding="utf-8"))
                    candidate = info_payload.get("media_info")
                    if isinstance(candidate, dict):
                        media_info = candidate
                        raw = candidate.get("duration")
                        if raw is not None:
                            duration = float(raw)
                if duration_path.exists():
                    duration_payload = json.loads(duration_path.read_text(encoding="utf-8"))
                    raw = duration_payload.get("duration")
                    if raw is not None:
                        duration = float(raw)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None
        if media_info is None and duration is None:
            return None
        return {
            "schema_version": _PROBE_BUNDLE_SCHEMA_VERSION,
            "media_info": media_info,
            "duration": duration,
            "created_at": time.time(),
            "migrated_from_legacy": True,
        }

    def _write_probe_bundle(self, path: Path, payload: Dict[str, Any]) -> None:
        with self._cache_diagnostics.measure("copy_store"):
            path.write_text(
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
        perf_stats.incr("cache_write")
        self._cache_diagnostics.mark_write(path)
        if not self.no_cache:
            self._clean_cache()

    def _record_probe_cache_hit(
        self,
        *,
        file_path: Path,
        path: Path,
        caller: str,
        kind: str,
    ) -> None:
        perf_stats.incr("cache_hit")
        self._cache_diagnostics.classify_hit(path)
        perf = perf_stats.current_perf_stats()
        if perf is not None:
            perf.record_ffprobe_call(
                kind=kind,
                caller=caller,
                path=str(file_path),
                elapsed_ms=0.0,
                cache_hit=True,
            )

    async def _generate_probe_bundle(
        self,
        file_path: Path,
        *,
        caller: str,
        request_kind: str,
    ) -> Dict[str, Any]:
        info_func, duration_func = _public_probe_functions()
        media_info: Optional[MediaInfo] = None
        duration: Optional[float] = None

        # Existing tests/integrations may monkeypatch only get_media_duration on the
        # public cache module. Honor that injection without forcing ffprobe on fake media.
        duration_is_overridden = duration_func is not _DEFAULT_GET_MEDIA_DURATION
        if request_kind == "duration" and duration_is_overridden:
            duration = float(await duration_func(str(file_path), caller=caller))
        else:
            media_info = await info_func(str(file_path), caller=caller)
            raw_duration = media_info.get("duration") if media_info else None
            if raw_duration is not None:
                duration = float(raw_duration)
            else:
                duration = float(await duration_func(str(file_path), caller=caller))

        return {
            "schema_version": _PROBE_BUNDLE_SCHEMA_VERSION,
            "media_info": media_info,
            "duration": duration,
            "created_at": time.time(),
        }

    async def _get_or_create_probe_bundle(
        self,
        file_path: Path,
        *,
        caller: str,
        request_kind: str,
    ) -> tuple[Dict[str, Any], Path, bool]:
        cache_key, bundle_path = self._probe_bundle_path(file_path)
        if self.no_cache:
            self._cache_diagnostics.record_status("disabled")
        await self._refresh_cached_path_once(
            f"media_probe_bundle:{cache_key}",
            bundle_path,
            log_label="media probe cache",
        )

        with self._cache_diagnostics.measure("path_existence"):
            exists = bundle_path.exists()
        bundle = self._read_probe_bundle(bundle_path) if exists else None
        if bundle is None and not exists:
            legacy = self._read_legacy_probe_bundle(file_path)
            if legacy is not None:
                self._write_probe_bundle(bundle_path, legacy)
                bundle = legacy

        requested_value_present = bool(
            bundle is not None
            and (
                bundle.get("duration") is not None
                if request_kind == "duration"
                else isinstance(bundle.get("media_info"), dict)
            )
        )
        if requested_value_present:
            self._record_probe_cache_hit(
                file_path=file_path,
                path=bundle_path,
                caller=caller,
                kind=request_kind,
            )
            return bundle, bundle_path, True

        task_key = f"media_probe_bundle:{cache_key}"
        async with self._inflight_lock:
            existing = self._inflight_tasks.get(task_key)
            if existing is None:
                perf_stats.incr("cache_miss")
                self._cache_diagnostics.record_status("miss")

                async def _create() -> Dict[str, Any]:
                    try:
                        current = self._read_probe_bundle(bundle_path)
                        current_has_value = bool(
                            current is not None
                            and (
                                current.get("duration") is not None
                                if request_kind == "duration"
                                else isinstance(current.get("media_info"), dict)
                            )
                        )
                        if current_has_value:
                            return current
                        generated = await self._generate_probe_bundle(
                            file_path,
                            caller=caller,
                            request_kind=request_kind,
                        )
                        if current:
                            if generated.get("media_info") is None:
                                generated["media_info"] = current.get("media_info")
                            if generated.get("duration") is None:
                                generated["duration"] = current.get("duration")
                        self._write_probe_bundle(bundle_path, generated)
                        return generated
                    except Exception as exc:
                        raise CacheError(
                            f"Failed to get or cache media probe for {file_path.name}: {exc}"
                        ) from exc
                    finally:
                        async with self._inflight_lock:
                            self._inflight_tasks.pop(task_key, None)

                task = asyncio.create_task(_create())
                self._inflight_tasks[task_key] = task
            else:
                self._cache_diagnostics.record_status("in_flight_wait")
                task = existing
        return await task, bundle_path, False

    async def get_or_create_media_info(
        self,
        file_path: Path,
        caller: Optional[str] = None,
    ) -> MediaInfo:
        resolved_caller = str(caller or self._infer_probe_caller())
        bundle, _path, _hit = await self._get_or_create_probe_bundle(
            file_path,
            caller=resolved_caller,
            request_kind="media_info",
        )
        media_info = bundle.get("media_info")
        if not isinstance(media_info, dict):
            # A duration-only compatibility probe may have created the first bundle.
            generated = await self._generate_probe_bundle(
                file_path,
                caller=resolved_caller,
                request_kind="media_info",
            )
            bundle.update(generated)
            _cache_key, bundle_path = self._probe_bundle_path(file_path)
            self._write_probe_bundle(bundle_path, bundle)
            media_info = bundle.get("media_info")
        if not isinstance(media_info, dict):
            raise CacheError(f"Media info was not produced for {file_path.name}")
        return media_info

    async def get_or_create_media_duration(
        self,
        file_path: Path,
        caller: Optional[str] = None,
    ) -> float:
        resolved_caller = str(caller or self._infer_probe_caller())
        bundle, _path, _hit = await self._get_or_create_probe_bundle(
            file_path,
            caller=resolved_caller,
            request_kind="duration",
        )
        duration = bundle.get("duration")
        if duration is None:
            raise CacheError(f"Media duration was not produced for {file_path.name}")
        return float(duration)
