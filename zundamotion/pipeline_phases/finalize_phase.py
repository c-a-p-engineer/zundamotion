import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Tuple

from zundamotion.components.video import VideoRenderer
from zundamotion.reporting.voice_report_generator import generate_voice_report
from zundamotion.utils.ffmpeg_utils import (
    add_bgm_to_video,
    apply_transition,
    get_audio_duration,
)
from zundamotion.utils.logger import logger, time_log


class FinalizePhase:
    def __init__(self, config: Dict[str, Any], temp_dir: Path, jobs: str):
        self.config = config
        self.temp_dir = temp_dir
        self.jobs = jobs
        self.video_renderer = VideoRenderer(self.config, self.temp_dir, self.jobs)

    @time_log(logger)
    def run(
        self,
        output_path: str,
        scenes: List[Dict[str, Any]],
        final_clips_for_concat: List[Path],
        used_voicevox_info: List[Tuple[int, str]],
    ):
        """Phase 4: Concatenate all clips and apply global BGM and scene transitions."""
        processed_clips: List[Path] = []
        if not final_clips_for_concat:
            logger.warning("No clips to process in FinalizePhase.")
            return

        # Process clips, applying transitions where specified
        stitched_clips: List[Path] = []
        current_clip: Path = final_clips_for_concat[0]

        for i in range(len(final_clips_for_concat) - 1):
            next_clip: Path = final_clips_for_concat[i + 1]
            transition_config = scenes[i].get("transition")

            if transition_config:
                transition_type = transition_config["type"]
                transition_duration = transition_config["duration"]

                current_clip_duration = get_audio_duration(str(current_clip))
                offset = current_clip_duration - transition_duration
                if offset < 0:
                    logger.warning(
                        f"Transition duration ({transition_duration}s) is longer than "
                        f"the preceding clip ({current_clip_duration}s) for scene '{scenes[i]['id']}'. "
                        "Adjusting offset to 0. This might cause unexpected behavior."
                    )
                    offset = 0

                transition_output_path = self.temp_dir / f"transition_{i}_{i+1}.mp4"
                logger.info(
                    f"Applying '{transition_type}' transition ({transition_duration}s) "
                    f"between scene '{scenes[i]['id']}' and '{scenes[i+1]['id']}'."
                )
                apply_transition(
                    input_video1_path=str(current_clip),
                    input_video2_path=str(next_clip),
                    output_path=str(transition_output_path),
                    transition_type=transition_type,
                    duration=transition_duration,
                    offset=offset,
                )
                current_clip = transition_output_path
            else:
                stitched_clips.append(current_clip)
                current_clip = next_clip

        stitched_clips.append(current_clip)

        final_output_path_temp = self.temp_dir / "final_video_no_global_bgm.mp4"
        if stitched_clips:
            self.video_renderer.concat_clips(
                stitched_clips,
                str(final_output_path_temp),
            )
        else:
            logger.warning("No clips to concatenate after transition processing.")
            return

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

        # Generate VOICEVOX usage report
        output_path_base = Path(output_path)
        voice_report_output_path = output_path_base.with_suffix(".voice_report.md")
        generate_voice_report(
            used_voicevox_info,
            str(voice_report_output_path),
            os.getenv("VOICEVOX_URL", "http://127.0.0.1:50021"),
        )
