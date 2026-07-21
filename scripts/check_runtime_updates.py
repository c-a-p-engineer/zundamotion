#!/usr/bin/env python3
"""Check official Python and FFmpeg stable releases; write only on explicit request."""

from __future__ import annotations

import argparse
import hashlib
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


def source_sha256(url: str) -> str:
    with urllib.request.urlopen(url, timeout=120) as response:
        digest = hashlib.sha256()
        while chunk := response.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def candidate_lock(lock: dict[str, object], python_version: str, ffmpeg_version: str) -> dict[str, object]:
    candidate = json.loads(json.dumps(lock))
    python = candidate["python"]
    ffmpeg = candidate["ffmpeg"]
    python["version"] = python_version
    python["source_url"] = f"https://www.python.org/ftp/python/{python_version}/Python-{python_version}.tar.xz"
    ffmpeg["version"] = ffmpeg_version
    ffmpeg["source_url"] = f"https://ffmpeg.org/releases/ffmpeg-{ffmpeg_version}.tar.xz"
    python["source_sha256"] = source_sha256(python["source_url"])
    ffmpeg["source_sha256"] = source_sha256(ffmpeg["source_url"])
    for image in candidate["runtime_images"].values():
        image["tag"] = f"python-{python_version}-ffmpeg-{ffmpeg_version}"
        image["digest"] = None
    return candidate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write a changed candidate lock")
    parser.add_argument("--lock", type=Path, default=LOCK_PATH)
    args = parser.parse_args()
    lock = load_lock(args.lock)
    python_version = latest_python_version(fetch_text(PYTHON_SOURCE_INDEX))
    ffmpeg_version = latest_ffmpeg_version(fetch_text(FFMPEG_RELEASES))
    if (python_version, ffmpeg_version) == (lock["python"]["version"], lock["ffmpeg"]["version"]):
        return 0
    if args.write:
        args.lock.write_text(json.dumps(candidate_lock(lock, python_version, ffmpeg_version), indent=2) + "\n", encoding="utf-8")
    else:
        print(json.dumps({"python": python_version, "ffmpeg": ffmpeg_version}))
    return 10


if __name__ == "__main__":
    raise SystemExit(main())
