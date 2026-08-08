"""Self-healing cache helpers for FinalizePhase."""

from __future__ import annotations

import hashlib
import math
import os
import tempfile
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict

from zundamotion.exceptions import PipelineError
from zundamotion.utils.ffmpeg_probe import clear_probe_caches, get_media_duration
from zundamotion.utils.logger import logger


class FinalizeCacheMixin:
    _TRANSITION_CACHE_MIN_TOLERANCE_SECONDS = 0.5
    _TRANSITION_CACHE_MAX_TOLERANCE_SECONDS = 2.0
    _FINAL_CACHE_MIN_TOLERANCE_SECONDS = 1.0
    _FINAL_CACHE_MAX_TOLERANCE_SECONDS = 5.0
    _CACHE_DURATION_RELATIVE_TOLERANCE = 0.01

    @staticmethod
    def _file_signature(path: Path) -> Dict[str, Any]:
        resolved = Path(path).resolve()
        try:
            stat = resolved.stat()
            digest = hashlib.sha256()
            with resolved.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            return {"size": stat.st_size, "sha256": digest.hexdigest()}
        except Exception:
            return {"path": str(resolved), "missing": True}

    def _cache_tolerance(self, expected_duration: float, cache_label: str) -> float:
        relative = expected_duration * self._CACHE_DURATION_RELATIVE_TOLERANCE
        if cache_label == "transition":
            return min(
                max(self._TRANSITION_CACHE_MIN_TOLERANCE_SECONDS, relative),
                self._TRANSITION_CACHE_MAX_TOLERANCE_SECONDS,
            )
        return min(
            max(self._FINAL_CACHE_MIN_TOLERANCE_SECONDS, relative),
            self._FINAL_CACHE_MAX_TOLERANCE_SECONDS,
        )

    async def _is_valid_finalize_cache(
        self, path: Path, *, expected_duration: float, cache_label: str,
    ) -> bool:
        try:
            actual = float(await get_media_duration(str(path), caller="finalize_cache_validation"))
        except Exception as exc:
            logger.warning(
                "FinalizePhase: Invalid %s cache '%s': media probe failed (%s).",
                cache_label, path.name, exc,
            )
            return False
        if not math.isfinite(actual) or actual <= 0:
            logger.warning("FinalizePhase: Invalid %s cache '%s': duration=%s.", cache_label, path.name, actual)
            return False
        if not math.isfinite(expected_duration) or expected_duration <= 0:
            return True
        tolerance = self._cache_tolerance(expected_duration, cache_label)
        difference = abs(actual - expected_duration)
        if difference <= tolerance:
            return True
        logger.warning(
            "FinalizePhase: Invalid %s cache '%s': actual=%.2fs expected=%.2fs difference=%.2fs tolerance=%.2fs.",
            cache_label, path.name, actual, expected_duration, difference, tolerance,
        )
        return False

    async def _atomic_finalize_creator(
        self,
        cache_output_path: Path,
        creator_func: Callable[[Path], Awaitable[Path]],
        *, expected_duration: float, cache_label: str,
    ) -> Path:
        cache_output_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=f".{cache_output_path.stem}.partial-", dir=cache_output_path.parent
        ) as partial_dir:
            partial = Path(partial_dir) / cache_output_path.name
            generated = Path(await creator_func(partial))
            if generated != partial:
                raise PipelineError(
                    f"FinalizePhase: Cache creator returned an unexpected output path: {generated}"
                )
            if not await self._is_valid_finalize_cache(
                partial, expected_duration=expected_duration, cache_label=cache_label
            ):
                raise PipelineError(f"FinalizePhase: Generated {cache_label} cache failed validation.")
            os.replace(partial, cache_output_path)
            clear_probe_caches()
            return cache_output_path

    async def _get_or_create_finalize_cache(
        self, *, key_data: Dict[str, Any], file_name: str, extension: str,
        creator_func: Callable[[Path], Awaitable[Path]], expected_duration: float,
        cache_label: str,
    ) -> Path:
        async def atomic(path: Path) -> Path:
            return await self._atomic_finalize_creator(
                path, creator_func,
                expected_duration=expected_duration, cache_label=cache_label,
            )

        cached = await self.cache_manager.get_or_create(
            key_data=key_data, file_name=file_name, extension=extension,
            creator_func=atomic,
        )
        if await self._is_valid_finalize_cache(
            cached, expected_duration=expected_duration, cache_label=cache_label
        ):
            return cached
        logger.warning(
            "FinalizePhase: Removing invalid %s cache and regenerating: %s",
            cache_label, cached,
        )
        cached.unlink(missing_ok=True)
        clear_probe_caches()
        rebuilt = await self.cache_manager.get_or_create(
            key_data=key_data, file_name=file_name, extension=extension,
            creator_func=atomic,
        )
        if await self._is_valid_finalize_cache(
            rebuilt, expected_duration=expected_duration, cache_label=cache_label
        ):
            return rebuilt
        rebuilt.unlink(missing_ok=True)
        raise PipelineError(f"FinalizePhase: Regenerated {cache_label} cache failed validation.")
