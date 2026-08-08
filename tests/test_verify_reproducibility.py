from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from verify_reproducibility import build_render_command, compare_values, run


def test_compare_values_reports_nested_media_difference() -> None:
    differences = compare_values(
        {"streams": [{"width": 1920, "height": 1080}]},
        {"streams": [{"width": 1280, "height": 1080}]},
    )
    assert differences == [{"path": "$.streams[0].width", "left": 1920, "right": 1280}]


def test_compare_values_accepts_identical_structures() -> None:
    value = {"duration": "1.000", "hash": ["a", "b"]}
    assert compare_values(value, value) == []


def test_build_render_command_forwards_explicit_jobs(tmp_path: Path) -> None:
    args = argparse.Namespace(
        hw_encoder="cpu",
        no_voice=True,
        jobs="1",
        timeout=60,
    )
    command = build_render_command(
        tmp_path / "script.yaml",
        tmp_path / "out.mp4",
        args,
        tmp_path,
    )

    jobs_index = command.index("--jobs")
    assert command[jobs_index + 1] == "1"
    assert "--no-voice" in command


def test_build_render_command_omits_jobs_when_not_requested(tmp_path: Path) -> None:
    args = argparse.Namespace(
        hw_encoder="cpu",
        no_voice=False,
        jobs=None,
        timeout=60,
    )
    command = build_render_command(
        tmp_path / "script.yaml",
        tmp_path / "out.mp4",
        args,
        tmp_path,
    )

    assert "--jobs" not in command


def test_run_persists_partial_logs_when_command_times_out(tmp_path, monkeypatch) -> None:
    def _timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(
            cmd=["example"],
            timeout=1,
            output=b"partial stdout",
            stderr=b"partial stderr",
        )

    monkeypatch.setattr(subprocess, "run", _timeout)
    log_prefix = tmp_path / "run-1.render"

    with pytest.raises(RuntimeError, match="command timed out"):
        run(
            ["example"],
            cwd=tmp_path,
            timeout=1,
            log_prefix=log_prefix,
        )

    assert (tmp_path / "run-1.render.stdout.log").read_text(encoding="utf-8") == "partial stdout"
    assert (tmp_path / "run-1.render.stderr.log").read_text(encoding="utf-8") == "partial stderr"
    assert "example" in (tmp_path / "run-1.render.command.json").read_text(encoding="utf-8")