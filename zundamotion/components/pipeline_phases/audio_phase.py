import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Tuple  # Add this import
from typing import Any, Dict, List, Optional

from tqdm import tqdm

from zundamotion.cache import CacheManager
from zundamotion.components.audio import AudioGenerator
from zundamotion.exceptions import PipelineError
from zundamotion.timeline import Timeline
from zundamotion.utils.subtitle_text import is_effective_subtitle_text
from zundamotion.utils.ffmpeg_params import AudioParams
from zundamotion.utils.ffmpeg_probe import get_audio_duration
from zundamotion.utils.text_processing import parse_reading_markup
from zundamotion.utils.logger import logger, time_log
from zundamotion.utils.face_anim import (
    compute_mouth_timeline,
    generate_blink_timeline,
    deterministic_seed_from_text,
)


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
        self.audio_gen = AudioGenerator(
            self.config, self.temp_dir, audio_params, self.cache_manager
        )  # cache_managerを渡す
        self.video_extensions = self.config.get("system", {}).get(
            "video_extensions",
            [".mp4", ".mov", ".webm", ".avi", ".mkv"],
        )
        self.used_voicevox_info: List[Tuple[int, str]] = (
            []
        )  # Initialize list to store (speaker_id, text)

    @time_log(logger)
    async def run(
        self, scenes: List[Dict[str, Any]], timeline: Timeline
    ) -> Tuple[
        Dict[str, Dict[str, Any]], List[Tuple[int, str]]
    ]:  # Return line_data_map and used_voicevox_info
        """Phase 1: Generate all audio files and calculate their durations."""
        line_data_map: Dict[str, Dict[str, Any]] = {}
        total_lines = sum(len(s.get("lines", [])) for s in scenes)

        with tqdm(
            total=total_lines,
            desc="Audio Generation",
            unit="line",
            leave=False,
            disable=(os.getenv("TQDM_DISABLE") == "1" or not sys.stderr.isatty()),
        ) as pbar:
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

                    # テキスト（表示用）/読み（音声用）の分離
                    original_text = str(line.get("text", ""))
                    # Apply inline reading markup if explicit reading is not provided
                    subtitle_reading_display = str(
                        (self.config.get("subtitle", {}) or {}).get(
                            "reading_display", "none"
                        )
                    ).lower()
                    if line.get("reading") or line.get("read"):
                        read_text = str(line.get("reading") or line.get("read") or original_text)
                        # display text may still contain markup for visual purpose; parse for display only
                        disp_from_markup, _ = parse_reading_markup(
                            original_text, subtitle_reading_display
                        )
                        display_text = str(line.get("subtitle_text") or disp_from_markup)
                    else:
                        disp_from_markup, tts_from_markup = parse_reading_markup(
                            original_text, subtitle_reading_display
                        )
                        read_text = tts_from_markup
                        display_text = str(line.get("subtitle_text") or disp_from_markup)
                    text = display_text
                    effective_subtitle_text = (
                        display_text if is_effective_subtitle_text(display_text) else ""
                    )
                    pbar.set_description(
                        f"Audio Generation (Scene '{scene_id}', Line {idx}: '{text[:30]}...')"
                    )

                    # Generate audio and get speaker info
                    (
                        audio_path,
                        speaker_id,
                        generated_text,
                    ) = await self.audio_gen.generate_audio(read_text, line, line_id)

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
                        "text": read_text,
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
                            duration = (
                                await self.cache_manager.get_or_create_media_duration(
                                    insert_path
                                )
                            )
                        else:
                            duration = insert_config.get("duration", 2.0)
                    else:
                        duration = (
                            await self.cache_manager.get_or_create_media_duration(
                                audio_path
                            )
                        )

                    character_name = line.get("speaker_name", "Unknown")
                    timeline.add_event(
                        f'{character_name}: "{display_text}"',
                        duration,
                        text=(effective_subtitle_text or None),
                    )

                    # ------------------------------
                    # Face animation timelines (mouth + blink)
                    # ------------------------------
                    video_cfg = self.config.get("video", {})
                    anim_cfg = video_cfg.get("face_anim", {})
                    mouth_fps = int(anim_cfg.get("mouth_fps", 15))
                    thr_half = float(anim_cfg.get("mouth_thr_half", 0.2))
                    thr_open = float(anim_cfg.get("mouth_thr_open", 0.5))
                    # Blink settings
                    video_fps = int(video_cfg.get("fps", 30))
                    blink_min = float(anim_cfg.get("blink_min_interval", 2.0))
                    blink_max = float(anim_cfg.get("blink_max_interval", 5.0))
                    blink_close_frames = int(anim_cfg.get("blink_close_frames", 2))

                    # The target character to animate: prefer speaker_name; fallback to first visible character
                    target_name = line.get("speaker_name")
                    if not target_name:
                        try:
                            for ch in (line.get("characters") or []):
                                if ch.get("visible", False) and ch.get("name"):
                                    target_name = ch.get("name")
                                    break
                        except Exception:
                            target_name = None

                    face_anim = None
                    try:
                        # Compute mouth timeline from speech audio only (cached by audio content + params)
                        mouth_segments = []
                        try:
                            st = audio_path.stat()
                            key_data = {
                                "op": "mouth_timeline",
                                "audio_path": str(audio_path.resolve()),
                                "size": st.st_size,
                                "mtime": int(st.st_mtime),
                                "fps": int(mouth_fps),
                                "thr_half": float(thr_half),
                                "thr_open": float(thr_open),
                            }

                            async def _create_mouth_json(out_path: Path) -> Path:
                                segs = compute_mouth_timeline(
                                    audio_path,
                                    fps=mouth_fps,
                                    thr_half_ratio=thr_half,
                                    thr_open_ratio=thr_open,
                                )
                                with open(out_path, "w", encoding="utf-8") as _f:
                                    json.dump({"segments": segs}, _f, ensure_ascii=False)
                                return out_path

                            mouth_json_path = await self.cache_manager.get_or_create(
                                key_data=key_data,
                                file_name="face_mouth",
                                extension="json",
                                creator_func=_create_mouth_json,
                            )
                            with open(mouth_json_path, "r", encoding="utf-8") as _f:
                                mouth_segments = (json.load(_f) or {}).get("segments", [])
                        except Exception:
                            # Fallback: compute inline on any cache/read error
                            mouth_segments = compute_mouth_timeline(
                                audio_path,
                                fps=mouth_fps,
                                thr_half_ratio=thr_half,
                                thr_open_ratio=thr_open,
                            )

                        # Deterministic blink schedule per line
                        seed = deterministic_seed_from_text(line_id)
                        blink_segments = generate_blink_timeline(
                            duration=float(duration),
                            fps=video_fps,
                            min_interval_sec=blink_min,
                            max_interval_sec=blink_max,
                            close_frames=blink_close_frames,
                            seed=seed,
                        )
                        face_anim = {
                            "target_name": target_name,
                            "mouth": mouth_segments,
                            "eyes": blink_segments,
                            "meta": {
                                "mouth_fps": mouth_fps,
                                "thr_half": thr_half,
                                "thr_open": thr_open,
                                "blink_min_interval": blink_min,
                                "blink_max_interval": blink_max,
                                "blink_close_frames": blink_close_frames,
                            },
                        }
                    except Exception as e:
                        logger.debug(f"Face animation timeline generation failed for {line_id}: {e}")

                    line_data_map[line_id] = {
                        "type": "talk",
                        "audio_path": audio_path,
                        "duration": duration,
                        "text": effective_subtitle_text,
                        "tts_text": read_text,
                        "line_config": line,
                        "face_anim": face_anim,
                    }
                    pbar.update(1)
        # Ensure a clean newline after closing the progress bar
        try:
            tqdm.write("", file=sys.stderr)
        except Exception:
            pass
        return line_data_map, self.used_voicevox_info
