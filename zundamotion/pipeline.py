import asyncio  # 追加
import shutil
import statistics
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from tqdm import tqdm

from .cache import CacheManager
from .components.pipeline_phases import AudioPhase, BGMPhase, FinalizePhase, VideoPhase
from .components.script_loader import load_script_and_config
from .exceptions import PipelineError
from .timeline import Timeline
from .utils.ffmpeg_utils import AudioParams, VideoParams
from .utils.logger import KVLogger, logger, time_log


class GenerationPipeline:
    def __init__(
        self,
        config: Dict[str, Any],
        no_cache: bool = False,
        cache_refresh: bool = False,
        jobs: str = "1",
        video_params: Optional[VideoParams] = None,
        audio_params: Optional[AudioParams] = None,
        hw_encoder: str = "auto",
        quality: str = "balanced",
    ):
        self.config = config
        self.no_cache = no_cache
        self.cache_refresh = cache_refresh
        self.jobs = jobs
        self.hw_encoder = hw_encoder
        self.quality = quality
        self.cache_manager = CacheManager(
            cache_dir=Path(self.config.get("system", {}).get("cache_dir", "cache")),
            no_cache=self.no_cache,
            cache_refresh=self.cache_refresh,
        )
        self.timeline = Timeline()
        self.video_params = video_params if video_params else VideoParams()
        self.audio_params = audio_params if audio_params else AudioParams()
        self.stats: Dict[str, Any] = {
            "phases": {},
            "total_duration": 0.0,
            "clips_processed": 0,
            "clip_durations": [],
        }

    async def _run_phase(self, phase_name: str, func, *args, **kwargs):
        start_time = time.time()
        if isinstance(logger, KVLogger):
            logger.kv_info(
                f"--- Starting Phase: {phase_name} ---",
                kv_pairs={"Event": "PhaseStart", "Phase": phase_name},
            )
        else:
            logger.info(f"--- Starting Phase: {phase_name} ---")

        result = await func(*args, **kwargs)

        end_time = time.time()
        duration = end_time - start_time
        self.stats["phases"][phase_name] = {"duration": duration}

        if isinstance(logger, KVLogger):
            logger.kv_info(
                f"--- Finished Phase: {phase_name}. Duration: {duration:.2f} seconds ---",
                kv_pairs={
                    "Event": "PhaseFinish",
                    "Phase": phase_name,
                    "Duration": f"{duration:.2f}s",
                },
            )
        else:
            logger.info(
                f"--- Finished Phase: {phase_name}. Duration: {duration:.2f} seconds ---"
            )
        return result

    @time_log(logger)
    async def run(self, output_path: str):
        """
        Executes the full video generation pipeline.

        Args:
            output_path (str): The final output video file path.
        """
        pipeline_start_time = time.time()
        with tempfile.TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            if isinstance(logger, KVLogger):
                logger.kv_info(
                    f"Using temporary directory: {temp_dir}",
                    kv_pairs={"TempDir": str(temp_dir)},
                )
                logger.kv_info(
                    f"Using persistent cache directory: {self.cache_manager.cache_dir}",
                    kv_pairs={"CacheDir": str(self.cache_manager.cache_dir)},
                )
            else:
                logger.info(f"Using temporary directory: {temp_dir}")
                logger.info(
                    f"Using persistent cache directory: {self.cache_manager.cache_dir}"
                )

            script = self.config.get("script", {})
            scenes = script.get("scenes", [])

            # Phase 1: Audio Generation
            audio_phase = AudioPhase(
                self.config, temp_dir, self.cache_manager, self.audio_params
            )
            line_data_map, used_voicevox_info = await self._run_phase(
                "AudioPhase", audio_phase.run, scenes, self.timeline
            )

            # Phase 2: Video Generation
            video_phase = await VideoPhase.create(
                self.config,
                temp_dir,
                self.cache_manager,
                self.jobs,
            )
            all_clips = await self._run_phase(
                "VideoPhase", video_phase.run, scenes, line_data_map, self.timeline
            )
            self.stats["clips_processed"] = len(all_clips)
            # all_clips が Path オブジェクトのリストであると仮定し、get_media_duration を使用して duration を取得
            # get_media_duration は非同期関数なので、asyncio.gather を使って並行して duration を取得
            clip_durations_tasks = [
                self.cache_manager.get_or_create_media_duration(clip)
                for clip in all_clips
            ]
            self.stats["clip_durations"] = await asyncio.gather(*clip_durations_tasks)
            # Phase 3: BGM Mixing
            bgm_phase = BGMPhase(self.config, temp_dir)
            final_clips_for_concat = await self._run_phase(
                "BGMPhase", bgm_phase.run, scenes, all_clips
            )

            # Phase 4: Finalize Video
            finalize_phase = FinalizePhase(
                self.config,
                temp_dir,
                self.cache_manager,
                self.video_params,
                self.audio_params,
                self.hw_encoder,
                self.quality,
            )
            final_video_path = await self._run_phase(
                "FinalizePhase",
                finalize_phase.run,
                scenes,
                self.timeline,
                line_data_map,
                final_clips_for_concat,
                used_voicevox_info,
            )
            # 最終的な動画をoutput_pathにコピー
            shutil.copy(final_video_path, output_path)
            if isinstance(logger, KVLogger):
                logger.kv_info(
                    f"Final video saved to {output_path}",
                    kv_pairs={"OutputPath": str(output_path)},
                )
            else:
                logger.info(f"Final video saved to {output_path}")

            # Save the timeline if enabled
            timeline_config = self.config.get("system", {}).get("timeline", {})
            if timeline_config.get("enabled", False):
                timeline_format = timeline_config.get("format", "md")
                output_path_base = Path(output_path)

                if timeline_format in ["md", "both"]:
                    timeline_output_path_md = output_path_base.with_suffix(".md")
                    self.timeline.save_as_md(timeline_output_path_md)
                    if isinstance(logger, KVLogger):
                        logger.kv_info(
                            f"Timeline saved to {timeline_output_path_md}",
                            kv_pairs={"TimelinePathMD": str(timeline_output_path_md)},
                        )
                    else:
                        logger.info(f"Timeline saved to {timeline_output_path_md}")
                if timeline_format in ["csv", "both"]:
                    timeline_output_path_csv = output_path_base.with_suffix(".csv")
                    self.timeline.save_as_csv(timeline_output_path_csv)
                    if isinstance(logger, KVLogger):
                        logger.kv_info(
                            f"Timeline saved to {timeline_output_path_csv}",
                            kv_pairs={"TimelinePathCSV": str(timeline_output_path_csv)},
                        )
                    else:
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
                    if isinstance(logger, KVLogger):
                        logger.kv_info(
                            f"Subtitle file saved to {subtitle_output_path_srt}",
                            kv_pairs={"SubtitlePathSRT": str(subtitle_output_path_srt)},
                        )
                    else:
                        logger.info(
                            f"Subtitle file saved to {subtitle_output_path_srt}"
                        )
                if subtitle_format in ["ass", "both"]:
                    subtitle_output_path_ass = output_path_base.with_suffix(".ass")
                    self.timeline.save_subtitles(subtitle_output_path_ass, format="ass")
                    if isinstance(logger, KVLogger):
                        logger.kv_info(
                            f"Subtitle file saved to {subtitle_output_path_ass}",
                            kv_pairs={"SubtitlePathASS": str(subtitle_output_path_ass)},
                        )
                    else:
                        logger.info(
                            f"Subtitle file saved to {subtitle_output_path_ass}"
                        )

            pipeline_end_time = time.time()
            self.stats["total_duration"] = pipeline_end_time - pipeline_start_time

            # Output final summary
            self._log_final_summary()

            if isinstance(logger, KVLogger):
                logger.kv_info(
                    "--- Video Generation Pipeline Completed ---",
                    kv_pairs={"Event": "PipelineCompleted"},
                )
            else:
                logger.info("--- Video Generation Pipeline Completed ---")

    def _log_final_summary(self):
        if isinstance(logger, KVLogger):
            summary_kv = {"Event": "PipelineSummary"}
            summary_kv["TotalDuration"] = f"{self.stats['total_duration']:.2f}s"
            summary_kv["ClipsProcessed"] = self.stats["clips_processed"]

            if self.stats["clip_durations"]:
                avg_duration = statistics.mean(self.stats["clip_durations"])
                p95_duration = statistics.quantiles(
                    self.stats["clip_durations"], n=100
                )[
                    94
                ]  # 95th percentile
                summary_kv["ClipAvgDuration"] = f"{avg_duration:.2f}s"
                summary_kv["ClipP95Duration"] = f"{p95_duration:.2f}s"

            for phase_name, data in self.stats["phases"].items():
                summary_kv[f"Phase{phase_name}Duration"] = f"{data['duration']:.2f}s"

            logger.kv_info("Pipeline Summary", kv_pairs=summary_kv)
        else:
            logger.info("--- Pipeline Summary ---")
            logger.info(f"Total Duration: {self.stats['total_duration']:.2f}s")
            logger.info(f"Clips Processed: {self.stats['clips_processed']}")
            if self.stats["clip_durations"]:
                avg_duration = statistics.mean(self.stats["clip_durations"])
                p95_duration = statistics.quantiles(
                    self.stats["clip_durations"], n=100
                )[94]
                logger.info(f"Clip Average Duration: {avg_duration:.2f}s")
                logger.info(f"Clip P95 Duration: {p95_duration:.2f}s")
            for phase_name, data in self.stats["phases"].items():
                logger.info(f"  {phase_name} Duration: {data['duration']:.2f}s")
            logger.info("------------------------")


async def run_generation(
    script_path: str,
    output_path: str,
    no_cache: bool = False,
    cache_refresh: bool = False,
    jobs: str = "0",
    timeline_format: Optional[str] = None,
    no_timeline: bool = False,
    subtitle_file_format: Optional[str] = None,
    no_subtitle_file: bool = False,
    hw_encoder: str = "auto",
    quality: str = "balanced",
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

    # Create and run the pipeline with default VideoParams and AudioParams
    pipeline = GenerationPipeline(
        config,
        no_cache,
        cache_refresh,
        jobs,
        video_params=VideoParams(),  # デフォルトのVideoParamsを渡す
        audio_params=AudioParams(),  # デフォルトのAudioParamsを渡す
        hw_encoder=hw_encoder,
        quality=quality,
    )
    await pipeline.run(output_path)
