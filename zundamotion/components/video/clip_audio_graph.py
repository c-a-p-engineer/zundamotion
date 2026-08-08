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


async def append_clip_audio_graph(
    *,
    renderer: "VideoRenderer",
    inputs: ClipInputCollection,
    audio_path: Path,
    duration: float,
    insert_config: Optional[Dict[str, Any]],
    audio_delay: float,
    parts: List[str],
) -> str:
    """Append audio filters and return the final map label."""

    has_speech_audio = await has_audio_stream(str(audio_path))
    audio_src: str
    if insert_config and inputs.insert_audio_index != -1:
        volume = float(insert_config.get("volume", 1.0))
        insert_filters = ["asetpts=PTS-STARTPTS", f"volume={volume}"]
        if abs(inputs.insert_speed - 1.0) > 1e-6:
            insert_filters.append(_atempo_chain(inputs.insert_speed))
        parts.append(
            f"[{inputs.insert_audio_index}:a]{','.join(insert_filters)}[insert_audio_vol]"
        )
        if has_speech_audio:
            parts.append(
                f"[{inputs.speech_audio_index}:a]aresample={renderer.audio_params.sample_rate},"
                "asetpts=PTS-STARTPTS[speech_norm]"
            )
            parts.append(
                "[speech_norm][insert_audio_vol]"
                "amix=inputs=2:duration=longest:dropout_transition=0[mixed_a]"
            )
            audio_src = "[mixed_a]"
        else:
            audio_src = "[insert_audio_vol]"
    elif has_speech_audio:
        parts.append(
            f"[{inputs.speech_audio_index}:a]aresample={renderer.audio_params.sample_rate},"
            "asetpts=PTS-STARTPTS[speech_norm]"
        )
        audio_src = "[speech_norm]"
    else:
        parts.append(
            f"anullsrc=channel_layout=stereo:sample_rate={renderer.audio_params.sample_rate}[sil]"
        )
        audio_src = "[sil]"

    mix_labels = [audio_src]
    for extra_index, overlay in enumerate(inputs.extra_audio_inputs):
        ff_idx = overlay.get("_ff_idx")
        if ff_idx is None:
            continue
        try:
            source_start = max(0.0, float(overlay.get("source_start", 0.0) or 0.0))
        except Exception:
            source_start = 0.0
        try:
            overlay_duration = max(
                0.0, float(overlay.get("duration", duration) or duration)
            )
        except Exception:
            overlay_duration = duration
        try:
            overlay_start = max(0.0, float(overlay.get("start", 0.0) or 0.0))
        except Exception:
            overlay_start = 0.0
        try:
            overlay_volume = float(overlay.get("volume", 1.0) or 1.0)
        except Exception:
            overlay_volume = 1.0
        trimmed = f"[extra_audio_trim_{extra_index}]"
        delayed = f"[extra_audio_{extra_index}]"
        parts.append(
            f"[{ff_idx}:a]atrim=start={source_start:.6f}:duration={overlay_duration:.6f},"
            f"asetpts=PTS-STARTPTS,volume={overlay_volume:.6f}{trimmed}"
        )
        delay_ms = max(0, int(overlay_start * 1000))
        parts.append(f"{trimmed}adelay={delay_ms}:all=1{delayed}")
        mix_labels.append(delayed)

    if len(mix_labels) > 1:
        mixed_label = "[mixed_extra_a]"
        parts.append(
            f"{''.join(mix_labels)}amix=inputs={len(mix_labels)}:"
            f"duration=longest:dropout_transition=0{mixed_label}"
        )
        audio_src = mixed_label

    delay_ms = max(0, int(audio_delay * 1000))
    parts.append(
        f"{audio_src}asetpts=PTS-STARTPTS,adelay={delay_ms}:all=1,"
        f"apad=whole_dur={duration},atrim=duration={duration},"
        "asetpts=PTS-STARTPTS[final_a]"
    )
    return "[final_a]"
