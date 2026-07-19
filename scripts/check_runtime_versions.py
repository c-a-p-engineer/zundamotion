#!/usr/bin/env python3
"""Check that CPU/GPU Dockerfiles and runtime documentation use one FFmpeg commit."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

EXPECTED_FFMPEG_COMMIT = "db69d06eeeab4f46da15030a80d539efb4503ca8"
VERSION_SOURCES = {
    "Dockerfile.cpu": Path(".devcontainer/Dockerfile.cpu"),
    "Dockerfile.gpu": Path(".devcontainer/Dockerfile.gpu"),
    "setup_and_runtime.md": Path("docs/guides/setup_and_runtime.md"),
}


def extract_commit(path: Path) -> str | None:
    if not path.is_file():
        return None
    match = re.search(r"FFMPEG_COMMIT=([0-9a-f]{40})", path.read_text(encoding="utf-8"))
    return match.group(1) if match else None


def collect_versions(root: Path) -> dict[str, str | None]:
    return {name: extract_commit(root / relative_path) for name, relative_path in VERSION_SOURCES.items()}


def validate_versions(values: dict[str, str | None], expected: str = EXPECTED_FFMPEG_COMMIT) -> list[str]:
    errors: list[str] = []
    for source, value in values.items():
        if value is None:
            errors.append(f"{source}: FFMPEG_COMMIT is missing")
        elif value != expected:
            errors.append(f"{source}: expected {expected}, got {value}")
    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    errors = validate_versions(collect_versions(args.root))
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
