from __future__ import annotations

import asyncio
import os

import pytest

from zundamotion import pipeline_entry
from zundamotion.utils import ffmpeg_capabilities


def test_cpu_policy_is_set_only_inside_context(monkeypatch) -> None:
    monkeypatch.delenv("DISABLE_HWENC", raising=False)

    with pipeline_entry._encoder_policy_environment("cpu"):
        assert os.environ["DISABLE_HWENC"] == "1"

    assert "DISABLE_HWENC" not in os.environ


def test_cpu_policy_restores_existing_value(monkeypatch) -> None:
    monkeypatch.setenv("DISABLE_HWENC", "custom")

    with pipeline_entry._encoder_policy_environment("cpu"):
        assert os.environ["DISABLE_HWENC"] == "1"

    assert os.environ["DISABLE_HWENC"] == "custom"


def test_auto_policy_does_not_modify_environment(monkeypatch) -> None:
    monkeypatch.setenv("DISABLE_HWENC", "custom")

    with pipeline_entry._encoder_policy_environment("auto"):
        assert os.environ["DISABLE_HWENC"] == "custom"

    assert os.environ["DISABLE_HWENC"] == "custom"


def test_policy_context_does_not_suppress_exceptions(monkeypatch) -> None:
    monkeypatch.delenv("DISABLE_HWENC", raising=False)

    with pytest.raises(RuntimeError, match="expected"):
        with pipeline_entry._encoder_policy_environment("auto"):
            raise RuntimeError("expected")


def test_downstream_encoder_resolution_skips_gpu_probe(monkeypatch) -> None:
    monkeypatch.delenv("DISABLE_HWENC", raising=False)

    async def unexpected_probe(*args, **kwargs):
        raise AssertionError("GPU encoder probe must not run in CPU policy scope")

    monkeypatch.setattr(
        ffmpeg_capabilities,
        "is_nvenc_available",
        unexpected_probe,
    )

    with pipeline_entry._encoder_policy_environment("cpu"):
        resolved = asyncio.run(
            ffmpeg_capabilities.get_hw_encoder_kind_for_video_params(
                hw_encoder="auto"
            )
        )

    assert resolved is None
