#!/usr/bin/env python3
"""Compare bounded subtitle segment worker counts on a synthetic long scene."""

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
from zundamotion.utils import perf_stats
from zundamotion.utils.ffmpeg_hw import set_hw_filter_mode
from zundamotion.utils.ffmpeg_params import resolve_media_params


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = 1


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
    subprocess.run(command, cwd=ROOT, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


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


async def _run_trial(base_video: Path, output_dir: Path, workers: int) -> dict[str, Any]:
    trial_dir = output_dir / f"workers-{workers}"
    if trial_dir.exists():
        shutil.rmtree(trial_dir)
    trial_dir.mkdir(parents=True)
    temp_dir = trial_dir / "temp"
    cache_dir = trial_dir / "cache"
    temp_dir.mkdir()
    cache = CacheManager(cache_dir, no_cache=True)
    cache.set_ephemeral_dir(temp_dir)
    config = _config()
    video_params, audio_params = resolve_media_params(config)
    renderer = VideoRenderer(
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
    output_path = trial_dir / "subtitle-output.mp4"
    os.environ["ZUNDAMOTION_SUBTITLE_SEGMENT_WORKERS"] = str(workers)
    stats = perf_stats.start_perf_stats()
    started = time.perf_counter()
    await renderer.apply_subtitle_overlays(
        base_video,
        _subtitles(),
        scene_id=f"subtitle-benchmark-w{workers}",
    )
    generated = temp_dir / f"{base_video.stem}_sub.mp4"
    if not generated.is_file():
        raise FileNotFoundError(generated)
    shutil.copy2(generated, output_path)
    elapsed = time.perf_counter() - started
    summary = stats.to_dict()
    return {
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


async def _main_async(output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    base_video = output_dir / "base.mp4"
    duration = float(len(_subtitles()))
    _create_base_video(base_video, duration)
    set_hw_filter_mode("cpu")
    os.environ["DISABLE_HWENC"] = "1"
    os.environ["HW_FILTER_MODE"] = "cpu"
    trials = [
        await _run_trial(base_video, output_dir, workers)
        for workers in (1, 2)
    ]
    one, two = trials
    comparison = {
        "elapsed_ratio_w2_vs_w1": round(two["elapsed_seconds"] / one["elapsed_seconds"], 6),
        "subtitle_burn_ratio_w2_vs_w1": (
            round(two["subtitle_burn_ms"] / one["subtitle_burn_ms"], 6)
            if one["subtitle_burn_ms"] > 0
            else None
        ),
        "ffmpeg_calls_equal": one["ffmpeg_calls"] == two["ffmpeg_calls"],
        "worker2_faster": two["elapsed_seconds"] < one["elapsed_seconds"],
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "duration_seconds": duration,
        "subtitle_count": len(_subtitles()),
        "chunk_size": 8,
        "trials": trials,
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
