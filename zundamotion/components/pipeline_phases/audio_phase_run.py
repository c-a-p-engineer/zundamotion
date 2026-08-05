"""AudioPhase line preparation and synthesis orchestration."""

import asyncio
import json
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
from zundamotion.utils.face_anim import (
    deterministic_seed_from_text,
    generate_blink_timeline,
)
from zundamotion.utils.logger import logger, time_log

from .audio_phase_entries import prepare_audio_entries


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
        ) as pbar:
            for entry in ordered_entries:
                entry_type = entry["entry_type"]
                scene_id = entry["scene_id"]

                if entry_type == "bgm":
                    bgm_cfg = entry["bgm_cfg"]
                    timeline.add_bgm_event(
                        str(bgm_cfg.get("id")),
                        str(bgm_cfg.get("action")),
                        fade=bgm_cfg.get("fade"),
                    )
                    continue

                if entry_type == "topic":
                    timeline.add_topic(entry["topic"])
                    continue

                line = entry["line"]
                line_idx = entry["line_idx"]
                line_id = entry["line_id"]
                incoming_audio_overlays: List[Dict[str, Any]] = []
                if pending_l_cut_audio is not None:
                    incoming_audio_overlays.append(pending_l_cut_audio)
                    pending_l_cut_audio = None

                if entry_type == "wait":
                    pbar.set_description(
                        f"Calculating Wait Step (Scene '{scene_id}', Line {line_idx})"
                    )
                    wait_value = line["wait"]
                    if isinstance(wait_value, dict):
                        duration = float(wait_value.get("duration", 0.0))
                    else:
                        duration = float(wait_value)

                    timeline.add_event(f"(Wait {duration}s)", duration, text=None)
                    line_data_map[line_id] = {
                        "type": "wait",
                        "duration": duration,
                        "line_config": line,
                        "audio_path": None,
                        "text": None,
                        "extra_audio_overlays": incoming_audio_overlays,
                    }
                    pbar.update(1)
                    continue

                if entry_type == "image_layer":
                    pbar.set_description(
                        f"Registering Image Layer Step (Scene '{scene_id}', Line {line_idx})"
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
                    pbar.update(1)
                    continue

                text = entry["display_text"]
                read_text = entry["read_text"]
                effective_subtitle_text = entry["effective_subtitle_text"]
                pbar.set_description(
                    f"Audio Generation (Scene '{scene_id}', Line {line_idx}: '{text[:30]}...')"
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
                needs_line_audio_cache = bool(
                    line.get("audio_filter")
                    or line.get("sound_effects")
                    or line.get("voice_layers")
                    or not Path(audio_path).exists()
                )
                if needs_line_audio_cache:
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

                    async def _filter_creator(output_path: Path) -> Path:
                        await apply_audio_filter(
                            str(audio_path),
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
                        insert_speed = max(0.25, min(4.0, insert_speed))
                        duration = duration / insert_speed
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

                voice_layers_cfg = [
                    layer
                    for layer in (line.get("voice_layers") or [])
                    if isinstance(layer, dict)
                ]

                character_name = line.get("speaker_name")
                if not character_name and voice_layers_cfg:
                    names = [
                        layer.get("speaker_name")
                        for layer in voice_layers_cfg
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

                video_cfg = self.config.get("video", {})
                anim_cfg = video_cfg.get("face_anim", {})
                mouth_fps = int(anim_cfg.get("mouth_fps", 15))
                thr_half = float(anim_cfg.get("mouth_thr_half", 0.2))
                thr_open = float(anim_cfg.get("mouth_thr_open", 0.5))
                video_fps = int(video_cfg.get("fps", 30))
                blink_min = float(anim_cfg.get("blink_min_interval", 2.0))
                blink_max = float(anim_cfg.get("blink_max_interval", 5.0))
                blink_close_frames = int(anim_cfg.get("blink_close_frames", 2))

                mouth_segment_cache: Dict[str, List[Dict[str, Any]]] = {}

                async def _load_mouth_segments(
                    target_audio_path: Path,
                ) -> List[Dict[str, Any]]:
                    try:
                        cache_key_path = target_audio_path.resolve(strict=False)
                    except Exception:
                        cache_key_path = target_audio_path.absolute()
                    cache_key = str(cache_key_path)
                    if cache_key in mouth_segment_cache:
                        return mouth_segment_cache[cache_key]

                    try:
                        stat = target_audio_path.stat()
                        key_data = {
                            "op": "mouth_timeline",
                            "audio_path": str(cache_key_path),
                            "size": stat.st_size,
                            "mtime": int(stat.st_mtime),
                            "fps": int(mouth_fps),
                            "thr_half": float(thr_half),
                            "thr_open": float(thr_open),
                        }

                        async def _create_mouth_json(out_path: Path) -> Path:
                            from . import audio_phase as audio_phase_module

                            segments = audio_phase_module.compute_mouth_timeline(
                                target_audio_path,
                                fps=mouth_fps,
                                thr_half_ratio=thr_half,
                                thr_open_ratio=thr_open,
                            )
                            with open(out_path, "w", encoding="utf-8") as output_file:
                                json.dump(
                                    {"segments": segments},
                                    output_file,
                                    ensure_ascii=False,
                                )
                            return out_path

                        mouth_json_path = await self.cache_manager.get_or_create(
                            key_data=key_data,
                            file_name="face_mouth",
                            extension="json",
                            creator_func=_create_mouth_json,
                        )
                        with open(
                            mouth_json_path,
                            "r",
                            encoding="utf-8",
                        ) as input_file:
                            segments = (json.load(input_file) or {}).get(
                                "segments",
                                [],
                            )
                    except Exception:
                        try:
                            from . import audio_phase as audio_phase_module

                            segments = audio_phase_module.compute_mouth_timeline(
                                target_audio_path,
                                fps=mouth_fps,
                                thr_half_ratio=thr_half,
                                thr_open_ratio=thr_open,
                            )
                        except Exception as err:
                            logger.debug(
                                "Mouth timeline computation failed for %s: %s",
                                line_id,
                                err,
                            )
                            segments = []

                    mouth_segment_cache[cache_key] = segments
                    return segments

                face_anim: Optional[Any] = None
                line_mouth_sync = bool(line.get("mouth_sync", True))

                if voice_layers_cfg and voice_layer_segments:
                    layer_face_anims: List[Dict[str, Any]] = []
                    for layer_idx, layer_cfg in enumerate(voice_layers_cfg):
                        target_name = layer_cfg.get("speaker_name")
                        if not target_name or self._is_face_anim_target_hidden(
                            line,
                            str(target_name),
                        ):
                            continue
                        matching_segments = [
                            segment
                            for segment in voice_layer_segments
                            if segment.get("layer_origin") == layer_idx
                        ]
                        if not matching_segments:
                            continue
                        mouth_segments: List[Dict[str, Any]] = []
                        if bool(layer_cfg.get("mouth_sync", line_mouth_sync)):
                            for segment_info in matching_segments:
                                audio_segment = segment_info.get("audio_path")
                                if not audio_segment:
                                    continue
                                try:
                                    audio_segment_path = (
                                        audio_segment
                                        if isinstance(audio_segment, Path)
                                        else Path(str(audio_segment))
                                    )
                                except Exception:
                                    continue
                                segments = await _load_mouth_segments(
                                    audio_segment_path
                                )
                                if not segments:
                                    continue
                                offset = float(segment_info.get("start_time", 0.0))
                                for segment in segments:
                                    start_value = (
                                        float(segment.get("start", 0.0)) + offset
                                    )
                                    end_value = (
                                        float(segment.get("end", 0.0)) + offset
                                    )
                                    if end_value <= start_value:
                                        continue
                                    mouth_segments.append(
                                        {
                                            "start": start_value,
                                            "end": end_value,
                                            "state": segment.get("state"),
                                        }
                                    )
                            mouth_segments.sort(key=lambda item: item["start"])
                        seed = deterministic_seed_from_text(
                            f"{line_id}:{target_name}"
                        )
                        blink_segments = generate_blink_timeline(
                            duration=float(duration),
                            fps=video_fps,
                            min_interval_sec=blink_min,
                            max_interval_sec=blink_max,
                            close_frames=blink_close_frames,
                            seed=seed,
                        )
                        layer_face_anims.append(
                            {
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
                        )
                    if layer_face_anims:
                        face_anim = layer_face_anims

                if face_anim is None:
                    target_name = line.get("speaker_name")
                    if not target_name:
                        try:
                            for character in line.get("characters") or []:
                                if character.get("visible", False) and character.get(
                                    "name"
                                ):
                                    target_name = character.get("name")
                                    break
                        except Exception:
                            target_name = None
                    if not target_name and voice_layers_cfg:
                        for layer in voice_layers_cfg:
                            if layer.get("speaker_name"):
                                target_name = layer.get("speaker_name")
                                break

                    if target_name and not self._is_face_anim_target_hidden(
                        line,
                        str(target_name),
                    ):
                        try:
                            mouth_segments = (
                                await _load_mouth_segments(audio_path)
                                if line_mouth_sync
                                else []
                            )
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
                        except Exception as exc:
                            logger.debug(
                                "Face animation timeline generation failed for %s: %s",
                                line_id,
                                exc,
                            )

                line_data_map[line_id] = {
                    "type": "talk",
                    "audio_path": audio_path,
                    "duration": duration,
                    "audio_full_duration": audio_full_duration,
                    "text": effective_subtitle_text,
                    "tts_text": read_text,
                    "line_config": line,
                    "face_anim": face_anim,
                    "extra_audio_overlays": incoming_audio_overlays,
                }
                pbar.update(1)

        try:
            tqdm.write("", file=sys.stderr)
        except Exception:
            pass
        return line_data_map, self.used_voicevox_info
