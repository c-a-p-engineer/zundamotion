"""AudioPhase ordered-entry orchestration."""

import asyncio
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from tqdm import tqdm

from zundamotion.timeline import Timeline
from zundamotion.utils.logger import logger, time_log

from .audio_phase_control import (
    build_non_speech_line,
    register_control_entry,
    take_pending_audio_overlay,
)
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
                if register_control_entry(entry, timeline):
                    continue

                incoming_audio_overlays = take_pending_audio_overlay(
                    pending_l_cut_audio
                )
                pending_l_cut_audio = None
                non_speech = build_non_speech_line(
                    entry=entry,
                    timeline=timeline,
                    incoming_audio_overlays=incoming_audio_overlays,
                )
                if non_speech is not None:
                    progress.set_description(non_speech.progress_description)
                    line_data_map[non_speech.line_id] = non_speech.line_data
                    progress.update(1)
                    continue

                progress.set_description(
                    "Audio Generation "
                    f"(Scene '{entry['scene_id']}', Line {entry['line_idx']}: "
                    f"'{entry['display_text'][:30]}...')"
                )
                result = await process_speech_entry(
                    phase=self,
                    entry=entry,
                    timeline=timeline,
                    incoming_audio_overlays=incoming_audio_overlays,
                )
                line_data_map[entry["line_id"]] = result.line_data
                pending_l_cut_audio = result.pending_l_cut_audio
                progress.update(1)

        try:
            tqdm.write("", file=sys.stderr)
        except Exception:
            pass
        return line_data_map, self.used_voicevox_info
