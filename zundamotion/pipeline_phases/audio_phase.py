import hashlib
import json
from pathlib import Path
from typing import Tuple  # Add this import
from typing import Any, Dict, List, Optional

from tqdm import tqdm

from zundamotion.cache import CacheManager
from zundamotion.components.audio import AudioGenerator
from zundamotion.exceptions import PipelineError
from zundamotion.timeline import Timeline
from zundamotion.utils.ffmpeg_utils import AudioParams, get_audio_duration
from zundamotion.utils.logger import logger, time_log


class AudioPhase:
    def __init__(
        self,
        config: Dict[str, Any],
        temp_dir: Path,
        cache_manager: CacheManager,
        audio_params: AudioParams,
    ):
        self.config = config
        self.temp_dir = temp_dir
        self.cache_manager = cache_manager
        self.audio_gen = AudioGenerator(self.config, self.temp_dir, audio_params)
        self.video_extensions = self.config.get("system", {}).get(
            "video_extensions",
            [".mp4", ".mov", ".webm", ".avi", ".mkv"],
        )
        self.used_voicevox_info: List[Tuple[int, str]] = (
            []
        )  # Initialize list to store (speaker_id, text)

    @time_log(logger)
    def run(
        self, scenes: List[Dict[str, Any]], timeline: Timeline
    ) -> Tuple[
        Dict[str, Dict[str, Any]], List[Tuple[int, str]]
    ]:  # Return line_data_map and used_voicevox_info
        """Phase 1: Generate all audio files and calculate their durations."""
        line_data_map: Dict[str, Dict[str, Any]] = {}
        total_lines = sum(len(s.get("lines", [])) for s in scenes)

        with tqdm(total=total_lines, desc="Audio Generation", unit="line") as pbar:
            for scene_idx, scene in enumerate(scenes):
                scene_id = scene["id"]
                bg = scene.get("bg", self.config.get("background", {}).get("default"))
                timeline.add_scene_change(scene_id, bg)

                for idx, line in enumerate(scene.get("lines", []), start=1):
                    line_id = f"{scene_id}_{idx}"

                    if "wait" in line:
                        pbar.set_description(
                            f"Calculating Wait Step (Scene '{scene_id}', Line {idx})"
                        )
                        wait_value = line["wait"]
                        if isinstance(wait_value, dict):
                            duration = float(
                                wait_value.get("duration", 0.0)
                            )  # Ensure float and provide default
                        else:
                            duration = float(wait_value)  # Ensure float

                        timeline.add_event(f"(Wait {duration}s)", duration, text=None)

                        line_data_map[line_id] = {
                            "type": "wait",
                            "duration": duration,
                            "line_config": line,
                            "audio_path": None,
                            "text": None,
                        }
                        pbar.update(1)
                        continue

                    text = line["text"]
                    pbar.set_description(
                        f"Audio Generation (Scene '{scene_id}', Line {idx}: '{text[:30]}...')"
                    )

                    # Generate audio and get speaker info
                    audio_path, speaker_id, generated_text = (
                        self.audio_gen.generate_audio(text, line, line_id)
                    )

                    if not audio_path:
                        raise PipelineError(
                            f"Audio generation failed for line: {line_id}"
                        )

                    # Record VOICEVOX usage information
                    if (
                        generated_text.strip()
                    ):  # Only record if actual voice was generated
                        self.used_voicevox_info.append((speaker_id, generated_text))

                    # Cache the generated audio file
                    audio_cache_data = {
                        "text": text,
                        "line_config": line,
                        "voice_config": self.config.get("voice", {}),
                    }
                    self.cache_manager.save_to_cache(
                        key_data=audio_cache_data,
                        file_name=line_id,
                        extension="wav",
                        source_path=audio_path,
                    )
                    # Ensure audio_path is the cached path for subsequent use
                    audio_path = self.cache_manager.get_cache_path(
                        key_data=audio_cache_data,
                        file_name=line_id,
                        extension="wav",
                    )
                    if (
                        not audio_path.exists()
                    ):  # Fallback if cache path doesn't exist (e.g., no_cache=True)
                        audio_path = (
                            self.temp_dir / f"{line_id}_speech.wav"
                        )  # Use the original temp path

                    insert_config = line.get("insert")
                    duration = 0.0
                    if insert_config:
                        insert_path = Path(insert_config["path"])
                        if insert_path.suffix.lower() in self.video_extensions:
                            duration = get_audio_duration(str(insert_path))
                        else:
                            duration = insert_config.get("duration", 2.0)
                    else:
                        duration = get_audio_duration(str(audio_path))

                    character_name = line.get("speaker_name", "Unknown")
                    timeline.add_event(
                        f'{character_name}: "{text}"', duration, text=text
                    )

                    line_data_map[line_id] = {
                        "type": "talk",
                        "audio_path": audio_path,
                        "duration": duration,
                        "text": text,
                        "line_config": line,
                    }
                    pbar.update(1)
        return line_data_map, self.used_voicevox_info
