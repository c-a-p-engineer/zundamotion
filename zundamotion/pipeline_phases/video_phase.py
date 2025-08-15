import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from tqdm import tqdm

from zundamotion.cache import CacheManager
from zundamotion.components.subtitle import SubtitleGenerator
from zundamotion.components.video import VideoRenderer
from zundamotion.exceptions import PipelineError
from zundamotion.utils.ffmpeg_utils import get_audio_duration
from zundamotion.utils.logger import logger


class VideoPhase:
    def __init__(
        self,
        config: Dict[str, Any],
        temp_dir: Path,
        cache_manager: CacheManager,
        jobs: str,
    ):
        self.config = config
        self.temp_dir = temp_dir
        self.cache_manager = cache_manager
        self.jobs = jobs
        self.subtitle_gen = SubtitleGenerator(self.config)
        self.video_renderer = VideoRenderer(self.config, self.temp_dir, self.jobs)
        self.video_extensions = self.config.get("system", {}).get(
            "video_extensions",
            [".mp4", ".mov", ".webm", ".avi", ".mkv"],
        )

    def _generate_scene_hash(self, scene: Dict[str, Any]) -> Dict[str, Any]:
        """Generates a dictionary for scene hash based on its content and relevant config."""
        return {
            "id": scene.get("id"),
            "lines": scene.get("lines", []),
            "bg": scene.get("bg"),
            "bgm": scene.get("bgm"),
            "voice_config": self.config.get("voice", {}),
            "video_config": self.config.get("video", {}),
            "subtitle_config": self.config.get("subtitle", {}),
            "bgm_config": self.config.get("bgm", {}),
            "background_default": self.config.get("background", {}).get("default"),
        }

    def run(
        self,
        scenes: List[Dict[str, Any]],
        line_data_map: Dict[str, Dict[str, Any]],
    ) -> List[Path]:
        """Phase 2: Render video clips for each scene."""
        logger.info(
            "\n--- Phase 2: Preparing scene backgrounds and rendering clips ---"
        )
        all_clips: List[Path] = []
        bg_default = self.config.get("background", {}).get("default")
        total_scenes = len(scenes)

        with tqdm(
            total=total_scenes, desc="Scene Rendering", unit="scene"
        ) as pbar_scenes:
            for scene_idx, scene in enumerate(scenes):
                scene_id = scene["id"]
                scene_hash_data = self._generate_scene_hash(scene)

                cached_scene_video_path = self.cache_manager.get_cached_path(
                    key_data=scene_hash_data,
                    file_name=f"scene_{scene_id}",
                    extension="mp4",
                )
                if cached_scene_video_path:
                    all_clips.append(cached_scene_video_path)
                    pbar_scenes.update(1)
                    continue

                pbar_scenes.set_description(
                    f"Scene Rendering (Scene {scene_idx + 1}/{total_scenes}: '{scene_id}')"
                )

                bg_image = scene.get("bg", bg_default)
                is_bg_video = Path(bg_image).suffix.lower() in self.video_extensions

                scene_duration = sum(
                    line_data_map[f"{scene_id}_{idx + 1}"]["duration"]
                    for idx, line in enumerate(scene.get("lines", []))
                )

                scene_bg_video_path: Optional[Path] = None
                if is_bg_video:
                    scene_bg_video_filename = f"scene_bg_{scene_id}"
                    scene_bg_video_path = (
                        self.video_renderer.render_looped_background_video(
                            bg_image, scene_duration, scene_bg_video_filename
                        )
                    )
                    logger.debug(
                        f"Generated looped scene background video -> {scene_bg_video_path.name}"
                    )

                scene_line_clips: List[Path] = []
                current_scene_time = 0.0
                for idx, line in enumerate(scene.get("lines", []), start=1):
                    line_id = f"{scene_id}_{idx}"
                    line_data = line_data_map[line_id]
                    duration = line_data["duration"]
                    line_config = line_data["line_config"]

                    background_config = {
                        "type": "video" if is_bg_video else "image",
                        "path": str(scene_bg_video_path) if is_bg_video else bg_image,
                        "start_time": current_scene_time,
                    }

                    if line_data["type"] == "wait":
                        logger.debug(
                            f"Rendering wait clip for {duration}s (Scene '{scene_id}', Line {idx})"
                        )
                        wait_cache_data = {
                            "type": "wait",
                            "duration": duration,
                            "bg_image_path": bg_image,
                            "is_bg_video": is_bg_video,
                            "start_time": current_scene_time,
                            "video_config": self.config.get("video", {}),
                            "line_config": line_config,
                        }
                        clip_path = self.cache_manager.get_or_create(
                            key_data=wait_cache_data,
                            file_name=line_id,
                            extension="mp4",
                            creator_func=lambda: self.video_renderer.render_wait_clip(
                                duration, background_config, line_id, line_config
                            ),
                        )
                        if clip_path:
                            scene_line_clips.append(clip_path)
                    else:  # Talk Step
                        text = line_data["text"]
                        audio_path = line_data["audio_path"]
                        logger.debug(
                            f"Rendering clip for line '{text[:30]}...' (Scene '{scene_id}', Line {idx})"
                        )
                        drawtext_filter = self.subtitle_gen.get_drawtext_filter(
                            text, duration, line_config
                        )
                        audio_cache_key_data = {
                            "text": text,
                            "line_config": line_config,
                            "voice_config": self.config.get("voice", {}),
                        }
                        video_cache_data = {
                            "type": "talk",
                            "audio_cache_key": self.cache_manager._generate_hash(
                                audio_cache_key_data
                            ),
                            "duration": duration,
                            "drawtext_filter": drawtext_filter,
                            "bg_image_path": bg_image,
                            "is_bg_video": is_bg_video,
                            "start_time": current_scene_time,
                            "video_config": self.config.get("video", {}),
                            "subtitle_config": self.config.get("subtitle", {}),
                            "bgm_config": self.config.get("bgm", {}),
                            "insert_config": line_config.get("insert"),
                        }

                        clip_path = self.cache_manager.get_or_create(
                            key_data=video_cache_data,
                            file_name=line_id,
                            extension="mp4",
                            creator_func=lambda: self.video_renderer.render_clip(
                                audio_path,
                                duration,
                                drawtext_filter,
                                background_config,
                                line.get("characters", []),
                                line_id,
                                insert_config=line_config.get("insert"),
                            ),
                        )
                        if clip_path:
                            scene_line_clips.append(clip_path)
                        else:
                            raise PipelineError(
                                f"Clip rendering failed for line: {line_id}"
                            )

                    current_scene_time += duration

                if scene_line_clips:
                    scene_output_path = self.temp_dir / f"scene_output_{scene_id}.mp4"
                    self.video_renderer.concat_clips(
                        scene_line_clips, str(scene_output_path)
                    )
                    logger.info(f"Concatenated scene clips -> {scene_output_path.name}")
                    all_clips.append(scene_output_path)
                    self.cache_manager.cache_file(
                        source_path=scene_output_path,
                        key_data=scene_hash_data,
                        file_name=f"scene_{scene_id}",
                        extension="mp4",
                    )

                if scene_bg_video_path and scene_bg_video_path.exists():
                    scene_bg_video_path.unlink()
                    logger.debug(
                        f"Cleaned up temporary scene background video -> {scene_bg_video_path.name}"
                    )
                pbar_scenes.update(1)
        logger.info("--- Phase 2 Completed ---")
        return all_clips
