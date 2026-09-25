#!/usr/bin/env python3
"""Benchmark AudioPhase with VOICEVOX worker counts 1 and 2.

The benchmark isolates speech generation from video rendering. It uses unique,
fixed Japanese lines, disables provider retries, alternates worker order across
rounds, and compares decoded PCM plus timeline ordering between trials.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

from zundamotion.cache import CacheManager
from zundamotion.components.pipeline_phases.audio_phase import AudioPhase
from zundamotion.timeline import Timeline
from zundamotion.utils.ffmpeg_params import AudioParams


ROOT_DIR = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = 1
DEFAULT_LINES = 24


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _benchmark_lines(count: int) -> list[str]:
    seeds = [
        "ずんだもーしょんの音声生成ベンチマークです。",
        "低スペック環境でも再現可能な動画生成を目指します。",
        "同じ入力から同じ順序で音声が生成されることを確認します。",
        "一つの処理を速くしても出力が変われば採用できません。",
        "キャッシュを使わず音声合成そのものの時間を比較します。",
        "ワーカー数を変えてもタイムラインの順序は維持します。",
        "短い文章と少し長い文章を混ぜて実際の台本に近づけます。",
        "計測結果はJSONへ保存し、後から条件を確認できるようにします。",
    ]
    return [
        f"{seeds[index % len(seeds)]} 計測番号は{index + 1}です。"
        for index in range(max(1, count))
    ]


def _scenes(count: int, speaker: int) -> list[dict[str, Any]]:
    return [
        {
            "id": "audio-worker-benchmark",
            "lines": [
                {
                    "text": text,
                    "speaker_id": speaker,
                    "mouth_sync": False,
                }
                for text in _benchmark_lines(count)
            ],
        }
    ]


def _pcm_sha256(path: Path, audio_params: AudioParams) -> str:
    command = [
        "ffmpeg",
        "-v",
        "error",
        "-i",
        str(path),
        "-f",
        "s16le",
        "-acodec",
        "pcm_s16le",
        "-ar",
        str(audio_params.sample_rate),
        "-ac",
        str(audio_params.channels),
        "-",
    ]
    completed = subprocess.run(
        command,
        cwd=ROOT_DIR,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return hashlib.sha256(completed.stdout).hexdigest()


def _timeline_fingerprint(timeline: Timeline) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for event in timeline.events:
        result.append(
            {
                "type": event.get("type"),
                "scene_id": event.get("scene_id"),
                "description": event.get("description"),
                "text": event.get("text"),
                "start_time": round(float(event.get("start_time", 0.0)), 6),
                "duration": round(float(event.get("duration", 0.0)), 6),
            }
        )
    return result


def _trial_fingerprint(
    line_data_map: dict[str, dict[str, Any]],
    timeline: Timeline,
    audio_params: AudioParams,
) -> dict[str, Any]:
    lines = []
    for line_id, data in line_data_map.items():
        raw_path = data.get("audio_path")
        if not raw_path:
            raise RuntimeError(f"Missing audio_path for {line_id}")
        path = Path(raw_path)
        lines.append(
            {
                "line_id": line_id,
                "pcm_sha256": _pcm_sha256(path, audio_params),
                "duration": round(float(data.get("audio_full_duration", data["duration"])), 6),
                "text": data.get("text"),
            }
        )
    return {
        "line_order": [item["line_id"] for item in lines],
        "lines": lines,
        "timeline": _timeline_fingerprint(timeline),
    }


def _voicevox_version(url: str, timeout: float) -> str:
    endpoint = f"{url.rstrip('/')}/version"
    with urllib.request.urlopen(endpoint, timeout=timeout) as response:
        payload = response.read().decode("utf-8", errors="replace").strip()
    try:
        parsed = json.loads(payload)
        return str(parsed)
    except json.JSONDecodeError:
        return payload.strip('"')


def _worker_schedule(rounds: int) -> list[int]:
    schedule: list[int] = []
    for index in range(max(1, rounds)):
        schedule.extend((1, 2) if index % 2 == 0 else (2, 1))
    return schedule


async def _run_trial(
    *,
    trial_index: int,
    workers: int,
    output_dir: Path,
    voicevox_url: str,
    speaker: int,
    line_count: int,
    timeout: float,
) -> dict[str, Any]:
    trial_dir = output_dir / f"trial-{trial_index:02d}-workers-{workers}"
    if trial_dir.exists():
        shutil.rmtree(trial_dir)
    temp_dir = trial_dir / "temp"
    cache_dir = trial_dir / "cache"
    temp_dir.mkdir(parents=True)
    cache = CacheManager(cache_dir, no_cache=True)
    cache.set_ephemeral_dir(temp_dir)
    audio_params = AudioParams(
        sample_rate=48000,
        channels=2,
        codec="aac",
        bitrate_kbps=128,
    )
    config: dict[str, Any] = {
        "voice": {
            "provider": "voicevox",
            "url": voicevox_url,
            "speaker": speaker,
            "speed": 1.0,
            "pitch": 0.0,
            "parallel_workers": workers,
            "request_timeout": timeout,
            # Disable retries so retry/backoff noise cannot bias worker comparison.
            "retry_attempts": 1,
            "speaker_retry_attempts": 1,
            "retry_wait_min": 0.0,
            "retry_wait_max": 0.0,
        },
        "video": {
            "fps": 30,
            "audio_sample_rate": audio_params.sample_rate,
            "audio_channels": audio_params.channels,
        },
    }

    previous_workers = os.environ.get("ZUNDAMOTION_AUDIO_WORKERS")
    previous_url = os.environ.get("VOICEVOX_URL")
    os.environ["ZUNDAMOTION_AUDIO_WORKERS"] = str(workers)
    os.environ["VOICEVOX_URL"] = voicevox_url
    timeline = Timeline()
    started = time.perf_counter()
    try:
        phase = AudioPhase(config, temp_dir, cache, audio_params)
        line_data_map, usage = await phase.run(_scenes(line_count, speaker), timeline)
        elapsed = time.perf_counter() - started
        fingerprint = _trial_fingerprint(line_data_map, timeline, audio_params)
        return {
            "trial_index": trial_index,
            "workers": workers,
            "success": True,
            "elapsed_seconds": round(elapsed, 3),
            "resolved_workers": phase.audio_worker_policy.resolved,
            "worker_policy_source": phase.audio_worker_policy.source,
            "line_count": len(line_data_map),
            "voice_usage_count": len(usage),
            "provider_failures": 0,
            "retry_attempts_configured": 1,
            "provider_retries_possible": 0,
            "fingerprint": fingerprint,
        }
    except Exception as exc:
        return {
            "trial_index": trial_index,
            "workers": workers,
            "success": False,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "provider_failures": 1,
            "retry_attempts_configured": 1,
            "provider_retries_possible": 0,
            "error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        if previous_workers is None:
            os.environ.pop("ZUNDAMOTION_AUDIO_WORKERS", None)
        else:
            os.environ["ZUNDAMOTION_AUDIO_WORKERS"] = previous_workers
        if previous_url is None:
            os.environ.pop("VOICEVOX_URL", None)
        else:
            os.environ["VOICEVOX_URL"] = previous_url


def _comparison(trials: list[dict[str, Any]]) -> dict[str, Any]:
    successful = [item for item in trials if item.get("success")]
    by_workers = {
        workers: [
            float(item["elapsed_seconds"])
            for item in successful
            if int(item["workers"]) == workers
        ]
        for workers in (1, 2)
    }
    medians = {
        str(workers): (
            round(statistics.median(values), 3) if values else None
        )
        for workers, values in by_workers.items()
    }
    one = medians["1"]
    two = medians["2"]
    speedup = (
        round(float(one) / float(two), 6)
        if one is not None and two is not None and float(two) > 0
        else None
    )
    improvement = (
        round((1.0 - (float(two) / float(one))) * 100.0, 3)
        if one is not None and two is not None and float(one) > 0
        else None
    )

    reference = successful[0].get("fingerprint") if successful else None
    equivalence = [
        {
            "trial_index": item["trial_index"],
            "workers": item["workers"],
            "matches_reference": item.get("fingerprint") == reference,
        }
        for item in successful
    ]
    return {
        "median_elapsed_seconds": medians,
        "worker2_speedup_vs_worker1": speedup,
        "worker2_improvement_percent": improvement,
        "all_successful_trials_equivalent": bool(successful)
        and all(item["matches_reference"] for item in equivalence),
        "equivalence": equivalence,
        "provider_failures": sum(int(item.get("provider_failures", 0)) for item in trials),
    }


async def run_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = (ROOT_DIR / output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    version = _voicevox_version(args.voicevox_url, args.timeout)
    schedule = _worker_schedule(args.rounds)
    trials = []
    for index, workers in enumerate(schedule, start=1):
        trial = await _run_trial(
            trial_index=index,
            workers=workers,
            output_dir=output_dir,
            voicevox_url=args.voicevox_url,
            speaker=args.speaker,
            line_count=args.lines,
            timeout=args.timeout,
        )
        trials.append(trial)
        if not trial.get("success"):
            break

    runtime_lock = ROOT_DIR / ".devcontainer" / "runtime.lock.json"
    return {
        "schema_version": SCHEMA_VERSION,
        "benchmark": "audio-worker-voicevox",
        "conditions": {
            "voicevox_url": args.voicevox_url,
            "voicevox_version": version,
            "speaker": args.speaker,
            "lines": args.lines,
            "rounds": args.rounds,
            "schedule": schedule,
            "provider_retry_attempts": 1,
            "python": sys.version,
            "platform": platform.platform(),
            "cpu_count": os.cpu_count(),
            "runtime_lock_sha256": _sha256(runtime_lock),
        },
        "trials": trials,
        "comparison": _comparison(trials),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--voicevox-url",
        default=os.getenv("VOICEVOX_URL", "http://127.0.0.1:50021"),
    )
    parser.add_argument("--speaker", type=int, default=3)
    parser.add_argument("--lines", type=int, default=DEFAULT_LINES)
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument(
        "--output-dir",
        default="output/benchmarks/audio-workers",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.lines < 1 or args.rounds < 1:
        raise SystemExit("--lines and --rounds must be >= 1")
    result = asyncio.run(run_benchmark(args))
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = (ROOT_DIR / output_dir).resolve()
    result_path = output_dir / "audio-worker-benchmark.json"
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(result_path)
    comparison = result["comparison"]
    ok = (
        comparison["provider_failures"] == 0
        and comparison["all_successful_trials_equivalent"]
        and len(result["trials"]) == len(result["conditions"]["schedule"])
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
