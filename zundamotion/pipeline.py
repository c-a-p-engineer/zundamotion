"""音声・映像生成フェーズを統括するパイプライン実装。"""

import asyncio
import shutil
import os
import statistics
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from tqdm import tqdm

from .cache import CacheManager
from .components.pipeline_phases import AudioPhase, BGMPhase, FinalizePhase, VideoPhase
from .components.script import load_script_and_config
from .exceptions import PipelineError
from .timeline import Timeline
from .plugins.manager import initialize_plugins
from .utils.ffmpeg_params import AudioParams, VideoParams
from .utils.ffmpeg_probe import get_media_duration
from .utils.logger import KVLogger, logger, time_log


class GenerationPipeline:
    """スクリプトを元に音声・映像・仕上げの各フェーズを連携させる。"""

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
        final_copy_only: bool = False,
    ):
        self.config = config
        self.no_cache = no_cache
        self.cache_refresh = cache_refresh
        self.jobs = jobs
        self.hw_encoder = hw_encoder
        self.quality = quality
        self.final_copy_only = final_copy_only
        # 既定で NVENC の高速化フラグを有効化（必要に応じて NVENC_FAST=0 で無効化）
        try:
            import os as _os
            _os.environ.setdefault("NVENC_FAST", "1")
        except Exception:
            pass
        # Propagate quality-aware scaling policy into config for VideoPhase/Renderer
        try:
            vcfg = self.config.setdefault("video", {})
            # Map quality -> scale flags (CPU scaler) and fps filter policy
            q = (quality or "balanced").lower()
            if "scale_flags" not in vcfg:
                vcfg["scale_flags"] = (
                    "fast_bilinear" if q == "speed" else ("lanczos" if q == "quality" else "bicubic")
                )
            if "apply_fps_filter" not in vcfg:
                # In speed mode, rely on output -r CFR to minimize per-frame filter cost
                vcfg["apply_fps_filter"] = False if q == "speed" else True
            # Encourage scene base generation slightly earlier in speed mode
            if q == "speed":
                try:
                    cur = int(vcfg.get("scene_base_min_lines", 6))
                except Exception:
                    cur = 6
                vcfg["scene_base_min_lines"] = max(2, min(cur, 4))
        except Exception:
            pass
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
        """各フェーズを実行し処理時間を記録する。"""
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
        """動画生成パイプライン全体を実行する。

        Args:
            output_path: 最終出力する動画ファイルのパス。
        """
        pipeline_start_time = time.time()
        # Prefer RAM disk (/dev/shm) when available and large enough, controlled by USE_RAMDISK env (default: 1)
        use_ramdisk = True
        try:
            use_ramdisk = os.getenv("USE_RAMDISK", "1") == "1"
        except Exception:
            use_ramdisk = True
        temp_ctx = None
        if use_ramdisk and Path("/dev/shm").exists():
            try:
                import shutil as _sh

                usage = _sh.disk_usage("/dev/shm")
                # Require at least 256MB free
                if usage.free > 256 * 1024 * 1024:
                    temp_ctx = tempfile.TemporaryDirectory(dir="/dev/shm")
            except Exception:
                temp_ctx = None
        if temp_ctx is None:
            temp_ctx = tempfile.TemporaryDirectory()

        with temp_ctx as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            # Route ephemeral (no-cache) outputs to temp_dir for this run
            try:
                self.cache_manager.set_ephemeral_dir(temp_dir)
            except Exception:
                pass
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
                self.hw_encoder,
            )
            all_clips = await self._run_phase(
                "VideoPhase", video_phase.run, scenes, line_data_map, self.timeline
            )
            video_renderer = getattr(video_phase, "video_renderer", None)
            self.stats["filter_path_usage"] = getattr(
                video_renderer, "path_counters", {}
            )
            self.stats["subtitle_overlay"] = getattr(
                video_renderer, "subtitle_overlay_stats", {}
            )
            self.stats["subtitle_overlay_history"] = getattr(
                video_renderer, "subtitle_overlay_stats_history", []
            )
            generate_no_sub_video = bool(
                self.config.get("system", {}).get("generate_no_sub_video", False)
            )
            no_sub_clips = (
                self._derive_no_subtitle_clips(all_clips)
                if generate_no_sub_video
                else []
            )
            self.stats["clips_processed"] = len(all_clips)
            # all_clips が Path オブジェクトのリストであると仮定し、get_media_duration を使用して duration を取得
            # get_media_duration は非同期関数なので、asyncio.gather を使って並行して duration を取得
            clip_durations_tasks = [
                self.cache_manager.get_or_create_media_duration(clip)
                for clip in all_clips
            ]
            self.stats["clip_durations"] = await asyncio.gather(*clip_durations_tasks)
            # Phase 3: Finalize Video
            finalize_phase = FinalizePhase(
                self.config,
                temp_dir,
                self.cache_manager,
                self.video_params,
                self.audio_params,
                self.hw_encoder,
                self.quality,
                final_copy_only=self.final_copy_only,
            )
            final_video_path = await self._run_phase(
                "FinalizePhase",
                finalize_phase.run,
                scenes,
                self.timeline,
                line_data_map,
                all_clips,
                used_voicevox_info,
                "final_output",
            )
            no_sub_final_video_path = None
            if no_sub_clips:
                no_sub_final_video_path = await self._run_phase(
                    "FinalizePhase",
                    finalize_phase.run,
                    scenes,
                    self.timeline,
                    line_data_map,
                    no_sub_clips,
                    used_voicevox_info,
                    "final_output_no_sub",
                )
            # Phase 4: BGM Mixing (timeline driven)
            bgm_phase = BGMPhase(self.config, temp_dir, self.audio_params)
            final_video_path = await self._run_phase(
                "BGMPhase",
                bgm_phase.run,
                final_video_path,
                self.timeline,
            )
            if no_sub_final_video_path is not None:
                no_sub_final_video_path = await self._run_phase(
                    "BGMPhase",
                    bgm_phase.run,
                    no_sub_final_video_path,
                    self.timeline,
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
            if no_sub_final_video_path is not None:
                output_path_base = Path(output_path)
                no_sub_output_path = output_path_base.with_name(
                    f"{output_path_base.stem}_no_sub{output_path_base.suffix}"
                )
                shutil.copy(no_sub_final_video_path, no_sub_output_path)
                logger.info(f"No-sub video saved to {no_sub_output_path}")

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
                subtitle_offset = float(subtitle_file_config.get("offset_seconds", 0.0) or 0.0)
                output_path_base = Path(output_path)

                if subtitle_format in ["srt", "both"]:
                    subtitle_output_path_srt = output_path_base.with_suffix(".srt")
                    self.timeline.save_subtitles(
                        subtitle_output_path_srt,
                        format="srt",
                        offset_seconds=subtitle_offset,
                    )
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
                    self.timeline.save_subtitles(
                        subtitle_output_path_ass,
                        format="ass",
                        offset_seconds=subtitle_offset,
                    )
                    if isinstance(logger, KVLogger):
                        logger.kv_info(
                            f"Subtitle file saved to {subtitle_output_path_ass}",
                            kv_pairs={"SubtitlePathASS": str(subtitle_output_path_ass)},
                        )
                    else:
                        logger.info(
                            f"Subtitle file saved to {subtitle_output_path_ass}"
                        )

            topics = self.timeline.get_topics()
            if topics:
                formatted_topics = [
                    f"{self.timeline.format_chapter_timestamp(t['time'])} {t['title']}"
                    for t in topics
                ]
                logger.info("Topics: %s", formatted_topics)
                output_path_base = Path(output_path)
                chapters_output_path = output_path_base.with_suffix(".chapters.txt")
                self.timeline.save_chapters(chapters_output_path)
                if isinstance(logger, KVLogger):
                    logger.kv_info(
                        f"Chapters saved to {chapters_output_path}",
                        kv_pairs={"ChaptersPath": str(chapters_output_path)},
                    )
                else:
                    logger.info(f"Chapters saved to {chapters_output_path}")

                try:
                    video_duration = await get_media_duration(str(final_video_path))
                    ffmetadata_output_path = output_path_base.with_suffix(".ffmetadata")
                    with open(ffmetadata_output_path, "w", encoding="utf-8") as f:
                        f.write(";FFMETADATA1\n")
                        for idx, topic in enumerate(topics):
                            start_ms = int(float(topic["time"]) * 1000)
                            if idx + 1 < len(topics):
                                end_ms = int(float(topics[idx + 1]["time"]) * 1000)
                            else:
                                end_ms = int(float(video_duration) * 1000)
                            if end_ms <= start_ms:
                                end_ms = start_ms + 1
                            f.write("[CHAPTER]\n")
                            f.write("TIMEBASE=1/1000\n")
                            f.write(f"START={start_ms}\n")
                            f.write(f"END={end_ms}\n")
                            f.write(f"title={topic['title']}\n")
                    logger.info(f"FFmetadata saved to {ffmetadata_output_path}")
                except Exception as e:
                    logger.debug("Failed to save ffmetadata: %s", e)

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
        """Log aggregated statistics after the pipeline completes."""
        clip_durations = self.stats["clip_durations"]
        avg_duration = None
        p95_duration = None
        if clip_durations:
            avg_duration = statistics.mean(clip_durations)
            if len(clip_durations) >= 2:
                p95_duration = statistics.quantiles(clip_durations, n=100)[94]
            else:
                p95_duration = clip_durations[0]

        if isinstance(logger, KVLogger):
            summary_kv = {"Event": "PipelineSummary"}
            summary_kv["TotalDuration"] = f"{self.stats['total_duration']:.2f}s"
            summary_kv["ClipsProcessed"] = self.stats["clips_processed"]

            if avg_duration is not None and p95_duration is not None:
                summary_kv["ClipAvgDuration"] = f"{avg_duration:.2f}s"
                summary_kv["ClipP95Duration"] = f"{p95_duration:.2f}s"

            for phase_name, data in self.stats["phases"].items():
                summary_kv[f"Phase{phase_name}Duration"] = f"{data['duration']:.2f}s"

            filter_stats = self.stats.get("filter_path_usage") or {}
            if isinstance(filter_stats, dict):
                for key in ("cuda_overlay", "opencl_overlay", "gpu_scale_only", "cpu"):
                    summary_kv[f"FilterPath{key}"] = filter_stats.get(key, 0)

            subtitle_stats = self.stats.get("subtitle_overlay") or {}
            subtitle_history = self.stats.get("subtitle_overlay_history") or []
            if isinstance(subtitle_history, list) and subtitle_history:
                subtitle_stats = {
                    "mode": ",".join(
                        sorted({str(item.get("mode", "none")) for item in subtitle_history})
                    ),
                    "subtitles": sum(int(item.get("subtitles", 0) or 0) for item in subtitle_history),
                    "chunks": sum(int(item.get("chunks", 0) or 0) for item in subtitle_history),
                    "png_chunk_size": ",".join(
                        sorted({
                            str(item.get("png_chunk_size"))
                            for item in subtitle_history
                            if item.get("png_chunk_size") is not None
                        })
                    ) or None,
                    "layer_video_attempted": any(
                        bool(item.get("layer_video_attempted")) for item in subtitle_history
                    ),
                    "layer_video_used": any(
                        bool(item.get("layer_video_used")) for item in subtitle_history
                    ),
                }
            if isinstance(subtitle_stats, dict):
                summary_kv["SubtitleMode"] = subtitle_stats.get("mode", "none")
                summary_kv["SubtitleCount"] = subtitle_stats.get("subtitles", 0)
                summary_kv["SubtitleChunks"] = subtitle_stats.get("chunks", 0)
                summary_kv["SubtitlePngChunkSize"] = subtitle_stats.get("png_chunk_size")
                summary_kv["SubtitleLayerVideoAttempted"] = bool(
                    subtitle_stats.get("layer_video_attempted")
                )
                summary_kv["SubtitleLayerVideoUsed"] = bool(
                    subtitle_stats.get("layer_video_used")
                )

            logger.kv_info("Pipeline Summary", kv_pairs=summary_kv)
        else:
            logger.info("--- Pipeline Summary ---")
            logger.info(f"Total Duration: {self.stats['total_duration']:.2f}s")
            logger.info(f"Clips Processed: {self.stats['clips_processed']}")
            if avg_duration is not None and p95_duration is not None:
                logger.info(f"Clip Average Duration: {avg_duration:.2f}s")
                logger.info(f"Clip P95 Duration: {p95_duration:.2f}s")
            for phase_name, data in self.stats["phases"].items():
                logger.info(f"  {phase_name} Duration: {data['duration']:.2f}s")
            filter_stats = self.stats.get("filter_path_usage") or {}
            if isinstance(filter_stats, dict):
                logger.info(
                    "Filter Path Usage: cuda_overlay=%s, opencl_overlay=%s, gpu_scale_only=%s, cpu=%s",
                    filter_stats.get("cuda_overlay", 0),
                    filter_stats.get("opencl_overlay", 0),
                    filter_stats.get("gpu_scale_only", 0),
                    filter_stats.get("cpu", 0),
                )
            subtitle_stats = self.stats.get("subtitle_overlay") or {}
            subtitle_history = self.stats.get("subtitle_overlay_history") or []
            if isinstance(subtitle_history, list) and subtitle_history:
                subtitle_stats = {
                    "mode": ",".join(
                        sorted({str(item.get("mode", "none")) for item in subtitle_history})
                    ),
                    "subtitles": sum(int(item.get("subtitles", 0) or 0) for item in subtitle_history),
                    "chunks": sum(int(item.get("chunks", 0) or 0) for item in subtitle_history),
                    "png_chunk_size": ",".join(
                        sorted({
                            str(item.get("png_chunk_size"))
                            for item in subtitle_history
                            if item.get("png_chunk_size") is not None
                        })
                    ) or None,
                    "layer_video_attempted": any(
                        bool(item.get("layer_video_attempted")) for item in subtitle_history
                    ),
                    "layer_video_used": any(
                        bool(item.get("layer_video_used")) for item in subtitle_history
                    ),
                }
            if isinstance(subtitle_stats, dict):
                logger.info(
                    "Subtitle Overlay: mode=%s, subtitles=%s, chunks=%s, png_chunk_size=%s, layer_attempted=%s, layer_used=%s",
                    subtitle_stats.get("mode", "none"),
                    subtitle_stats.get("subtitles", 0),
                    subtitle_stats.get("chunks", 0),
                    subtitle_stats.get("png_chunk_size"),
                    bool(subtitle_stats.get("layer_video_attempted")),
                    bool(subtitle_stats.get("layer_video_used")),
                )
            logger.info("------------------------")

    @staticmethod
    def _derive_no_subtitle_clips(all_clips: list[Path]) -> list[Path]:
        derived: list[Path] = []
        found_distinct_no_sub = False
        for clip in all_clips:
            candidate = clip
            stem = clip.stem
            if stem.endswith("_sub"):
                maybe = clip.with_name(f"{stem[:-4]}{clip.suffix}")
                if maybe.exists():
                    candidate = maybe
                    found_distinct_no_sub = True
            derived.append(candidate)
        return derived if found_distinct_no_sub else []


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
    final_copy_only: bool = False,
    disable_plugins: bool = False,
    plugin_paths: Optional[List[str]] = None,
    plugin_allow: Optional[List[str]] = None,
    plugin_deny: Optional[List[str]] = None,
    dump_resolved_path: Optional[str] = None,
    debug_include: bool = False,
    disable_voice: bool = False,
):
    """動画生成を高レベルに実行するユーティリティ関数。"""
    # Get the path to the default config file
    default_config_path = Path(__file__).parent / "templates" / "config.yaml"

    # Load script and config
    config = load_script_and_config(
        script_path,
        str(default_config_path),
        dump_resolved_path=dump_resolved_path,
        debug_include=debug_include,
    )
    if disable_voice:
        config.setdefault("voice", {})["enabled"] = False

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

    # Initialize plugin system before pipeline creation
    if not disable_plugins:
        try:
            initialize_plugins(
                config=config,
                cli_paths=plugin_paths,
                allow_ids=plugin_allow,
                deny_ids=plugin_deny,
            )
        except Exception:
            logger.warning("[PluginLoader] Plugin initialization failed; continuing with built-ins")

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
        final_copy_only=final_copy_only,
    )
    await pipeline.run(output_path)
