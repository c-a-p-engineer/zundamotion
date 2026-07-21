from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from runtime_lock import load_lock, runtime_build_args, runtime_image_ref, validate_lock


def test_committed_lock_is_valid_for_bootstrap() -> None:
    assert validate_lock(load_lock(), allow_unpublished_images=True) == []


def test_runtime_build_args_are_derived_from_lock() -> None:
    lock = load_lock()
    cpu = runtime_build_args(lock, "cpu")
    gpu = runtime_build_args(lock, "gpu")

    assert cpu["FFMPEG_SOURCE_SHA256"] == lock["ffmpeg"]["source_sha256"]
    assert lock["python"]["cpu_base_digest"] in cpu["CPU_BASE_IMAGE"]
    assert lock["gpu"]["cuda_base_digest"] in gpu["CUDA_BASE_IMAGE"]


def test_unpublished_runtime_cannot_be_used_as_a_dev_image() -> None:
    try:
        runtime_image_ref(load_lock(), "cpu")
    except ValueError as exc:
        assert "not published" in str(exc)
    else:
        raise AssertionError("unpublished image must not have a runtime reference")
