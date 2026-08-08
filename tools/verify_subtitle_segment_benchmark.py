#!/usr/bin/env python3
"""Verify subtitle segment benchmark performance, A/V, and stream contracts."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


def _framemd5_content_signature(text: str) -> dict[str, Any]:
    """Hash decoded frame payloads while intentionally ignoring DTS/PTS.

    FFmpeg ``framemd5`` records contain stream index, DTS, PTS, duration, frame
    size and the decoded-frame hash. Subtitle segment implementations may have a
    small, explicitly measured start-time difference while producing identical
    frame pixels. Timing is validated separately via ffprobe, so this signature
    compares only frame size/hash in frame order.
    """
    digest = hashlib.sha256()
    frames = 0
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        fields = [field.strip() for field in line.split(",", 5)]
        if len(fields) != 6:
            raise ValueError(f"unexpected framemd5 record: {raw_line!r}")
        size, frame_hash = fields[4], fields[5]
        digest.update(f"{size},{frame_hash}\n".encode("ascii"))
        frames += 1
    if frames <= 0:
        raise ValueError("framemd5 contained no decoded video frames")
    return {"frames": frames, "sha256": digest.hexdigest()}


def _decoded_video_content_signature(path: str) -> dict[str, Any]:
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-map", "0:v:0", "-f", "framemd5", "-"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    return _framemd5_content_signature(proc.stdout)


def _encoded_audio_md5(path: str) -> str:
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-map", "0:a:0", "-c:a", "copy", "-f", "md5", "-"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    return proc.stdout.strip()


def verify(root: Path) -> dict[str, Any]:
    report = json.loads((root / "subtitle-segment-worker-benchmark.json").read_text(encoding="utf-8"))
    trials = {
        trial["mode"] + (f"-w{trial['workers']}" if trial.get("workers") else ""): trial
        for trial in report["trials"]
    }
    legacy = trials["legacy_av_segments"]
    worker1 = trials["video_only-w1"]
    worker2 = trials["video_only-w2"]

    for trial in (legacy, worker1, worker2):
        assert trial["av_warnings_total"] == 0, trial
        assert trial["av"]["start_delta"] is not None
        assert trial["av"]["duration_delta"] is not None
        assert trial["av"]["start_delta"] <= 0.05, trial["av"]
        assert trial["av"]["duration_delta"] <= 0.05, trial["av"]

    comparison = report["comparison"]
    assert comparison["worker2_faster_than_legacy"], comparison
    assert comparison["worker2_faster_than_worker1"], comparison
    assert worker1["elapsed_seconds"] < legacy["elapsed_seconds"], comparison

    video_signatures = {
        "legacy": _decoded_video_content_signature(legacy["output"]),
        "worker1": _decoded_video_content_signature(worker1["output"]),
        "worker2": _decoded_video_content_signature(worker2["output"]),
    }
    frame_counts = {value["frames"] for value in video_signatures.values()}
    content_hashes = {value["sha256"] for value in video_signatures.values()}
    assert len(frame_counts) == 1, video_signatures
    assert len(content_hashes) == 1, video_signatures

    source_audio = _encoded_audio_md5(str(root / "base.mp4"))
    audio_hashes = {
        "source": source_audio,
        "worker1": _encoded_audio_md5(worker1["output"]),
        "worker2": _encoded_audio_md5(worker2["output"]),
    }
    assert audio_hashes["worker1"] == source_audio, audio_hashes
    assert audio_hashes["worker2"] == source_audio, audio_hashes

    return {
        "elapsed_seconds": {
            "legacy": legacy["elapsed_seconds"],
            "worker1": worker1["elapsed_seconds"],
            "worker2": worker2["elapsed_seconds"],
        },
        "ratios": comparison,
        "video_frame_content": video_signatures,
        "aac_stream_md5": audio_hashes,
        "av": {
            "legacy": legacy["av"],
            "worker1": worker1["av"],
            "worker2": worker2["av"],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("benchmark_dir", type=Path)
    args = parser.parse_args()
    root = args.benchmark_dir.resolve()
    result = verify(root)
    (root / "verification.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
