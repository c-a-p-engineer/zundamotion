#!/usr/bin/env python3
"""Write reproducible, runtime-derived FFmpeg build metadata."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable

DEFAULT_OUTPUT = Path("/opt/zundamotion-build-info/build-info.json")
CommandRunner = Callable[[list[str]], str]


def run_command(command: list[str]) -> str:
    """Run a command and return its combined UTF-8 output."""
    completed = subprocess.run(
        command,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout


def contains_capability(listing: str, capability: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(capability)}(?![A-Za-z0-9_])", listing) is not None


def build_payload(
    *,
    profile: str,
    ffmpeg_source_url: str,
    ffmpeg_source_sha256: str,
    nv_codec_headers: str | None,
    cuda_base_image: str | None,
    command_runner: CommandRunner = run_command,
) -> dict[str, object]:
    """Collect installed capabilities so metadata reflects the built image."""
    ffmpeg_version = command_runner(["ffmpeg", "-version"]).splitlines()[0]
    buildconf = command_runner(["ffmpeg", "-buildconf"])
    encoders = command_runner(["ffmpeg", "-hide_banner", "-encoders"])
    filters = command_runner(["ffmpeg", "-hide_banner", "-filters"])
    python_version = command_runner([sys.executable, "--version"]).strip()
    configure_options = re.findall(r"--[A-Za-z0-9_-]+(?:=[^\s]+)?", buildconf)

    return {
        "profile": profile,
        "python_version": python_version,
        "ffmpeg_version": ffmpeg_version,
        "ffmpeg_source_url": ffmpeg_source_url,
        "ffmpeg_source_sha256": ffmpeg_source_sha256,
        "ffmpeg_configure": configure_options,
        "encoders": {
            name: contains_capability(encoders, name)
            for name in ("libx264", "libx265", "h264_nvenc", "hevc_nvenc", "aac")
        },
        "filters": {
            "libfreetype": "--enable-libfreetype" in configure_options,
            **{
                name: contains_capability(filters, name)
                for name in ("overlay", "drawtext", "overlay_cuda", "scale_cuda", "scale_npp")
            },
        },
        "cuda_base_image": cuda_base_image,
        "nv_codec_headers": nv_codec_headers,
    }


def write_build_info(output: Path, payload: dict[str, object]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    lock = json.loads(args.lock.read_text(encoding="utf-8"))
    payload = build_payload(
        profile="unified",
        ffmpeg_source_url=f"btbn:{lock['ffmpeg']['release_tag']}/{lock['ffmpeg']['asset']}",
        ffmpeg_source_sha256=lock["ffmpeg"]["sha256"],
        nv_codec_headers=None,
        cuda_base_image=None,
    )
    write_build_info(args.output, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
