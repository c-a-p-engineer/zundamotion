"""AudioPhase ordered-entry orchestration."""

import asyncio
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from tqdm import tqdm

from zundamotion.timeline import Timeline
from zundamotion.utils.logger import logger, time_log

from .audio_phase_entries import prepare_audio_entries
from .audio_phase_speech import process_speech_entry


class AudioPhaseRunMixin:
    """Provide the audio generation phase while AudioPhase owns dependencies."""

    @time_log(logger)
    async def run(
        self, scenes: List[Dict[str, Any]], timeline: Timeline
    ) -> Tuple[Dict[str, Dict[str, Any]], List[Tuple[int, str]]]:
        """Generate audio entries and register their timeline results in order."""
        line_data_map: Dict[str, Dict[str, Any]] = {}
        total_lines = sum(len(scene.get("lines", [])) for scene in scenes)
        audio_semaphore = asyncio.Semaphore(self.audio_workers)
        pending_l_cut_audio: Optional[Dict[str, Any]] = None

        async def generate_line_audio(
            read_text: str,
            line: Dict[str, Any],
            line_id: str,
        ) -> Tuple[Path, List[Tuple[int, str]], List[Dict[str, Any]]]:
            async with audio_semaphore:
                return await self.audio_gen.generate_audio(read_text, line, line_id)

        entries = prepare_audio_entries(
            scenes=scenes,
            config=self.config,
            timeline=timeline,
            generate_line_audio=generate_line_audio,
        )
        with tqdm(
            total=total_lines,
            desc="Audio Generation",
            unit="line",
            leave=False,
            disable=(os.getenv("TQDM_DISABLE") == "1" or not sys.stderr.isatty()),
        ) as progress:
            for entry in entries:
                entry_type = entry["entry_type"]
                if entry_type == "bgm":
                    bgm_config = entry["bgm_cfg"]
                    timeline.add_bgm_event(
                        str(bgm_config.get("id")),
                        str(bgm_config.get("action")),
                        fade=bgm_config.get("fade"),
                    )
                    continue
                if entry_type == "topic":
                    timeline.add_topic(entry["topic"])
                    continue

                scene_id = entry["scene_id"]
                line_index = entry["line_idx"]
                line_id = entry["line_id"]
                line = entry["line"]
                incoming_audio_overlays: List[Dict[str, Any]] = []
                if pending_l_cut_audio is not None:
                    incoming_audio_overlays.append(pending_l_cut_audio)
                    pending_l_cut_audio = None

                if entry_type == "wait":
                    progress.set_description(
                        f"Calculating Wait Step (Scene '{scene_id}', Line {line_index})"
                    )
                    wait_value = line["wait"]
                    duration = float(
                        wait_value.get("duration", 0.0)
                        if isinstance(wait_value, dict)
                        else wait_value
                    )
                    timeline.add_event(f"(Wait {duration}s)", duration, text=None)
                    line_data_map[line_id] = {
                        "type": "wait",
                        "duration": duration,
                        "line_config": line,
                        "audio_path": None,
                        "text": None,
                        "extra_audio_overlays": incoming_audio_overlays,
                    }
                    progress.update(1)
                    continue

                if entry_type == "image_layer":
                    progress.set_description(
                        f"Registering Image Layer Step (Scene '{scene_id}', Line {line_index})"
                    )
                    timeline.add_event("(Image Layer)", 0.0, text=None)
                    line_data_map[line_id] = {
                        "type": "image_layer",
                        "duration": 0.0,
                        "line_config": line,
                        "audio_path": None,
                        "text": None,
                        "extra_audio_overlays": incoming_audio_overlays,
                    }
                    progress.update(1)
                    continue

                progress.set_description(
                    "Audio Generation "
                    f"(Scene '{scene_id}', Line {line_index}: "
                    f"'{entry['display_text'][:30]}...')"
                )
                result = await process_speech_entry(
                    phase=self,
                    entry=entry,
                    timeline=timeline,
                    incoming_audio_overlays=incoming_audio_overlays,
                )
                line_data_map[line_id] = result.line_data
                pending_l_cut_audio = result.pending_l_cut_audio
                progress.update(1)

        try:
            tqdm.write("", file=sys.stderr)
        except Exception:
            pass
        return line_data_map, self.used_voicevox_info
