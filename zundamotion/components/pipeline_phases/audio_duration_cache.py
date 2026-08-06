"""AudioPhase-local CacheManager proxy for deterministic WAV durations."""

from __future__ import annotations

import wave
from pathlib import Path
from typing import Any, Optional

from zundamotion.utils import perf_stats
from zundamotion.utils.logger import logger


class AudioDurationCacheProxy:
    """Delegate cache operations while avoiding ffprobe for valid PCM WAV files."""

    def __init__(self, cache_manager: Any):
        self._cache_manager = cache_manager

    def __getattr__(self, name: str) -> Any:
        return getattr(self._cache_manager, name)

    @staticmethod
    def _wav_duration(file_path: Path) -> float:
        with wave.open(str(file_path), "rb") as reader:
            frame_rate = int(reader.getframerate())
            if frame_rate <= 0:
                raise ValueError("WAV frame rate must be positive")
            return float(reader.getnframes()) / float(frame_rate)

    async def get_or_create_media_duration(
        self,
        file_path: Path,
        caller: Optional[str] = None,
    ) -> float:
        path = Path(file_path)
        if path.suffix.lower() == ".wav":
            try:
                duration = self._wav_duration(path)
                perf_stats.incr("wav_duration_header_hit")
                logger.debug(
                    "[AudioDuration] WAV header HIT file=%s duration=%.3fs caller=%s",
                    path.name,
                    duration,
                    caller or "unknown",
                )
                return duration
            except (OSError, EOFError, ValueError, wave.Error) as exc:
                perf_stats.incr("wav_duration_header_fallback")
                logger.debug(
                    "[AudioDuration] WAV header fallback file=%s caller=%s error=%s",
                    path.name,
                    caller or "unknown",
                    exc,
                )
        return float(
            await self._cache_manager.get_or_create_media_duration(
                path,
                caller=caller,
            )
        )
