from pathlib import Path
from typing import Any, Dict, List

from tqdm import tqdm

from zundamotion.exceptions import PipelineError
from zundamotion.utils.ffmpeg_utils import (
    AudioParams,
    add_bgm_to_video,
    get_audio_duration,
    get_media_duration,
)
from zundamotion.utils.logger import logger, time_log


class BGMPhase:
    def __init__(self, config: Dict[str, Any], temp_dir: Path):
        self.config = config
        self.temp_dir = temp_dir

    @time_log(logger)
    async def run(  # async を追加
        self,
        scenes: List[Dict[str, Any]],
        all_clips: List[Path],
    ) -> List[Path]:
        """Phase 3: Apply BGM to each scene clip."""
        final_clips_for_concat: List[Path] = []
        total_scenes = len(scenes)
        with tqdm(total=total_scenes, desc="BGM Application", unit="scene") as pbar_bgm:
            for scene_idx, scene in enumerate(scenes):
                pbar_bgm.set_description(
                    f"BGM Application (Scene {scene_idx + 1}/{total_scenes}: '{scene['id']}')"
                )
                if scene_idx >= len(all_clips):
                    raise PipelineError(
                        "Scene index out of bounds for all_clips. This indicates a mismatch between scenes and generated clips."
                    )
                scene_clip_path = all_clips[scene_idx]
                scene_bgm_config = scene.get("bgm", {})
                bgm_path = scene_bgm_config.get("path")
                if bgm_path:
                    logger.info(
                        f"Applying BGM to scene {scene_idx + 1} ('{scene['id']}') with '{bgm_path}'"
                    )
                    scene_output_with_bgm_path = (
                        self.temp_dir / f"scene_with_bgm_{scene_idx}.mp4"
                    )
                    audio_config = self.config.get("audio", {})
                    audio_params = AudioParams(
                        sample_rate=audio_config.get("sample_rate", 48000),
                        channels=audio_config.get("channels", 2),
                        codec=audio_config.get("codec", "aac"),
                        bitrate_kbps=audio_config.get("bitrate_kbps", 192),
                    )
                    await add_bgm_to_video(  # await を追加
                        video_path=str(scene_clip_path),
                        bgm_path=bgm_path,
                        output_path=str(scene_output_with_bgm_path),
                        audio_params=audio_params,
                        bgm_volume=scene_bgm_config.get(
                            "volume", self.config.get("bgm", {}).get("volume", 0.5)
                        ),
                        bgm_start_time=scene_bgm_config.get(
                            "start_time",
                            self.config.get("bgm", {}).get("start_time", 0.0),
                        ),
                        fade_in_duration=scene_bgm_config.get(
                            "fade_in_duration",
                            self.config.get("bgm", {}).get("fade_in_duration", 0.0),
                        ),
                        fade_out_duration=scene_bgm_config.get(
                            "fade_out_duration",
                            self.config.get("bgm", {}).get("fade_out_duration", 0.0),
                        ),
                        video_duration=get_media_duration(str(scene_clip_path)),
                    )
                    final_clips_for_concat.append(scene_output_with_bgm_path)
                else:
                    final_clips_for_concat.append(scene_clip_path)
                pbar_bgm.update(1)
        return final_clips_for_concat
