import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from tqdm import tqdm

from .cache import CacheManager
from .components.audio import AudioGenerator
from .components.script_loader import load_script_and_config
from .exceptions import PipelineError
from .pipeline_phases import AudioPhase, BGMPhase, FinalizePhase, VideoPhase
from .timeline import Timeline
from .utils.logger import logger, time_log


class GenerationPipeline:
    def __init__(
        self,
        config: Dict[str, Any],
        no_cache: bool = False,
        cache_refresh: bool = False,
        jobs: str = "1",
    ):
        self.config = config
        self.no_cache = no_cache
        self.cache_refresh = cache_refresh
        self.jobs = jobs
        self.cache_manager = CacheManager(
            cache_dir=Path(self.config.get("system", {}).get("cache_dir", "cache")),
            no_cache=self.no_cache,
            cache_refresh=self.cache_refresh,
        )
        self.timeline = Timeline()

    @time_log(logger)
    def run(self, output_path: str):
        """
        Executes the full video generation pipeline.

        Args:
            output_path (str): The final output video file path.
        """
        with tempfile.TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            logger.info(f"Using temporary directory: {temp_dir}")
            logger.info(
                f"Using persistent cache directory: {self.cache_manager.cache_dir}"
            )

            script = self.config.get("script", {})
            scenes = script.get("scenes", [])

            # Execute pipeline phases
            audio_phase = AudioPhase(self.config, temp_dir, self.cache_manager)
            line_data_map = audio_phase.run(scenes, self.timeline)

            video_phase = VideoPhase(
                self.config, temp_dir, self.cache_manager, self.jobs
            )
            all_clips = video_phase.run(scenes, line_data_map, self.timeline)

            bgm_phase = BGMPhase(self.config, temp_dir)
            final_clips_for_concat = bgm_phase.run(scenes, all_clips)

            finalize_phase = FinalizePhase(self.config, temp_dir, self.jobs)
            finalize_phase.run(
                output_path, scenes, final_clips_for_concat
            )  # Pass scenes to FinalizePhase

            # Save the timeline if enabled
            timeline_config = self.config.get("system", {}).get("timeline", {})
            if timeline_config.get("enabled", False):
                timeline_format = timeline_config.get("format", "md")
                output_path_base = Path(output_path)

                if timeline_format in ["md", "both"]:
                    timeline_output_path_md = output_path_base.with_suffix(".md")
                    self.timeline.save_as_md(timeline_output_path_md)
                    logger.info(f"Timeline saved to {timeline_output_path_md}")
                if timeline_format in ["csv", "both"]:
                    timeline_output_path_csv = output_path_base.with_suffix(".csv")
                    self.timeline.save_as_csv(timeline_output_path_csv)
                    logger.info(f"Timeline saved to {timeline_output_path_csv}")

            # Save subtitle file if enabled
            subtitle_file_config = self.config.get("system", {}).get(
                "subtitle_file", {}
            )
            if subtitle_file_config.get("enabled", False):
                subtitle_format = subtitle_file_config.get("format", "srt")
                output_path_base = Path(output_path)

                if subtitle_format in ["srt", "both"]:
                    subtitle_output_path_srt = output_path_base.with_suffix(".srt")
                    self.timeline.save_subtitles(subtitle_output_path_srt, format="srt")
                    logger.info(f"Subtitle file saved to {subtitle_output_path_srt}")
                if subtitle_format in ["ass", "both"]:
                    subtitle_output_path_ass = output_path_base.with_suffix(".ass")
                    self.timeline.save_subtitles(subtitle_output_path_ass, format="ass")
                    logger.info(f"Subtitle file saved to {subtitle_output_path_ass}")

            logger.info("--- Video Generation Pipeline Completed ---")


def run_generation(
    script_path: str,
    output_path: str,
    no_cache: bool = False,
    cache_refresh: bool = False,
    jobs: str = "1",
    timeline_format: Optional[str] = None,
    no_timeline: bool = False,
    subtitle_file_format: Optional[str] = None,
    no_subtitle_file: bool = False,
):
    """
    High-level function to run the entire generation process.
    """
    # Get the path to the default config file
    default_config_path = Path(__file__).parent / "templates" / "config.yaml"

    # Load script and config
    config = load_script_and_config(script_path, str(default_config_path))

    # Override timeline settings from CLI
    if no_timeline:
        config.setdefault("system", {}).setdefault("timeline", {})["enabled"] = False
    elif timeline_format:
        config.setdefault("system", {}).setdefault("timeline", {})["enabled"] = True
        config["system"]["timeline"]["format"] = timeline_format

    # Override subtitle file settings from CLI
    if no_subtitle_file:
        config.setdefault("system", {}).setdefault("subtitle_file", {})[
            "enabled"
        ] = False
    elif subtitle_file_format:
        config.setdefault("system", {}).setdefault("subtitle_file", {})[
            "enabled"
        ] = True
        config["system"]["subtitle_file"]["format"] = subtitle_file_format

    # Create and run the pipeline
    pipeline = GenerationPipeline(config, no_cache, cache_refresh, jobs)
    pipeline.run(output_path)
