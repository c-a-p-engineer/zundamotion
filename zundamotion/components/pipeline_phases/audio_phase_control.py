"""Register non-speech AudioPhase entries in timeline order."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from zundamotion.timeline import Timeline


@dataclass(frozen=True)
class NonSpeechLineResult:
    line_id: str
    line_data: Dict[str, Any]
    progress_description: str


def register_control_entry(entry: Dict[str, Any], timeline: Timeline) -> bool:
    """Register BGM/topic entries and report whether the entry was consumed."""
    entry_type = entry["entry_type"]
    if entry_type == "bgm":
        bgm_config = entry["bgm_cfg"]
        timeline.add_bgm_event(
            str(bgm_config.get("id")),
            str(bgm_config.get("action")),
            fade=bgm_config.get("fade"),
        )
        return True
    if entry_type == "topic":
        timeline.add_topic(entry["topic"])
        return True
    return False


def take_pending_audio_overlay(
    pending_l_cut_audio: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Return the previous line's L-cut overlay for the next timed entry."""
    return [pending_l_cut_audio] if pending_l_cut_audio is not None else []


def build_non_speech_line(
    *,
    entry: Dict[str, Any],
    timeline: Timeline,
    incoming_audio_overlays: List[Dict[str, Any]],
) -> Optional[NonSpeechLineResult]:
    """Build wait/image-layer line data without involving speech synthesis."""
    entry_type = entry["entry_type"]
    line = entry["line"]
    line_id = entry["line_id"]
    scene_id = entry["scene_id"]
    line_index = entry["line_idx"]

    if entry_type == "wait":
        wait_value = line["wait"]
        duration = float(
            wait_value.get("duration", 0.0)
            if isinstance(wait_value, dict)
            else wait_value
        )
        timeline.add_event(f"(Wait {duration}s)", duration, text=None)
        return NonSpeechLineResult(
            line_id=line_id,
            progress_description=(
                f"Calculating Wait Step (Scene '{scene_id}', Line {line_index})"
            ),
            line_data={
                "type": "wait",
                "duration": duration,
                "line_config": line,
                "audio_path": None,
                "text": None,
                "extra_audio_overlays": incoming_audio_overlays,
            },
        )

    if entry_type == "image_layer":
        timeline.add_event("(Image Layer)", 0.0, text=None)
        return NonSpeechLineResult(
            line_id=line_id,
            progress_description=(
                f"Registering Image Layer Step (Scene '{scene_id}', Line {line_index})"
            ),
            line_data={
                "type": "image_layer",
                "duration": 0.0,
                "line_config": line,
                "audio_path": None,
                "text": None,
                "extra_audio_overlays": incoming_audio_overlays,
            },
        )

    return None
