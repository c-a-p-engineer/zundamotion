"""音声・映像生成フェーズを統括するパイプライン実装。"""

import asyncio
import shutil
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Optional

from tqdm import tqdm

from .cache import CacheManager
from .components.pipeline_phases import AudioPhase, BGMPhase, FinalizePhase, VideoPhase
from .exceptions import PipelineError
from .timeline import Timeline
from .utils.ffmpeg_params import AudioParams, VideoParams, resolve_media_params
from .utils.ffmpeg_probe import get_media_duration, validate_final_media
from .utils.export_presets import apply_export_preset
from .utils.logger import KVLogger, logger, time_log
from .utils import perf_stats
from .pipeline_reporting import PipelineReportingMixin


class GenerationPipeline(PipelineReportingMixin):
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
        self.config = apply_export_preset(config)
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
            cache_dir=Path(self.config.get("system", {}).get("cache_dir", ".cache/zundamotion")),
            no_cache=self.no_cache,
            cache_refresh=self.cache_refresh,
        )
        self.timeline = Timeline()
        resolved_video, resolved_audio = resolve_media_params(self.config)
        self.video_params = video_params if video_params is not None else resolved_video
        self.audio_params = audio_params if audio_params is not None else resolved_audio
        self.stats: Dict[str, Any] = {
            "phases": {},
            "total_duration": 0.0,
            "clips_processed": 0,
            "clip_durations": [],
        }

    async def _run_phase(self, phase_name: str, func, *args, **kwargs):
        """各フェーズを実行し処理時間を記録する。"""
        start_time = time.time()
        current_perf = perf_stats.current_perf_stats()
        run_id = current_perf.run_id if current_perf is not None else "-"
        logger.info("[Phase] run_id=%s name=%s status=start", run_id, phase_name)
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
        current_perf = perf_stats.current_perf_stats()
        if current_perf is not None:
            current_perf.set_phase_ms(phase_name, duration * 1000.0)
            run_id = current_perf.run_id
        logger.info(
            "[Phase] run_id=%s name=%s status=end duration_ms=%.1f",
            run_id,
            phase_name,
            duration * 1000.0,
        )

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
        perf = perf_stats.start_perf_stats()
        logger.info(
            "[Render] run_id=%s start output=%s",
            perf.run_id,
            output_path,
        )
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
                video_params=self.video_params,
                audio_params=self.audio_params,
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
                self.cache_manager.get_or_create_media_duration(
                    clip,
                    caller="pipeline_clip_duration",
                )
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
            await validate_final_media(output_path, self.audio_params)
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
                    video_duration = await get_media_duration(
                        str(final_video_path),
                        caller="timeline_ffmetadata_duration",
                    )
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
            perf.scan_intermediates(temp_dir)
            self.stats["perf_summary"] = perf.to_dict()

            # Output final summary
            self._log_final_summary()
            self._write_perf_summary_json(Path(output_path), perf)

            if isinstance(logger, KVLogger):
                logger.kv_info(
                    "--- Video Generation Pipeline Completed ---",
                    kv_pairs={"Event": "PipelineCompleted"},
                )
            else:
                logger.info("--- Video Generation Pipeline Completed ---")

# Imported after GenerationPipeline is defined to preserve the public import path.
from .pipeline_entry import run_generation

