#!/usr/bin/env python3
"""Report upstream Python/FFmpeg versions for a manual runtime-lock review."""

from __future__ import annotations

import argparse
import json
import re
import urllib.request
from pathlib import Path

from runtime_lock import LOCK_PATH, load_lock

PYTHON_SOURCE_INDEX = "https://www.python.org/downloads/source/"
FFMPEG_RELEASES = "https://ffmpeg.org/releases/"


def fetch_text(url: str) -> str:
    with urllib.request.urlopen(url, timeout=30) as response:
        return response.read().decode("utf-8")


def latest_python_version(page: str) -> str:
    matches = re.findall(r"Python (3\.14\.\d+)", page)
    if not matches:
        raise ValueError("no stable Python 3.14 release found")
    return max(matches, key=lambda value: tuple(map(int, value.split("."))))


def latest_ffmpeg_version(page: str) -> str:
    matches = re.findall(r"ffmpeg-(\d+\.\d+(?:\.\d+)?)\.tar\.xz", page)
    if not matches:
        raise ValueError("no FFmpeg release found")
    return max(matches, key=lambda value: tuple(map(int, value.split("."))))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write",
        action="store_true",
        help="unsupported safety flag; lock updates require verified digests and checksums",
    )
    parser.add_argument("--lock", type=Path, default=LOCK_PATH)
    args = parser.parse_args()
    lock = load_lock(args.lock)
    python_version = latest_python_version(fetch_text(PYTHON_SOURCE_INDEX))
    ffmpeg_version = latest_ffmpeg_version(fetch_text(FFMPEG_RELEASES))
    if args.write:
        parser.error(
            "automatic writes are disabled; verify the Python image digest, BtbN release/archive "
            "SHA256, and VOICEVOX digests, then edit runtime.lock.json manually"
        )
    current = (lock["python"]["version"], lock["ffmpeg"]["official_version"])
    latest = (python_version, ffmpeg_version)
    print(
        json.dumps(
            {
                "current": {"python": current[0], "ffmpeg": current[1]},
                "upstream": {"python": latest[0], "ffmpeg": latest[1]},
                "update_available": latest != current,
            }
        )
    )
    return 10 if latest != current else 0


if __name__ == "__main__":
    raise SystemExit(main())
