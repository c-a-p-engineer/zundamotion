#!/usr/bin/env python3
"""Render twice and compare media semantics, decoded streams, and sidecars."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def run(command: list[str], *, cwd: Path, timeout: int, binary: bool = False) -> bytes | str:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env={**os.environ, "USE_RAMDISK": "0", "DISABLE_HWENC": "1"},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    if completed.returncode:
        stderr = completed.stderr.decode("utf-8", errors="replace")[-4000:]
        raise RuntimeError(f"command failed ({completed.returncode}): {' '.join(command)}\n{stderr}")
    if binary:
        return completed.stdout
    return completed.stdout.decode("utf-8", errors="strict")


def semantic_probe(path: Path, *, cwd: Path, timeout: int) -> dict[str, Any]:
    raw = run(
        [
            "ffprobe", "-v", "error", "-show_entries",
            "format=duration:stream=index,codec_type,codec_name,width,height,avg_frame_rate,"
            "r_frame_rate,sample_rate,channels,channel_layout,duration,nb_frames",
            "-of", "json", str(path),
        ],
        cwd=cwd,
        timeout=timeout,
    )
    return json.loads(str(raw))


def decoded_hash(path: Path, stream: str, *, cwd: Path, timeout: int) -> str:
    if stream == "video":
        command = ["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:v:0", "-f", "framemd5", "-"]
    else:
        command = [
            "ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0",
            "-f", "s16le", "-acodec", "pcm_s16le", "-",
        ]
    data = run(command, cwd=cwd, timeout=timeout, binary=True)
    return hashlib.sha256(data).hexdigest()


def compare_values(left: Any, right: Any, path: str = "$") -> list[dict[str, Any]]:
    if type(left) is not type(right):
        return [{"path": path, "left": left, "right": right}]
    if isinstance(left, dict):
        differences: list[dict[str, Any]] = []
        for key in sorted(set(left) | set(right)):
            if key not in left or key not in right:
                differences.append({"path": f"{path}.{key}", "left": left.get(key), "right": right.get(key)})
            else:
                differences.extend(compare_values(left[key], right[key], f"{path}.{key}"))
        return differences
    if isinstance(left, list):
        if len(left) != len(right):
            return [{"path": path, "left_length": len(left), "right_length": len(right)}]
        differences = []
        for index, (left_item, right_item) in enumerate(zip(left, right)):
            differences.extend(compare_values(left_item, right_item, f"{path}[{index}]"))
        return differences
    return [] if left == right else [{"path": path, "left": left, "right": right}]


def render(script: Path, output: Path, args: argparse.Namespace, root: Path) -> None:
    command = [
        sys.executable, "-m", "zundamotion.main", str(script),
        "--project-root", str(root), "-o", str(output), "--no-cache",
        "--hw-encoder", args.hw_encoder, "--timeline", "both", "--subtitle-file", "both",
    ]
    if args.no_voice:
        command.append("--no-voice")
    run(command, cwd=root, timeout=args.timeout)


def sidecar_hashes(output: Path) -> dict[str, str | None]:
    results: dict[str, str | None] = {}
    for suffix in (".md", ".csv", ".srt", ".ass", ".chapters.txt", ".ffmetadata"):
        path = output.with_suffix(suffix)
        results[suffix] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("script", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--no-voice", action="store_true")
    parser.add_argument("--hw-encoder", choices=("cpu", "gpu"), default="cpu")
    parser.add_argument("--timeout", type=int, default=600)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    script = args.script if args.script.is_absolute() else (root / args.script)
    output_dir = args.output_dir if args.output_dir.is_absolute() else (root / args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = [output_dir / "run-1.mp4", output_dir / "run-2.mp4"]
    report_path = output_dir / "reproducibility-report.json"
    try:
        for output in outputs:
            render(script, output, args, root)
        probes = [semantic_probe(path, cwd=root, timeout=args.timeout) for path in outputs]
        video_hashes = [decoded_hash(path, "video", cwd=root, timeout=args.timeout) for path in outputs]
        audio_hashes = [decoded_hash(path, "audio", cwd=root, timeout=args.timeout) for path in outputs]
        sidecars = [sidecar_hashes(path) for path in outputs]
        differences = compare_values(probes[0], probes[1], "$.ffprobe")
        differences.extend(compare_values(video_hashes[0], video_hashes[1], "$.video_framemd5"))
        differences.extend(compare_values(audio_hashes[0], audio_hashes[1], "$.audio_pcm"))
        differences.extend(compare_values(sidecars[0], sidecars[1], "$.sidecars"))
        report = {
            "status": "pass" if not differences else "fail",
            "script": str(script),
            "no_voice": args.no_voice,
            "hw_encoder": args.hw_encoder,
            "ffprobe": probes,
            "video_framemd5_sha256": video_hashes,
            "audio_pcm_sha256": audio_hashes,
            "sidecars": sidecars,
            "differences": differences,
        }
    except Exception as exc:
        report = {"status": "error", "error": str(exc), "script": str(script)}
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(report_path)
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
