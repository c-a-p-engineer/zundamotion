"""Finite wait-clip rendering through the common clip pipeline.

Historically wait clips used a dedicated FFmpeg graph with an infinite lavfi
``anullsrc`` input.  Short CPU renders intermittently stalled near completion in
CI.  Wait clips now use a finite PCM WAV and the same clip pipeline as talk
clips, so every input has a bounded EOF and filter/encoder behaviour stays in
one implementation.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING
import wave

from ...exceptions import PipelineError
from ...utils.logger import logger

if TYPE_CHECKING:
    from .renderer import VideoRenderer


_PCM_SAMPLE_WIDTH = 2
_WRITE_CHUNK_FRAMES = 16_384


def _silent_frame_count(duration: float, sample_rate: int) -> int:
    """Return a deterministic finite PCM frame count for ``duration``."""
    seconds = max(0.0, float(duration))
    return max(1, int(math.ceil(seconds * max(1, int(sample_rate)))))


def _write_finite_silence_wav(
    path: Path,
    *,
    duration: float,
    sample_rate: int,
    channels: int,
) -> Path:
    """Write bounded 16-bit PCM silence without allocating the whole file."""
    sample_rate = max(1, int(sample_rate))
    channels = max(1, int(channels))
    frames_remaining = _silent_frame_count(duration, sample_rate)
    path.parent.mkdir(parents=True, exist_ok=True)
    bytes_per_frame = channels * _PCM_SAMPLE_WIDTH
    zero_chunk = b"\x00" * (_WRITE_CHUNK_FRAMES * bytes_per_frame)

    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(channels)
        stream.setsampwidth(_PCM_SAMPLE_WIDTH)
        stream.setframerate(sample_rate)
        while frames_remaining > 0:
            frame_count = min(frames_remaining, _WRITE_CHUNK_FRAMES)
            stream.writeframesraw(zero_chunk[: frame_count * bytes_per_frame])
            frames_remaining -= frame_count
        stream.writeframes(b"")
    return path


class WaitClipRuntimeMixin:
    """Render wait lines using finite audio and the shared clip graph."""

    async def _finite_wait_silence(self, duration: float) -> Path:
        sample_rate = int(self.audio_params.sample_rate)
        channels = int(self.audio_params.channels)
        key_data = {
            "type": "finite_wait_silence",
            "version": "20260808_v1",
            "duration_us": int(round(max(0.0, float(duration)) * 1_000_000)),
            "sample_rate": sample_rate,
            "channels": channels,
            "sample_width": _PCM_SAMPLE_WIDTH,
        }

        async def creator(output_path: Path) -> Path:
            return _write_finite_silence_wav(
                output_path,
                duration=duration,
                sample_rate=sample_rate,
                channels=channels,
            )

        return await self.cache_manager.get_or_create(
            key_data=key_data,
            file_name="wait_silence",
            extension="wav",
            creator_func=creator,
        )

    async def render_wait_clip(
        self,
        duration: float,
        background_config: Dict[str, Any],
        output_filename: str,
        line_config: Dict[str, Any],
        characters_config: Optional[List[Dict[str, Any]]] = None,
        image_layer_overlays: Optional[List[Dict[str, Any]]] = None,
        extra_audio_overlays: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[Path]:
        """Render a wait clip without an infinite synthetic FFmpeg input."""
        if duration <= 0:
            raise ValueError("Wait duration must be greater than zero.")

        silence_path = await self._finite_wait_silence(duration)
        line_config = line_config if isinstance(line_config, dict) else {}
        logger.info(
            "[WaitClip] mode=finite_common_pipeline duration=%.3fs output=%s silence=%s",
            duration,
            output_filename,
            silence_path.name,
        )
        clip_path = await self.render_clip(
            audio_path=silence_path,
            duration=duration,
            background_config=background_config,
            characters_config=characters_config or [],
            output_filename=output_filename,
            subtitle_text=None,
            subtitle_line_config=line_config,
            insert_config=None,
            image_layer_overlays=image_layer_overlays,
            extra_audio_overlays=extra_audio_overlays,
            background_effects=line_config.get("background_effects"),
            screen_effects=line_config.get("screen_effects"),
            audio_delay=0.0,
        )
        if clip_path is None:
            raise PipelineError(f"Wait clip rendering failed: {output_filename}")
        return Path(clip_path)
