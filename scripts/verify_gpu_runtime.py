#!/usr/bin/env python3
"""Verify the Python 3.14/NVENC runtime and render a short GPU smoke video."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]


def run(command: list[str], *, echo: bool = True) -> str:
    completed = subprocess.run(
        command,
        cwd=ROOT_DIR,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if echo:
        print(completed.stdout, end="")
    if completed.returncode:
        raise subprocess.CalledProcessError(completed.returncode, command, completed.stdout)
    return completed.stdout


def ffprobe_streams(path: Path) -> list[dict[str, object]]:
    payload = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-of",
            "json",
            str(path),
        ]
    )
    return json.loads(payload)["streams"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT_DIR / "output" / "gpu-smoke" / "gpu-smoke.mp4",
    )
    parser.add_argument("--skip-render", action="store_true")
    args = parser.parse_args()

    report: dict[str, object] = {"python": sys.version, "root": str(ROOT_DIR)}
    if sys.version_info[:2] != (3, 14):
        raise RuntimeError(f"Python 3.14 is required, got {sys.version.split()[0]}")

    report["nvidia_smi"] = run(["nvidia-smi"])
    encoders = run(["ffmpeg", "-hide_banner", "-encoders"], echo=False)
    filters = run(["ffmpeg", "-hide_banner", "-filters"], echo=False)
    if "h264_nvenc" not in encoders:
        raise RuntimeError("h264_nvenc is unavailable")
    run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=128x128:d=0.1",
            "-c:v",
            "h264_nvenc",
            "-f",
            "null",
            "-",
        ]
    )
    report["nvenc_smoke_test"] = True
    report["gpu_filters"] = [
        name
        for name in ("overlay_cuda", "scale_cuda", "scale_npp", "overlay_opencl")
        if name in filters
    ]
    print(f"GPU capabilities: h264_nvenc, {', '.join(report['gpu_filters'])}")

    if not args.skip_render:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        render_log = run(
            [
                "env",
                "HW_FILTER_MODE=cpu",
                "zundamotion",
                "scripts/smoke_minimal.yaml",
                "-o",
                str(args.output),
                "--hw-encoder",
                "gpu",
                "--quality",
                "speed",
                "--jobs",
                "1",
                "--log-kv",
            ]
        )
        report["filter_mode"] = "cpu"
        report["nvenc_selected"] = (
            "h264_nvenc" in render_log
            and "GPU encoding was requested, but NVENC is not available" not in render_log
            and "Falling back to CPU" not in render_log
        )
        report["dts_warnings"] = sum(
            token in render_log.lower()
            for token in ("non-monotonic dts", "non monotonically increasing dts")
        )
        streams = ffprobe_streams(args.output)
        report["streams"] = streams
        codecs = {str(stream.get("codec_type")): str(stream.get("codec_name")) for stream in streams}
        if codecs.get("video") != "h264" or codecs.get("audio") != "aac":
            raise RuntimeError(f"unexpected output codecs: {codecs}")
        if not report["nvenc_selected"] or report["dts_warnings"]:
            raise RuntimeError("GPU render did not meet NVENC/DTS expectations")

    report_path = args.output.with_suffix(".report.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"GPU smoke report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
