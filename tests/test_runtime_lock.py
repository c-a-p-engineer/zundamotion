from __future__ import annotations

import copy
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from runtime_lock import (
    ffmpeg_download_url,
    load_lock,
    python_image_ref,
    validate_lock,
    voicevox_image_ref,
)


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
    assert voicevox_image_ref(lock, "cpu") == (
        f"{lock['voicevox']['cpu_image']}@{lock['voicevox']['cpu_digest']}"
    )


def test_floating_release_is_rejected() -> None:
    lock = copy.deepcopy(load_lock())
    lock["ffmpeg"]["release_tag"] = "latest"
    assert "ffmpeg.release_tag must be a fixed autobuild-* tag" in validate_lock(lock)


def test_invalid_archive_checksum_is_rejected() -> None:
    lock = copy.deepcopy(load_lock())
    lock["ffmpeg"]["sha256"] = "not-a-checksum"
    assert "ffmpeg.sha256 must be a 64-character lowercase SHA256" in validate_lock(lock)


def test_voicevox_floating_tag_is_rejected() -> None:
    lock = copy.deepcopy(load_lock())
    lock["voicevox"]["cpu_image"] = "voicevox/voicevox_engine:latest"
    assert "voicevox.cpu_image must not use latest" in validate_lock(lock)


def test_voicevox_invalid_digest_is_rejected() -> None:
    lock = copy.deepcopy(load_lock())
    lock["voicevox"]["gpu_digest"] = "sha256:not-a-digest"
    assert "voicevox.gpu_digest must be a sha256 digest" in validate_lock(lock)


def test_required_font_fields_are_validated() -> None:
    lock = copy.deepcopy(load_lock())
    lock["font"]["required_path"] = ""
    assert "font.required_path is required" in validate_lock(lock)


def test_missing_required_section_is_rejected() -> None:
    lock = copy.deepcopy(load_lock())
    del lock["voicevox"]
    errors = validate_lock(lock)
    assert "voicevox.cpu_image is required" in errors
    assert "voicevox.gpu_image is required" in errors


def test_compose_voicevox_defaults_match_lock() -> None:
    root = Path(__file__).resolve().parents[1]
    lock = load_lock()
    compose = yaml.safe_load((root / ".devcontainer/docker-compose.yml").read_text(encoding="utf-8"))
    gpu = yaml.safe_load(
        (root / ".devcontainer/docker-compose.voicevox-gpu.yml").read_text(encoding="utf-8")
    )
    cpu_ref = voicevox_image_ref(lock, "cpu")
    assert compose["services"]["voicevox"]["image"] == f"${{VOICEVOX_IMAGE:-{cpu_ref}}}"
    assert gpu["services"]["voicevox"]["image"] == voicevox_image_ref(lock, "gpu")


def test_dockerfile_installs_locked_font() -> None:
    root = Path(__file__).resolve().parents[1]
    lock = load_lock()
    dockerfile = (root / ".devcontainer/Dockerfile").read_text(encoding="utf-8")
    assert lock["font"]["package"] in dockerfile
    assert f"test -f {lock['font']['required_path']}" in dockerfile
