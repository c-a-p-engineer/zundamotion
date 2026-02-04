from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from zundamotion.exceptions import ValidationError
from zundamotion.timeline import Timeline
from zundamotion.utils.ffmpeg_audio import add_bgm_segments_to_video
from zundamotion.utils.ffmpeg_params import AudioParams
from zundamotion.utils.ffmpeg_probe import get_audio_duration, get_media_duration
from zundamotion.utils.logger import logger, time_log


class BGMPhase:
    def __init__(self, config: Dict[str, Any], temp_dir: Path, audio_params: AudioParams):
        self.config = config
        self.temp_dir = temp_dir
        self.audio_params = audio_params

    @time_log(logger)
    async def run(
        self,
        final_video_path: Path,
        timeline: Timeline,
    ) -> Path:
        """Phase 4: Apply timeline-driven BGM to the final video."""
        bgm_layers = (
            (self.config.get("script", {}) or {}).get("bgm_layers") or []
        )
        if not bgm_layers or not timeline.bgm_events:
            return final_video_path

        video_duration = await get_media_duration(str(final_video_path))
        events = [
            dict(evt, _index=idx) for idx, evt in enumerate(timeline.bgm_events)
        ]
        events.sort(key=lambda e: (float(e.get("time", 0.0)), e["_index"]))
        logger.info(
            "BGM IDs used: %s",
            sorted({str(evt.get("id")) for evt in events}),
        )
        logger.debug("BGM events: %s", json.dumps(events, ensure_ascii=False))

        layer_map = {str(layer["id"]): layer for layer in bgm_layers}
        layer_durations: Dict[str, float] = {}
        for layer_id, layer in layer_map.items():
            layer_durations[layer_id] = await get_audio_duration(layer["file"])

        states: Dict[str, Dict[str, Any]] = {
            layer_id: {
                "playing": False,
                "position": 0.0,
                "segment_start": 0.0,
                "segment_source_pos": 0.0,
                "segment_fade_in": 0.0,
                "has_started": False,
            }
            for layer_id in layer_map
        }
        segments: List[Dict[str, Any]] = []

        def _close_segment(bgm_id: str, end_time: float, fade_out: float) -> None:
            state = states[bgm_id]
            if not state["playing"]:
                return
            start_time = float(state["segment_start"])
            seg_len = max(0.0, float(end_time) - start_time)
            if seg_len <= 0:
                state["playing"] = False
                return

            layer = layer_map[bgm_id]
            duration = layer_durations.get(bgm_id, 0.0)
            loop = bool(layer.get("loop", False))
            source_pos = float(state["segment_source_pos"])
            if duration > 0 and loop:
                source_pos = source_pos % duration
            if duration > 0 and not loop:
                remaining = max(0.0, duration - source_pos)
                if remaining <= 0:
                    state["playing"] = False
                    return
                seg_len = min(seg_len, remaining)
            segments.append(
                {
                    "id": bgm_id,
                    "timeline_start": start_time,
                    "timeline_end": start_time + seg_len,
                    "source_start_pos": source_pos,
                    "duration": seg_len,
                    "fade_in": float(state["segment_fade_in"] or 0.0),
                    "fade_out": float(fade_out or 0.0),
                    "gain": layer.get("gain", 0.0),
                }
            )
            if duration > 0 and loop:
                state["position"] = (state["position"] + seg_len) % duration
            else:
                state["position"] = state["position"] + seg_len
            state["playing"] = False

        for event in events:
            bgm_id = str(event.get("id"))
            if bgm_id not in layer_map:
                raise ValidationError(f"BGM id '{bgm_id}' is not defined in bgm_layers.")
            action = str(event.get("action"))
            fade = event.get("fade")
            event_time = float(event.get("time", 0.0))
            state = states[bgm_id]

            if action == "start":
                if state["playing"]:
                    _close_segment(bgm_id, event_time, fade_out=0.0)
                state["position"] = 0.0
                state["segment_start"] = event_time
                state["segment_source_pos"] = state["position"]
                state["segment_fade_in"] = float(fade or 0.0)
                state["playing"] = True
                state["has_started"] = True
            elif action == "resume":
                if not state["has_started"]:
                    raise ValidationError(
                        f"BGM '{bgm_id}' resume called before start."
                    )
                if state["playing"]:
                    raise ValidationError(
                        f"BGM '{bgm_id}' resume called while already playing."
                    )
                state["segment_start"] = event_time
                state["segment_source_pos"] = state["position"]
                state["segment_fade_in"] = float(fade or 0.0)
                state["playing"] = True
            elif action == "stop":
                if not state["playing"]:
                    raise ValidationError(
                        f"BGM '{bgm_id}' stop called while not playing."
                    )
                _close_segment(bgm_id, event_time, fade_out=float(fade or 0.0))
            else:
                raise ValidationError(f"Unknown BGM action '{action}'.")

        for bgm_id in layer_map:
            if states[bgm_id]["playing"]:
                _close_segment(bgm_id, video_duration, fade_out=0.0)

        if not segments:
            return final_video_path

        logger.debug("BGM segments: %s", json.dumps(segments, ensure_ascii=False))
        output_path = self.temp_dir / "final_with_bgm.mp4"
        filter_complex = await add_bgm_segments_to_video(
            str(final_video_path),
            str(output_path),
            bgm_layers=bgm_layers,
            segments=segments,
            audio_params=self.audio_params,
        )
        logger.debug("BGM filter_complex: %s", filter_complex)
        return output_path
