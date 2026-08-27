from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import yaml

from zundamotion.authoring import (
    CAPABILITIES_FORMAT,
    COMPILED_FORMAT,
    VALIDATION_FORMAT,
    capabilities_document,
    compiled_document,
    validation_document,
)

ROOT = Path(__file__).resolve().parents[1]


def _write_script(path: Path, data: dict) -> None:
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def test_capabilities_document_is_machine_readable_and_stable() -> None:
    document = capabilities_document()

    assert document["format"] == CAPABILITIES_FORMAT
    assert document["format_version"] == 1
    assert document["tts"]["default_provider"] == "voicevox"
    assert "youtube_1080p" in document["export_presets"]
    assert {"validate", "compile", "capabilities"}.issubset(document["commands"])
    assert document["plugins"] == sorted(
        document["plugins"], key=lambda item: (item["kind"], item["id"])
    )


def test_compile_uses_render_loader_contract(tmp_path: Path) -> None:
    script = tmp_path / "minimal.yaml"
    _write_script(script, {"meta": {"title": "minimal", "version": 3}, "scenes": []})

    document = compiled_document(str(script))

    assert document["format"] == COMPILED_FORMAT
    assert document["format_version"] == 1
    assert document["config"]["script"]["meta"]["title"] == "minimal"
    assert document["config"]["script"]["scenes"] == []


def test_validation_document_reports_stable_error_code(tmp_path: Path) -> None:
    script = tmp_path / "invalid.yaml"
    _write_script(script, {"meta": {"title": "invalid", "version": 3}, "scenes": "bad"})

    document = validation_document(str(script))

    assert document["format"] == VALIDATION_FORMAT
    assert document["format_version"] == 1
    assert document["valid"] is False
    assert document["errors"][0]["code"] == "ZDM-E1000"
    assert "scenes" in document["errors"][0]["message"]


def test_module_cli_help_lists_authoring_commands() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "zundamotion", "--help"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    assert "validate" in proc.stdout
    assert "compile" in proc.stdout
    assert "capabilities" in proc.stdout
    assert "render" in proc.stdout


def test_module_cli_capabilities_json_does_not_start_render_runtime() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "zundamotion", "capabilities", "--json"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    document = json.loads(proc.stdout)
    assert document["format"] == CAPABILITIES_FORMAT
    assert document["tts"]["providers"] == ["voicevox"]


def test_module_cli_compile_to_stdout(tmp_path: Path) -> None:
    script = tmp_path / "minimal.yaml"
    _write_script(script, {"meta": {"title": "cli", "version": 3}, "scenes": []})

    proc = subprocess.run(
        [sys.executable, "-m", "zundamotion", "compile", str(script)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    document = json.loads(proc.stdout)
    assert document["format"] == COMPILED_FORMAT
    assert document["config"]["script"]["meta"]["title"] == "cli"
