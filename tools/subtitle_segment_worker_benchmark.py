#!/usr/bin/env python3
"""Compare legacy A/V subtitle chunks with bounded video-only execution."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from zundamotion.cache import CacheManager
from zundamotion.components.video import VideoRenderer
from zundamotion.components.video.subtitle_segment_plan import build_subtitle_segment_plan
from zundamotion.utils import perf_stats
from zundamotion.utils.ffmpeg_hw import set_hw_filter_mode
from zundamotion.utils.ffmpeg_ops import concat_videos_safe
from zundamotion.utils.ffmpeg_params import resolve_media_params


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = 2


def _config() -> dict[str, Any]:
    return {
        "system": {"cache_dir": ".cache/zundamotion"},
        "video": {
            "width": 320,
            "height": 180,
            "fps": 15,
            "audio_codec": "aac",
            "audio_sample_rate": 48000,
            "audio_channels": 2,
            "audio_bitrate_kbps": 128,
            "preset": "ultrafast",
            "crf": 28,
        },
        "subtitle": {
            "render_mode": "png",
            "font_path": "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf",
            "font_color": "white",
            "font_size": 24,
            "stroke_color": "black",
            "stroke_width": 1,
            "max_chars_per_line": 28,
            "wrap_mode": "chars",
            "max_pixel_width": 300,
            "x": "(w-text_w)/2",
            "y": "h-30-text_h/2",
            "png_compress_level": 1,
            "png_optimize": False,
            "png_chunk_size": 8,
            "copy_gap_threshold": 0.20,
            "background": {
                "color": "#000000",
                "opacity": 0.65,
                "radius": 8,
                "padding": {"x": 12, "y": 8},
                "border_width": 0,
            },
        },
    }


def _subtitles(count: int = 48) -> list[dict[str, Any]]:
    return [
        {
            "text": f"subtitle segment benchmark {index + 1:02d}",
            "start": float(index),
            "duration": 1.0,
            "line_config": {},
        }
        for index in range(count)
    ]


def _create_base_video(path: Path, duration: float) -> None:
    command = [
        "ffmpeg",
        "-y",
        "-nostdin",
        "-f",
        "lavfi",
        "-i",
        f"color=c=0x202020:s=320x180:r=15:d={duration:.3f}",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=440:sample_rate=48000:duration={duration:.3f}",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "28",
        "-pix_fmt",
        "yuv420p",
        "-r",
        "15",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-shortest",
        str(path),
    ]
    subprocess.run(
        command,
        cwd=ROOT,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _probe_av(path: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,start_time,duration",
            "-of",
            "json",
            str(path),
        ],
        cwd=ROOT,
        check=True,
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
    )
    streams = json.loads(completed.stdout).get("streams") or []
    by_type = {str(item.get("codec_type")): item for item in streams}

    def value(kind: str, key: str) -> float | None:
        raw = (by_type.get(kind) or {}).get(key)
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    video_start = value("video", "start_time")
    audio_start = value("audio", "start_time")
    video_duration = value("video", "duration")
    audio_duration = value("audio", "duration")
    return {
        "video_start": video_start,
        "audio_start": audio_start,
        "video_duration": video_duration,
        "audio_duration": audio_duration,
        "start_delta": (
            abs(video_start - audio_start)
            if video_start is not None and audio_start is not None
            else None
        ),
        "duration_delta": (
            abs(video_duration - audio_duration)
            if video_duration is not None and audio_duration is not None
            else None
        ),
    }


def _renderer(trial_dir: Path) -> VideoRenderer:
    temp_dir = trial_dir / "temp"
    cache_dir = trial_dir / "cache"
    temp_dir.mkdir()
    cache = CacheManager(cache_dir, no_cache=True)
    cache.set_ephemeral_dir(temp_dir)
    config = _config()
    video_params, audio_params = resolve_media_params(config)
    return VideoRenderer(
        config,
        temp_dir,
        cache,
        jobs="0",
        hw_kind=None,
        video_params=video_params,
        audio_params=audio_params,
        has_cuda_filters=False,
        clip_workers=1,
    )


def _trial_summary(
    *,
    mode: str,
    output_path: Path,
    elapsed: float,
    stats: Any,
    workers: int | None,
) -> dict[str, Any]:
    summary = stats.to_dict()
    return {
        "mode": mode,
        "workers": workers,
        "elapsed_seconds": round(elapsed, 3),
        "subtitle_burn_ms": float(summary.get("subtitle_burn_ms", 0.0) or 0.0),
        "ffmpeg_calls": int(summary.get("ffmpeg_calls", 0) or 0),
        "subtitle_chunks": int(summary.get("subtitle_chunks", 0) or 0),
        "av_warnings_total": int(summary.get("av_warnings_total", 0) or 0),
        "output_size": output_path.stat().st_size,
        "av": _probe_av(output_path),
        "output": str(output_path),
    }


async def _run_legacy_trial(base_video: Path, output_dir: Path) -> dict[str, Any]:
    trial_dir = output_dir / "legacy-av-segments"
    if trial_dir.exists():
        shutil.rmtree(trial_dir)
    trial_dir.mkdir(parents=True)
    renderer = _renderer(trial_dir)
    subtitles = _subtitles()
    plan = build_subtitle_segment_plan(
        subtitles,
        base_duration=float(len(subtitles)),
        gap_threshold=0.20,
        max_subtitles=8,
        min_exact_segment_duration=renderer._min_exact_segment_duration(),
    )
    stats = perf_stats.start_perf_stats()
    perf_stats.incr("subtitle_chunks", len(plan.ranges))
    started = time.perf_counter()
    segment_paths: list[Path] = []
    for index, item in enumerate(plan.ranges):
        segment_base = renderer.temp_dir / f"legacy_base_{index:03d}.mp4"
        cut = await renderer._cut_video_segment_exact(
            base_video,
            segment_base,
            float(item.start),
            float(item.duration),
        )
        if cut is None:
            raise RuntimeError("legacy benchmark failed to cut a planned range")
        adjusted: list[dict[str, Any]] = []
        for subtitle in item.subtitles:
            copied = dict(subtitle)
            copied["start"] = max(0.0, float(subtitle["start"]) - float(item.start))
            adjusted.append(copied)
        burn_path = renderer.temp_dir / f"legacy_burn_{index:03d}.mp4"
        burn_started = time.perf_counter()
        burned = await renderer._apply_subtitle_overlays_full(
            cut,
            adjusted,
            burn_path,
            scene_id="subtitle-benchmark-legacy",
            chunk_index=index,
        )
        perf_stats.add_ms(
            "subtitle_burn_ms",
            (time.perf_counter() - burn_started) * 1000.0,
        )
        segment_paths.append(burned)

    output_path = trial_dir / "subtitle-output.mp4"
    await concat_videos_safe(
        [str(path.resolve()) for path in segment_paths],
        str(output_path),
        renderer.audio_params,
        renderer.ffmpeg_path,
        context={
            "phase": "VideoPhase",
            "operation": "subtitle_scene_concat_legacy_benchmark",
            "scene_id": "subtitle-benchmark-legacy",
            "output_path": str(output_path),
        },
    )
    return _trial_summary(
        mode="legacy_av_segments",
        output_path=output_path,
        elapsed=time.perf_counter() - started,
        stats=stats,
        workers=None,
    )


async def _run_video_only_trial(
    base_video: Path,
    output_dir: Path,
    workers: int,
) -> dict[str, Any]:
    trial_dir = output_dir / f"video-only-workers-{workers}"
    if trial_dir.exists():
        shutil.rmtree(trial_dir)
    trial_dir.mkdir(parents=True)
    renderer = _renderer(trial_dir)
    output_path = trial_dir / "subtitle-output.mp4"
    os.environ["ZUNDAMOTION_SUBTITLE_SEGMENT_WORKERS"] = str(workers)
    stats = perf_stats.start_perf_stats()
    started = time.perf_counter()
    generated = await renderer.apply_subtitle_overlays(
        base_video,
        _subtitles(),
        scene_id=f"subtitle-benchmark-w{workers}",
    )
    if not Path(generated).is_file():
        raise FileNotFoundError(generated)
    shutil.copy2(generated, output_path)
    return _trial_summary(
        mode="video_only",
        output_path=output_path,
        elapsed=time.perf_counter() - started,
        stats=stats,
        workers=workers,
    )


async def _main_async(output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    base_video = output_dir / "base.mp4"
    duration = float(len(_subtitles()))
    _create_base_video(base_video, duration)
    set_hw_filter_mode("cpu")
    os.environ["DISABLE_HWENC"] = "1"
    os.environ["HW_FILTER_MODE"] = "cpu"

    legacy = await _run_legacy_trial(base_video, output_dir)
    one = await _run_video_only_trial(base_video, output_dir, 1)
    two = await _run_video_only_trial(base_video, output_dir, 2)
    comparison = {
        "w1_vs_legacy_elapsed_ratio": round(
            one["elapsed_seconds"] / legacy["elapsed_seconds"], 6
        ),
        "w2_vs_legacy_elapsed_ratio": round(
            two["elapsed_seconds"] / legacy["elapsed_seconds"], 6
        ),
        "w2_vs_w1_elapsed_ratio": round(
            two["elapsed_seconds"] / one["elapsed_seconds"], 6
        ),
        "legacy_ffmpeg_calls": legacy["ffmpeg_calls"],
        "worker1_ffmpeg_calls": one["ffmpeg_calls"],
        "worker2_ffmpeg_calls": two["ffmpeg_calls"],
        "worker2_faster_than_worker1": two["elapsed_seconds"] < one["elapsed_seconds"],
        "worker2_faster_than_legacy": two["elapsed_seconds"] < legacy["elapsed_seconds"],
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "duration_seconds": duration,
        "subtitle_count": len(_subtitles()),
        "chunk_size": 8,
        "base_av": _probe_av(base_video),
        "trials": [legacy, one, two],
        "comparison": comparison,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "output" / "benchmarks" / "subtitle-segment-workers",
    )
    args = parser.parse_args()
    result = asyncio.run(_main_async(args.output_dir.resolve()))
    output_path = args.output_dir.resolve() / "subtitle-segment-worker-benchmark.json"
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
