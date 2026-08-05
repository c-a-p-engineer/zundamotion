"""AudioPhase line preparation and synthesis orchestration."""

import asyncio
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from tqdm import tqdm

from zundamotion.exceptions import PipelineError
from zundamotion.timeline import Timeline
from zundamotion.utils.ffmpeg_audio import (
    AUDIO_MIX_VERSION,
    INTERMEDIATE_AUDIO_FORMAT_VERSION,
    apply_audio_filter,
)
from zundamotion.utils.logger import logger, time_log

from .audio_phase_entries import prepare_audio_entries
from .audio_phase_face_anim import build_face_animation


class AudioPhaseRunMixin:
    """Provide the audio generation phase while AudioPhase owns dependencies."""

    @time_log(logger)
    async def run(
        self, scenes: List[Dict[str, Any]], timeline: Timeline
    ) -> Tuple[Dict[str, Dict[str, Any]], List[Tuple[int, str]]]:
        """Generate line audio, timeline events, and face animation metadata."""
        line_data_map: Dict[str, Dict[str, Any]] = {}
        total_lines = sum(len(scene.get("lines", [])) for scene in scenes)
        audio_sem = asyncio.Semaphore(self.audio_workers)
        pending_l_cut_audio: Optional[Dict[str, Any]] = None

        async def _generate_line_audio(
            read_text: str,
            line: Dict[str, Any],
            line_id: str,
        ) -> Tuple[Path, List[Tuple[int, str]], List[Dict[str, Any]]]:
            async with audio_sem:
                return await self.audio_gen.generate_audio(read_text, line, line_id)

        ordered_entries = prepare_audio_entries(
            scenes=scenes,
            config=self.config,
            timeline=timeline,
            generate_line_audio=_generate_line_audio,
        )

        with tqdm(
            total=total_lines,
            desc="Audio Generation",
            unit="line",
            leave=False,
            disable=(os.getenv("TQDM_DISABLE") == "1" or not sys.stderr.isatty()),
        ) as progress:
            for entry in ordered_entries:
                entry_type = entry["entry_type"]
                scene_id = entry["scene_id"]

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

                line = entry["line"]
                line_index = entry["line_idx"]
                line_id = entry["line_id"]
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

                text = entry["display_text"]
                read_text = entry["read_text"]
                effective_subtitle_text = entry["effective_subtitle_text"]
                progress.set_description(
                    f"Audio Generation (Scene '{scene_id}', Line {line_index}: '{text[:30]}...')"
                )
                audio_path, voice_entries, voice_layer_segments = await entry[
                    "audio_task"
                ]
                if not audio_path:
                    raise PipelineError(f"Audio generation failed for line: {line_id}")
                for speaker_id, generated_text in voice_entries:
                    if generated_text.strip():
                        self.used_voicevox_info.append((speaker_id, generated_text))

                audio_cache_data = {
                    "text": read_text,
                    "line_config": line,
                    "voice_config": self.config.get("voice", {}),
                    "intermediate_audio_params": self.audio_params.for_intermediate().__dict__,
                    "intermediate_audio_format_version": INTERMEDIATE_AUDIO_FORMAT_VERSION,
                    "audio_mix_version": AUDIO_MIX_VERSION,
                }
                if (
                    line.get("audio_filter")
                    or line.get("sound_effects")
                    or line.get("voice_layers")
                    or not Path(audio_path).exists()
                ):
                    self.cache_manager.save_to_cache(
                        key_data=audio_cache_data,
                        file_name=line_id,
                        extension="wav",
                        source_path=audio_path,
                    )
                    audio_path = self.cache_manager.get_cache_path(
                        key_data=audio_cache_data,
                        file_name=line_id,
                        extension="wav",
                    )
                    if not audio_path.exists():
                        audio_path = self.temp_dir / f"{line_id}_speech.wav"

                audio_filter = line.get("audio_filter")
                if audio_filter:
                    filter_key = {
                        **audio_cache_data,
                        "audio_filter": audio_filter,
                        "audio_params": self.audio_params.for_intermediate().__dict__,
                        "intermediate_audio_format_version": INTERMEDIATE_AUDIO_FORMAT_VERSION,
                    }
                    source_audio_path = Path(audio_path)

                    async def _filter_creator(output_path: Path) -> Path:
                        await apply_audio_filter(
                            str(source_audio_path),
                            str(output_path),
                            audio_filter,
                            self.audio_params.for_intermediate(),
                        )
                        return output_path

                    audio_path = await self.cache_manager.get_or_create(
                        key_data=filter_key,
                        file_name=f"{line_id}_{audio_filter}",
                        extension="wav",
                        creator_func=_filter_creator,
                    )

                insert_config = line.get("insert")
                if insert_config:
                    insert_path = Path(insert_config["path"])
                    if insert_path.suffix.lower() in self.video_extensions:
                        duration = await self.cache_manager.get_or_create_media_duration(
                            insert_path
                        )
                        try:
                            insert_speed = float(insert_config.get("speed", 1.0))
                        except Exception:
                            insert_speed = 1.0
                        duration /= max(0.25, min(4.0, insert_speed))
                    else:
                        duration = insert_config.get("duration", 2.0)
                else:
                    duration = await self.cache_manager.get_or_create_media_duration(
                        audio_path
                    )

                audio_full_duration = float(duration)
                l_cut_duration = self._cut_duration(line, "l_cut")
                if l_cut_duration > 0 and audio_full_duration > 0.05:
                    l_cut_duration = min(
                        l_cut_duration,
                        max(0.0, audio_full_duration - 0.05),
                    )
                    if l_cut_duration > 0:
                        duration = max(0.05, audio_full_duration - l_cut_duration)
                        pending_l_cut_audio = {
                            "path": str(audio_path),
                            "source_start": duration,
                            "duration": l_cut_duration,
                            "start": 0.0,
                            "volume": float(
                                (line.get("l_cut") or {}).get("volume", 1.0)
                                if isinstance(line.get("l_cut"), dict)
                                else 1.0
                            ),
                        }

                voice_layers = [
                    layer
                    for layer in (line.get("voice_layers") or [])
                    if isinstance(layer, dict)
                ]
                character_name = line.get("speaker_name")
                if not character_name and voice_layers:
                    names = [
                        layer.get("speaker_name")
                        for layer in voice_layers
                        if layer.get("speaker_name")
                    ]
                    if names:
                        character_name = " + ".join(names)
                if not character_name:
                    character_name = "Unknown"
                timeline.add_event(
                    f'{character_name}: "{text}"',
                    duration,
                    text=(effective_subtitle_text or None),
                )

                face_animation = await build_face_animation(
                    phase=self,
                    line_id=line_id,
                    line=line,
                    audio_path=Path(audio_path),
                    duration=float(duration),
                    voice_layer_segments=voice_layer_segments,
                )
                line_data_map[line_id] = {
                    "type": "talk",
                    "audio_path": audio_path,
                    "duration": duration,
                    "audio_full_duration": audio_full_duration,
                    "text": effective_subtitle_text,
                    "tts_text": read_text,
                    "line_config": line,
                    "face_anim": face_animation,
                    "extra_audio_overlays": incoming_audio_overlays,
                }
                progress.update(1)

        try:
            tqdm.write("", file=sys.stderr)
        except Exception:
            pass
        return line_data_map, self.used_voicevox_info
