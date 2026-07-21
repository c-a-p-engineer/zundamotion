#!/usr/bin/env python3
"""Install one checksum-verified BtbN FFmpeg archive from runtime.lock.json."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
from pathlib import Path


class LockedFfmpegError(RuntimeError):
    pass


def fail(code: str) -> None:
    raise LockedFfmpegError(code)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--prefix", type=Path, default=Path("/opt/ffmpeg"))
    args = parser.parse_args()
    try:
        lock = json.loads(args.lock.read_text(encoding="utf-8"))
        ffmpeg = lock["ffmpeg"]
        required = lock["required"]
    except Exception as exc:
        raise LockedFfmpegError("lock_invalid") from exc
    if not isinstance(ffmpeg.get("sha256"), str) or len(ffmpeg["sha256"]) != 64:
        fail("lock_invalid")

    url = (
        "https://github.com/BtbN/FFmpeg-Builds/releases/download/"
        f"{ffmpeg['release_tag']}/{ffmpeg['asset']}"
    )
    with tempfile.TemporaryDirectory() as directory:
        archive = Path(directory) / ffmpeg["asset"]
        digest = hashlib.sha256()
        try:
            with urllib.request.urlopen(url, timeout=120) as response, archive.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    digest.update(chunk)
                    output.write(chunk)
        except Exception as exc:
            raise LockedFfmpegError("download_failed") from exc
        if digest.hexdigest() != ffmpeg["sha256"]:
            fail("checksum_mismatch")

        unpack = Path(directory) / "unpack"
        try:
            with tarfile.open(archive) as package:
                package.extractall(unpack, filter="data")
        except Exception as exc:
            raise LockedFfmpegError("archive_invalid") from exc
        roots = list(unpack.iterdir())
        if len(roots) != 1:
            fail("archive_invalid")
        source = roots[0]
        if not (source / "bin/ffmpeg").is_file():
            fail("ffmpeg_missing")
        if not (source / "bin/ffprobe").is_file():
            fail("ffprobe_missing")
        if args.prefix.exists():
            shutil.rmtree(args.prefix)
        shutil.copytree(source, args.prefix)

    for name in ("ffmpeg", "ffprobe"):
        link = Path("/usr/local/bin", name)
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(args.prefix / "bin" / name)

    binary = str(args.prefix / "bin/ffmpeg")
    version = subprocess.check_output([binary, "-version"], text=True)
    if not version.lower().startswith(ffmpeg["expected_version_prefix"].lower()):
        fail("version_mismatch")
    encoders = subprocess.check_output(
        [binary, "-hide_banner", "-encoders"], text=True, stderr=subprocess.STDOUT
    )
    missing_encoders = [name for name in required["encoders"] if name not in encoders]
    if missing_encoders:
        fail("required_encoder_missing:" + ",".join(missing_encoders))
    buildconf = subprocess.check_output([binary, "-buildconf"], text=True)
    missing_flags = [flag for flag in required["configure_flags"] if flag not in buildconf]
    if missing_flags:
        fail("required_configure_flag_missing:" + ",".join(missing_flags))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
