"""Runtime lock loading, validation, and Docker build argument generation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

LOCK_PATH = Path(__file__).resolve().parents[1] / ".devcontainer/runtime.lock.json"
SHA256_PREFIX = "sha256:"


def load_lock(path: Path = LOCK_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_lock(lock: dict[str, Any], *, allow_unpublished_images: bool = False) -> list[str]:
    errors: list[str] = []
    if lock.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    for group, keys in {
        "python": ("version", "series", "source_url", "source_sha256", "cpu_base_image", "cpu_base_digest"),
        "ffmpeg": ("version", "source_url", "source_sha256"),
        "gpu": ("cuda_base_image", "cuda_base_digest", "nv_codec_headers"),
    }.items():
        values = lock.get(group, {})
        for key in keys:
            if not values.get(key):
                errors.append(f"{group}.{key} is required")
    for group, key in (("python", "source_sha256"), ("ffmpeg", "source_sha256")):
        if len(lock.get(group, {}).get(key, "")) != 64:
            errors.append(f"{group}.{key} must be a SHA256 value")
    for group, key in (("python", "cpu_base_digest"), ("gpu", "cuda_base_digest")):
        if not lock.get(group, {}).get(key, "").startswith(SHA256_PREFIX):
            errors.append(f"{group}.{key} must be digest-pinned")
    for profile in ("cpu", "gpu"):
        image = lock.get("runtime_images", {}).get(profile, {})
        if not image.get("repository") or not image.get("tag"):
            errors.append(f"runtime_images.{profile} repository and tag are required")
        digest = image.get("digest")
        if digest is None and allow_unpublished_images:
            continue
        if not isinstance(digest, str) or not digest.startswith(SHA256_PREFIX):
            errors.append(f"runtime_images.{profile}.digest must be digest-pinned")
    return errors


def runtime_image_ref(lock: dict[str, Any], profile: str) -> str:
    image = lock["runtime_images"][profile]
    digest = image.get("digest")
    if not digest:
        raise ValueError(f"runtime image {profile} is not published; run runtime-update workflow first")
    return f"{image['repository']}@{digest}"


def runtime_build_args(lock: dict[str, Any], profile: str) -> dict[str, str]:
    common = {
        "FFMPEG_SOURCE_URL": lock["ffmpeg"]["source_url"],
        "FFMPEG_SOURCE_SHA256": lock["ffmpeg"]["source_sha256"],
        "FFMPEG_VERSION": lock["ffmpeg"]["version"],
    }
    if profile == "cpu":
        return {
            **common,
            "CPU_BASE_IMAGE": f"{lock['python']['cpu_base_image']}@{lock['python']['cpu_base_digest']}",
        }
    if profile == "gpu":
        return {
            **common,
            "CUDA_BASE_IMAGE": f"{lock['gpu']['cuda_base_image']}@{lock['gpu']['cuda_base_digest']}",
            "PYTHON_SOURCE_URL": lock["python"]["source_url"],
            "PYTHON_SOURCE_SHA256": lock["python"]["source_sha256"],
            "NV_CODEC_HEADERS_VERSION": lock["gpu"]["nv_codec_headers"],
        }
    raise ValueError(f"unknown profile: {profile}")
