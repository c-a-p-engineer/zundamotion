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
from .utils.logger import logger


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
            line_data_map = audio_phase.run(scenes)

            video_phase = VideoPhase(
                self.config, temp_dir, self.cache_manager, self.jobs
            )
            all_clips = video_phase.run(scenes, line_data_map)

            bgm_phase = BGMPhase(self.config, temp_dir)
            final_clips_for_concat = bgm_phase.run(scenes, all_clips)

            finalize_phase = FinalizePhase(self.config, temp_dir, self.jobs)
            finalize_phase.run(output_path, final_clips_for_concat)

            logger.info("--- Video Generation Pipeline Completed ---")


def run_generation(
    script_path: str,
    output_path: str,
    no_cache: bool = False,
    cache_refresh: bool = False,
    jobs: str = "1",
):
    """
    High-level function to run the entire generation process.
    """
    # Get the path to the default config file
    default_config_path = Path(__file__).parent / "templates" / "config.yaml"

    # Load script and config
    config = load_script_and_config(script_path, str(default_config_path))

    # Create and run the pipeline
    pipeline = GenerationPipeline(config, no_cache, cache_refresh, jobs)
    pipeline.run(output_path)
