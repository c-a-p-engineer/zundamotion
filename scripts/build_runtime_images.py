#!/usr/bin/env python3
"""Build digest-ready runtime images from the sole runtime lock file."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from runtime_lock import LOCK_PATH, load_lock, runtime_build_args


def run(command: list[str]) -> str:
    return subprocess.run(command, check=True, text=True, stdout=subprocess.PIPE).stdout


def local_tag(profile: str) -> str:
    return f"zundamotion-runtime-{profile}:candidate"


def build(lock: dict[str, object], profile: str) -> None:
    command = ["docker", "build", "--file", f".devcontainer/runtime/Dockerfile.{profile}", "--tag", local_tag(profile)]
    for key, value in runtime_build_args(lock, profile).items():
        command.extend(["--build-arg", f"{key}={value}"])
    command.append(".")
    run(command)


def push_and_update(lock: dict[str, object], profile: str) -> None:
    image = lock["runtime_images"][profile]
    remote_tag = f"{image['repository']}:{image['tag']}"
    run(["docker", "tag", local_tag(profile), remote_tag])
    run(["docker", "push", remote_tag])
    repo_digests = json.loads(run(["docker", "image", "inspect", remote_tag, "--format", "{{json .RepoDigests}}"]))
    prefix = f"{image['repository']}@"
    digest_ref = next((value for value in repo_digests if value.startswith(prefix)), None)
    if digest_ref is None:
        raise RuntimeError(f"could not resolve pushed digest for {remote_tag}")
    image["digest"] = digest_ref.removeprefix(prefix)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--load", action="store_true", help="build local candidate images")
    parser.add_argument("--push", action="store_true", help="push candidate images to GHCR")
    parser.add_argument("--update-lock", action="store_true", help="write digests after --push")
    parser.add_argument("--lock", type=Path, default=LOCK_PATH)
    args = parser.parse_args()
    if not args.load and not args.push:
        parser.error("one of --load or --push is required")
    lock = load_lock(args.lock)
    if args.load:
        for profile in ("cpu", "gpu"):
            build(lock, profile)
    if args.push:
        for profile in ("cpu", "gpu"):
            push_and_update(lock, profile)
    if args.update_lock:
        args.lock.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
