import shutil
from pathlib import Path
from typing import Any, Dict, List

from zundamotion.components.video import VideoRenderer
from zundamotion.utils.ffmpeg_utils import add_bgm_to_video, get_audio_duration
from zundamotion.utils.logger import logger


class FinalizePhase:
    def __init__(self, config: Dict[str, Any], temp_dir: Path, jobs: str):
        self.config = config
        self.temp_dir = temp_dir
        self.jobs = jobs
        self.video_renderer = VideoRenderer(self.config, self.temp_dir, self.jobs)

    def run(
        self,
        output_path: str,
        final_clips_for_concat: List[Path],
    ):
        """Phase 4: Concatenate all clips and apply global BGM."""
        logger.info("\n--- Phase 4: Final Concatenation and Global BGM Application ---")
        final_output_path_temp = self.temp_dir / "final_video_no_global_bgm.mp4"
        self.video_renderer.concat_clips(
            final_clips_for_concat, str(final_output_path_temp)
        )

        global_bgm_config = self.config.get("bgm", {})
        global_bgm_path = global_bgm_config.get("path")
        if global_bgm_path:
            logger.info(f"Applying global BGM with '{global_bgm_path}' to final video.")
            add_bgm_to_video(
                video_path=str(final_output_path_temp),
                bgm_path=global_bgm_path,
                output_path=str(Path(output_path)),
                bgm_volume=global_bgm_config.get("volume", 0.5),
                bgm_start_time=global_bgm_config.get("start_time", 0.0),
                fade_in_duration=global_bgm_config.get("fade_in_duration", 0.0),
                fade_out_duration=global_bgm_config.get("fade_out_duration", 0.0),
                video_duration=get_audio_duration(str(final_output_path_temp)),
            )
        else:
            shutil.copy(final_output_path_temp, Path(output_path))
        logger.info("--- Phase 4 Completed ---")
