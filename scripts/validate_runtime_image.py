#!/usr/bin/env python3
"""Validate runtime metadata and profile-specific FFmpeg capabilities."""

from __future__ import annotations

import argparse
import json
import subprocess


def container_output(image: str, command: str) -> str:
    result = subprocess.run(["docker", "run", "--rm", "--entrypoint", "sh", image, "-lc", command], check=True, text=True, stdout=subprocess.PIPE)
    return result.stdout


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--profile", choices=("cpu", "gpu"), required=True)
    args = parser.parse_args()
    payload = json.loads(container_output(args.image, "cat /opt/zundamotion-build-info/build-info.json"))
    required_encoders = {"libx264", "libx265", "aac"}
    if args.profile == "gpu":
        required_encoders.update(("h264_nvenc", "hevc_nvenc"))
    missing = [name for name in required_encoders if not payload["encoders"].get(name)]
    if missing or not payload["filters"].get("libfreetype"):
        raise SystemExit(f"runtime capability validation failed: encoders={missing}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
