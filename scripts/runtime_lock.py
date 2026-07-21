"""Runtime lock loading and validation for the fixed BtbN FFmpeg archive."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

LOCK_PATH = Path(__file__).resolve().parents[1] / ".devcontainer/runtime.lock.json"
SHA256_PREFIX = "sha256:"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def load_lock(path: Path = LOCK_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_lock(lock: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if lock.get("schema_version") != 1:
        errors.append("schema_version must be 1")

    python = lock.get("python", {})
    for key in ("version", "image", "image_digest"):
        if not python.get(key):
            errors.append(f"python.{key} is required")
    if not DIGEST_RE.fullmatch(str(python.get("image_digest", ""))):
        errors.append("python.image_digest must be a sha256 digest")
    if "latest" in str(python.get("image", "")).lower():
        errors.append("python.image must not use latest")

    ffmpeg = lock.get("ffmpeg", {})
    for key in (
        "official_version",
        "provider",
        "release_tag",
        "asset",
        "sha256",
        "expected_version_prefix",
    ):
        if not ffmpeg.get(key):
            errors.append(f"ffmpeg.{key} is required")
    if ffmpeg.get("provider") != "btbn":
        errors.append("ffmpeg.provider must be btbn")
    release_tag = str(ffmpeg.get("release_tag", ""))
    if not release_tag.startswith("autobuild-") or "latest" in release_tag.lower():
        errors.append("ffmpeg.release_tag must be a fixed autobuild-* tag")
    if not SHA256_RE.fullmatch(str(ffmpeg.get("sha256", ""))):
        errors.append("ffmpeg.sha256 must be a 64-character lowercase SHA256")

    voicevox = lock.get("voicevox", {})
    for profile in ("cpu", "gpu"):
        image_key = f"{profile}_image"
        digest_key = f"{profile}_digest"
        image = voicevox.get(image_key)
        digest = voicevox.get(digest_key)
        if not isinstance(image, str) or not image.strip():
            errors.append(f"voicevox.{image_key} is required")
        elif "latest" in image.lower():
            errors.append(f"voicevox.{image_key} must not use latest")
        if not DIGEST_RE.fullmatch(str(digest or "")):
            errors.append(f"voicevox.{digest_key} must be a sha256 digest")

    font = lock.get("font", {})
    for key in ("package", "required_path"):
        if not isinstance(font.get(key), str) or not font[key].strip():
            errors.append(f"font.{key} is required")
    if font.get("required_path") and not str(font["required_path"]).startswith("/"):
        errors.append("font.required_path must be absolute")

    required = lock.get("required", {})
    for key in ("encoders", "configure_flags"):
        value = required.get(key)
        if not isinstance(value, list) or not value or not all(isinstance(item, str) and item for item in value):
            errors.append(f"required.{key} must be a non-empty string list")

    optional_filters = lock.get("optional_filters")
    if not isinstance(optional_filters, list) or not all(isinstance(item, str) and item for item in optional_filters):
        errors.append("optional_filters must be a string list")
    if not lock.get("verified_at"):
        errors.append("verified_at is required")
    return errors


def ffmpeg_download_url(lock: dict[str, Any]) -> str:
    ffmpeg = lock["ffmpeg"]
    return (
        "https://github.com/BtbN/FFmpeg-Builds/releases/download/"
        f"{ffmpeg['release_tag']}/{ffmpeg['asset']}"
    )


def python_image_ref(lock: dict[str, Any]) -> str:
    python = lock["python"]
    return f"{python['image']}@{python['image_digest']}"


def voicevox_image_ref(lock: dict[str, Any], profile: str) -> str:
    if profile not in {"cpu", "gpu"}:
        raise ValueError(f"unsupported VOICEVOX profile: {profile}")
    voicevox = lock["voicevox"]
    return f"{voicevox[f'{profile}_image']}@{voicevox[f'{profile}_digest']}"
