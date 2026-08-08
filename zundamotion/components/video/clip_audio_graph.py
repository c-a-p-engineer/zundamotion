"""Build the audio side of a clip filter graph."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from ...utils.ffmpeg_audio import has_audio_stream
from .clip_input_collection import ClipInputCollection

if TYPE_CHECKING:
    from .renderer import VideoRenderer


def _atempo_chain(speed: float) -> str:
    remaining = max(0.25, min(4.0, float(speed)))
    parts: List[str] = []
    while remaining > 2.0:
        parts.append("atempo=2.000000")
        remaining /= 2.0
    while remaining < 0.5:
        parts.append("atempo=0.500000")
        remaining /= 0.5
    parts.append(f"atempo={remaining:.6f}")
    return ",".join(parts)


def _speech_source(renderer: "VideoRenderer", inputs: ClipInputCollection, parts: List[str]) -> str:
    parts.append(
        f"[{inputs.speech_audio_index}:a]aresample={renderer.audio_params.sample_rate},"
        "asetpts=PTS-STARTPTS[speech_norm]"
    )
    return "[speech_norm]"


def _insert_source(
    renderer: "VideoRenderer", inputs: ClipInputCollection,
    insert_config: Dict[str, Any], has_speech: bool, parts: List[str],
) -> str:
    volume = float(insert_config.get("volume", 1.0))
    filters = ["asetpts=PTS-STARTPTS", f"volume={volume}"]
    if abs(inputs.insert_speed - 1.0) > 1e-6:
        filters.append(_atempo_chain(inputs.insert_speed))
    parts.append(f"[{inputs.insert_audio_index}:a]{','.join(filters)}[insert_audio_vol]")
    if not has_speech:
        return "[insert_audio_vol]"
    speech = _speech_source(renderer, inputs, parts)
    parts.append(
        f"{speech}[insert_audio_vol]amix=inputs=2:duration=longest:"
        "dropout_transition=0[mixed_a]"
    )
    return "[mixed_a]"


def _number(overlay: Dict[str, Any], key: str, default: float, *, minimum: Optional[float] = None) -> float:
    try:
        value = float(overlay.get(key, default) or default)
    except Exception:
        value = default
    return max(minimum, value) if minimum is not None else value


def _append_extra_audio(
    inputs: ClipInputCollection, *, duration: float, base_source: str,
    parts: List[str],
) -> str:
    labels = [base_source]
    for index, overlay in enumerate(inputs.extra_audio_inputs):
        ff_idx = overlay.get("_ff_idx")
        if ff_idx is None:
            continue
        source_start = _number(overlay, "source_start", 0.0, minimum=0.0)
        overlay_duration = _number(overlay, "duration", duration, minimum=0.0)
        start = _number(overlay, "start", 0.0, minimum=0.0)
        volume = _number(overlay, "volume", 1.0)
        trimmed, delayed = f"[extra_audio_trim_{index}]", f"[extra_audio_{index}]"
        parts.append(
            f"[{ff_idx}:a]atrim=start={source_start:.6f}:duration={overlay_duration:.6f},"
            f"asetpts=PTS-STARTPTS,volume={volume:.6f}{trimmed}"
        )
        parts.append(f"{trimmed}adelay={max(0, int(start * 1000))}:all=1{delayed}")
        labels.append(delayed)
    if len(labels) == 1:
        return base_source
    parts.append(
        f"{''.join(labels)}amix=inputs={len(labels)}:duration=longest:"
        "dropout_transition=0[mixed_extra_a]"
    )
    return "[mixed_extra_a]"


async def _base_audio_source(
    renderer: "VideoRenderer", inputs: ClipInputCollection, audio_path: Path,
    insert_config: Optional[Dict[str, Any]], parts: List[str],
) -> str:
    has_speech = await has_audio_stream(str(audio_path))
    if insert_config and inputs.insert_audio_index != -1:
        return _insert_source(renderer, inputs, insert_config, has_speech, parts)
    if has_speech:
        return _speech_source(renderer, inputs, parts)
    parts.append(
        f"anullsrc=channel_layout=stereo:sample_rate={renderer.audio_params.sample_rate}[sil]"
    )
    return "[sil]"


async def append_clip_audio_graph(
    *, renderer: "VideoRenderer", inputs: ClipInputCollection,
    audio_path: Path, duration: float,
    insert_config: Optional[Dict[str, Any]], audio_delay: float,
    parts: List[str],
) -> str:
    """Append audio filters and return the final map label."""
    source = await _base_audio_source(renderer, inputs, audio_path, insert_config, parts)
    source = _append_extra_audio(inputs, duration=duration, base_source=source, parts=parts)
    delay_ms = max(0, int(audio_delay * 1000))
    parts.append(
        f"{source}asetpts=PTS-STARTPTS,adelay={delay_ms}:all=1,"
        f"apad=whole_dur={duration},atrim=duration={duration},"
        "asetpts=PTS-STARTPTS[final_a]"
    )
    return "[final_a]"
