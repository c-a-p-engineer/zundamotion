"""Process one AudioPhase speech entry after synthesis completes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from zundamotion.exceptions import PipelineError
from zundamotion.timeline import Timeline
from zundamotion.utils.ffmpeg_audio import (
    AUDIO_MIX_VERSION,
    INTERMEDIATE_AUDIO_FORMAT_VERSION,
    apply_audio_filter,
)

from .audio_phase_face_anim import build_face_animation


@dataclass(frozen=True)
class SpeechProcessingResult:
    line_data: Dict[str, Any]
    pending_l_cut_audio: Optional[Dict[str, Any]]


def _audio_cache_data(
    phase: Any,
    read_text: str,
    line: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "text": read_text,
        "line_config": line,
        "voice_config": phase.config.get("voice", {}),
        "intermediate_audio_params": phase.audio_params.for_intermediate().__dict__,
        "intermediate_audio_format_version": INTERMEDIATE_AUDIO_FORMAT_VERSION,
        "audio_mix_version": AUDIO_MIX_VERSION,
    }


def _ensure_line_audio_cache(
    phase: Any,
    *,
    line_id: str,
    line: Dict[str, Any],
    audio_path: Path,
    cache_data: Dict[str, Any],
) -> Path:
    needs_cache = bool(
        line.get("audio_filter")
        or line.get("sound_effects")
        or line.get("voice_layers")
        or not audio_path.exists()
    )
    if not needs_cache:
        return audio_path

    phase.cache_manager.save_to_cache(
        key_data=cache_data,
        file_name=line_id,
        extension="wav",
        source_path=audio_path,
    )
    cached_path = phase.cache_manager.get_cache_path(
        key_data=cache_data,
        file_name=line_id,
        extension="wav",
    )
    if cached_path.exists():
        return cached_path
    return phase.temp_dir / f"{line_id}_speech.wav"


async def _apply_filter(
    phase: Any,
    *,
    line_id: str,
    line: Dict[str, Any],
    audio_path: Path,
    cache_data: Dict[str, Any],
) -> Path:
    audio_filter = line.get("audio_filter")
    if not audio_filter:
        return audio_path
    filter_key = {
        **cache_data,
        "audio_filter": audio_filter,
        "audio_params": phase.audio_params.for_intermediate().__dict__,
        "intermediate_audio_format_version": INTERMEDIATE_AUDIO_FORMAT_VERSION,
    }

    async def creator(output_path: Path) -> Path:
        await apply_audio_filter(
            str(audio_path),
            str(output_path),
            audio_filter,
            phase.audio_params.for_intermediate(),
        )
        return output_path

    return await phase.cache_manager.get_or_create(
        key_data=filter_key,
        file_name=f"{line_id}_{audio_filter}",
        extension="wav",
        creator_func=creator,
    )


async def _resolve_duration(
    phase: Any,
    *,
    line: Dict[str, Any],
    audio_path: Path,
) -> float:
    insert_config = line.get("insert")
    if not insert_config:
        return float(
            await phase.cache_manager.get_or_create_media_duration(audio_path)
        )

    insert_path = Path(insert_config["path"])
    if insert_path.suffix.lower() not in phase.video_extensions:
        return float(insert_config.get("duration", 2.0))
    duration = float(
        await phase.cache_manager.get_or_create_media_duration(insert_path)
    )
    try:
        speed = float(insert_config.get("speed", 1.0))
    except Exception:
        speed = 1.0
    return duration / max(0.25, min(4.0, speed))


def _split_l_cut(
    phase: Any,
    *,
    line: Dict[str, Any],
    audio_path: Path,
    full_duration: float,
) -> tuple[float, Optional[Dict[str, Any]]]:
    l_cut_duration = phase._cut_duration(line, "l_cut")
    if l_cut_duration <= 0 or full_duration <= 0.05:
        return full_duration, None
    l_cut_duration = min(l_cut_duration, max(0.0, full_duration - 0.05))
    if l_cut_duration <= 0:
        return full_duration, None

    duration = max(0.05, full_duration - l_cut_duration)
    l_cut_config = line.get("l_cut")
    volume = float(
        (l_cut_config or {}).get("volume", 1.0)
        if isinstance(l_cut_config, dict)
        else 1.0
    )
    return duration, {
        "path": str(audio_path),
        "source_start": duration,
        "duration": l_cut_duration,
        "start": 0.0,
        "volume": volume,
    }


def _speaker_name(line: Dict[str, Any]) -> str:
    name = line.get("speaker_name")
    if name:
        return str(name)
    layer_names = [
        layer.get("speaker_name")
        for layer in (line.get("voice_layers") or [])
        if isinstance(layer, dict) and layer.get("speaker_name")
    ]
    return " + ".join(layer_names) if layer_names else "Unknown"


async def process_speech_entry(
    *,
    phase: Any,
    entry: Dict[str, Any],
    timeline: Timeline,
    incoming_audio_overlays: List[Dict[str, Any]],
) -> SpeechProcessingResult:
    """Wait for synthesis and build the line data consumed by VideoPhase."""
    line = entry["line"]
    line_id = entry["line_id"]
    read_text = entry["read_text"]
    display_text = entry["display_text"]
    effective_subtitle_text = entry["effective_subtitle_text"]

    audio_path, voice_entries, voice_layer_segments = await entry["audio_task"]
    if not audio_path:
        raise PipelineError(f"Audio generation failed for line: {line_id}")
    for speaker_id, generated_text in voice_entries:
        if generated_text.strip():
            phase.used_voicevox_info.append((speaker_id, generated_text))

    audio_path = Path(audio_path)
    cache_data = _audio_cache_data(phase, read_text, line)
    audio_path = _ensure_line_audio_cache(
        phase,
        line_id=line_id,
        line=line,
        audio_path=audio_path,
        cache_data=cache_data,
    )
    audio_path = await _apply_filter(
        phase,
        line_id=line_id,
        line=line,
        audio_path=audio_path,
        cache_data=cache_data,
    )

    full_duration = await _resolve_duration(
        phase,
        line=line,
        audio_path=audio_path,
    )
    duration, pending_l_cut = _split_l_cut(
        phase,
        line=line,
        audio_path=audio_path,
        full_duration=full_duration,
    )
    timeline.add_event(
        f'{_speaker_name(line)}: "{display_text}"',
        duration,
        text=(effective_subtitle_text or None),
    )
    face_animation = await build_face_animation(
        phase=phase,
        line_id=line_id,
        line=line,
        audio_path=audio_path,
        duration=duration,
        voice_layer_segments=voice_layer_segments,
    )
    return SpeechProcessingResult(
        line_data={
            "type": "talk",
            "audio_path": audio_path,
            "duration": duration,
            "audio_full_duration": full_duration,
            "text": effective_subtitle_text,
            "tts_text": read_text,
            "line_config": line,
            "face_anim": face_animation,
            "extra_audio_overlays": incoming_audio_overlays,
        },
        pending_l_cut_audio=pending_l_cut,
    )
