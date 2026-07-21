"""Pipeline summary logging and diagnostic artifact helpers."""

from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any

from .utils import perf_stats
from .utils.logger import KVLogger, logger


class PipelineReportingMixin:
    """Keep reporting/output helpers out of phase orchestration."""

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
        perf_summary = self.stats.get("perf_summary") or {}
        if isinstance(perf_summary, dict):
            logger.info("[PerfSummary] run_id=%s", perf_summary.get("run_id", "-"))
            logger.info(
                "[PerfSummary] ffmpeg_calls=%s ffprobe_calls=%s intermediate_files=%s intermediate_size_mb=%.1f",
                perf_summary.get("ffmpeg_calls", 0),
                perf_summary.get("ffprobe_calls", 0),
                perf_summary.get("intermediate_files", 0),
                float(perf_summary.get("intermediate_size_mb", 0.0) or 0.0),
            )
            logger.info(
                "[PerfSummary] ffprobe_duration_calls=%s ffprobe_stream_calls=%s ffprobe_other_calls=%s",
                perf_summary.get("ffprobe_duration_calls", 0),
                perf_summary.get("ffprobe_stream_calls", 0),
                perf_summary.get("ffprobe_other_calls", 0),
            )
            logger.info(
                "[PerfSummary] line_clips=%s subtitle_chunks=%s subtitle_png=%s",
                perf_summary.get("line_clips", 0),
                perf_summary.get("subtitle_chunks", 0),
                perf_summary.get("subtitle_png", 0),
            )
            logger.info(
                "[PerfSummary] cache_hit=%s cache_miss=%s cache_write=%s",
                perf_summary.get("cache_hit", 0),
                perf_summary.get("cache_miss", 0),
                perf_summary.get("cache_write", 0),
            )
            logger.info(
                "[PerfSummary] video_line_clip_ms=%.1f subtitle_burn_ms=%.1f face_precache_ms=%.1f scene_concat_ms=%.1f",
                float(perf_summary.get("video_line_clip_ms", 0.0) or 0.0),
                float(perf_summary.get("subtitle_burn_ms", 0.0) or 0.0),
                float(perf_summary.get("face_precache_ms", 0.0) or 0.0),
                float(perf_summary.get("scene_concat_ms", 0.0) or 0.0),
            )
            line_clip_summary = perf_summary.get("line_clip") or {}
            logger.info(
                "[PerfSummary] line_clip_metrics=%s line_clips_skipped_by_scene_cache=%s",
                line_clip_summary.get("status", "not_executed"),
                line_clip_summary.get("line_clips_skipped_by_scene_cache", 0),
            )
            logger.info(
                "[PerfSummary] line_clip_count=%s cache_hit=%s cache_miss=%s total_ms=%.1f render_ms=%.1f average_ms=%.1f p50_ms=%.1f p95_ms=%.1f max_ms=%.1f",
                line_clip_summary.get("line_clip_count", 0),
                line_clip_summary.get("line_clip_cache_hit_count", 0),
                line_clip_summary.get("line_clip_cache_miss_count", 0),
                float(line_clip_summary.get("line_clip_total_ms", 0.0) or 0.0),
                float(line_clip_summary.get("line_clip_render_ms", 0.0) or 0.0),
                float(line_clip_summary.get("line_clip_average_ms", 0.0) or 0.0),
                float(line_clip_summary.get("line_clip_p50_ms", 0.0) or 0.0),
                float(line_clip_summary.get("line_clip_p95_ms", 0.0) or 0.0),
                float(line_clip_summary.get("line_clip_max_ms", 0.0) or 0.0),
            )
            for item in (line_clip_summary.get("slowest") or [])[:10]:
                features = [
                    name
                    for name, enabled in (
                        ("subtitle", item.get("has_subtitle")),
                        ("face", item.get("has_face_overlay")),
                        ("move", item.get("has_move")),
                        ("effect", item.get("has_effect")),
                    )
                    if enabled
                ]
                logger.info(
                    "[PerfSummary] line_clip_slowest scene=%s line=%s time_ms=%.1f cache=%s features=%s",
                    item.get("scene_id", "-"),
                    item.get("line_index", "-"),
                    float(item.get("duration_ms", 0.0) or 0.0),
                    item.get("cache_status", "-"),
                    ",".join(features) or "none",
                )
            av_warnings = perf_summary.get("av_warnings") or {}
            logger.info(
                "[PerfSummary] av_warnings_total=%s",
                av_warnings.get("total", 0),
            )
            phase_ms = perf_summary.get("phase_ms") or {}
            for name, elapsed_ms in sorted(
                phase_ms.items(),
                key=lambda item: float(item[1] or 0.0),
                reverse=True,
            )[:4]:
                logger.info(
                    "[PerfSummary] phase_top name=%s elapsed_ms=%.1f",
                    name,
                    float(elapsed_ms or 0.0),
                )
            timing_items = [
                ("subtitle_burn", float(perf_summary.get("subtitle_burn_ms", 0.0) or 0.0)),
                ("video_line_clip", float(perf_summary.get("video_line_clip_ms", 0.0) or 0.0)),
                ("face_precache", float(perf_summary.get("face_precache_ms", 0.0) or 0.0)),
                ("scene_concat", float(perf_summary.get("scene_concat_ms", 0.0) or 0.0)),
            ]
            for name, elapsed_ms in sorted(
                timing_items,
                key=lambda item: item[1],
                reverse=True,
            ):
                if elapsed_ms <= 0.0:
                    continue
                logger.info(
                    "[PerfSummary] timing_top name=%s elapsed_ms=%.1f",
                    name,
                    elapsed_ms,
                )
            scene_cache = perf_summary.get("scene_cache") or {}
            miss_reasons = scene_cache.get("miss_reasons") or {}
            if miss_reasons:
                logger.info(
                    "[PerfSummary] scene_cache_miss_reasons=%s",
                    json.dumps(miss_reasons, ensure_ascii=False, sort_keys=True),
                )
            subtitle_burn = perf_summary.get("subtitle_burn") or {}
            for item in (subtitle_burn.get("top_chunks") or [])[:5]:
                logger.info(
                    "[PerfSummary] subtitle_burn_top scene_id=%s chunk=%s subtitles=%s burn_ms=%.1f",
                    item.get("scene_id", "-"),
                    item.get("chunk_index", 0),
                    item.get("subtitle_count", 0),
                    float(item.get("burn_duration_ms", 0.0) or 0.0),
                )
            ffprobe_summary = perf_summary.get("ffprobe") or {}
            for item in (ffprobe_summary.get("top_callers") or [])[:5]:
                logger.info(
                    "[PerfSummary] ffprobe_top_caller caller=%s calls=%s elapsed_ms=%.1f",
                    item.get("caller", "-"),
                    item.get("calls", 0),
                    float(item.get("elapsed_ms", 0.0) or 0.0),
                )
            for item in (ffprobe_summary.get("top_paths") or [])[:5]:
                logger.info(
                    "[PerfSummary] ffprobe_top_path calls=%s kind=%s path=%s",
                    item.get("calls", 0),
                    item.get("kind", "-"),
                    item.get("path", "-"),
                )

    def _write_perf_summary_json(self, output_path: Path, perf: perf_stats.PerfStats) -> None:
        configured = (
            (self.config.get("system", {}) or {})
            .get("performance", {})
            if isinstance((self.config.get("system", {}) or {}).get("performance", {}), dict)
            else {}
        )
        raw_path = configured.get("summary_json", "output/perf/perf_summary.json")
        summary_path = Path(raw_path)
        if not summary_path.is_absolute():
            summary_path = Path.cwd() / summary_path
        try:
            perf.write_json(summary_path)
            logger.info("[PerfSummary] json=%s", summary_path)
            history_path = summary_path.with_name(
                f"{summary_path.stem}.{perf.run_id}{summary_path.suffix}"
            )
            perf.write_json(history_path)
            logger.info("[PerfSummary] history_json=%s", history_path)
        except Exception as err:
            logger.warning("[PerfSummary] failed to write json summary: %s", err)

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


