from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from runtime_lock import ffmpeg_download_url, load_lock, python_image_ref, validate_lock


def test_committed_lock_is_valid() -> None:
    assert validate_lock(load_lock()) == []


def test_refs_are_derived_from_current_lock() -> None:
    lock = load_lock()
    assert ffmpeg_download_url(lock).endswith(
        f"/{lock['ffmpeg']['release_tag']}/{lock['ffmpeg']['asset']}"
    )
    assert python_image_ref(lock) == (
        f"{lock['python']['image']}@{lock['python']['image_digest']}"
    )


def test_floating_release_is_rejected() -> None:
    lock = copy.deepcopy(load_lock())
    lock["ffmpeg"]["release_tag"] = "latest"
    assert "ffmpeg.release_tag must be a fixed autobuild-* tag" in validate_lock(lock)


def test_invalid_archive_checksum_is_rejected() -> None:
    lock = copy.deepcopy(load_lock())
    lock["ffmpeg"]["sha256"] = "not-a-checksum"
    assert "ffmpeg.sha256 must be a 64-character lowercase SHA256" in validate_lock(lock)
