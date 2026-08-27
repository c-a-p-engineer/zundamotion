from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import yaml

from zundamotion.render_lock import create_render_lock, verify_render_lock

ROOT = Path(__file__).resolve().parents[1]


def _write_script(path: Path, bg_path: str) -> None:
    path.write_text(
        yaml.safe_dump(
            {
                "meta": {"title": "lock", "version": 3},
                "scenes": [
                    {
                        "id": "scene1",
                        "bg": bg_path,
                        "lines": [{"wait": 0.1}],
                    }
                ],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )


def test_render_lock_detects_asset_changes(monkeypatch, tmp_path: Path) -> None:
    asset = tmp_path / "assets" / "bg.png"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"first")
    script = tmp_path / "script.yaml"
    _write_script(script, "assets/bg.png")
    monkeypatch.chdir(tmp_path)

    lock = create_render_lock("script.yaml", project_root=tmp_path)
    assets = {item["path"]: item["sha256"] for item in lock["assets"]}

    assert lock["format"] == "zundamotion.render-lock"
    assert lock["format_version"] == 1
    assert lock["source"]["script"] == "script.yaml"
    assert "assets/bg.png" in assets
    assert verify_render_lock("script.yaml", lock, project_root=tmp_path)["valid"] is True

    asset.write_bytes(b"second")
    verification = verify_render_lock("script.yaml", lock, project_root=tmp_path)

    assert verification["valid"] is False
    assert any(
        item["code"] == "ZDM-L1200" and item["subject"] == "assets:assets/bg.png"
        for item in verification["differences"]
    )


def test_render_lock_is_deterministic(monkeypatch, tmp_path: Path) -> None:
    script = tmp_path / "script.yaml"
    script.write_text(
        yaml.safe_dump({"meta": {"title": "same", "version": 3}, "scenes": []}),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    first = create_render_lock("script.yaml", project_root=tmp_path)
    second = create_render_lock("script.yaml", project_root=tmp_path)

    assert first == second


def test_render_lock_project_root_scopes_loader_and_restores_cwd(tmp_path: Path) -> None:
    asset = tmp_path / "assets" / "bg.png"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"asset")
    script = tmp_path / "script.yaml"
    _write_script(script, "assets/bg.png")
    original_cwd = Path.cwd()

    lock = create_render_lock("script.yaml", project_root=tmp_path)

    assert Path.cwd() == original_cwd
    assert any(item["path"] == "assets/bg.png" for item in lock["assets"])


def test_render_lock_cli_round_trip_and_difference_exit_code(tmp_path: Path) -> None:
    asset = tmp_path / "assets" / "bg.png"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"first")
    _write_script(tmp_path / "script.yaml", "assets/bg.png")

    lock_proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "zundamotion",
            "lock",
            "script.yaml",
            "--project-root",
            str(tmp_path),
            "-o",
            "zundamotion.lock.json",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert lock_proc.returncode == 0, lock_proc.stderr
    assert (tmp_path / "zundamotion.lock.json").is_file()

    verify_proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "zundamotion",
            "verify-lock",
            "script.yaml",
            "--project-root",
            str(tmp_path),
            "--lock-file",
            "zundamotion.lock.json",
            "--json",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert verify_proc.returncode == 0, verify_proc.stderr
    assert json.loads(verify_proc.stdout)["valid"] is True

    asset.write_bytes(b"changed")
    changed_proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "zundamotion",
            "verify-lock",
            "script.yaml",
            "--project-root",
            str(tmp_path),
            "--lock-file",
            "zundamotion.lock.json",
            "--json",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert changed_proc.returncode == 1, changed_proc.stderr
    document = json.loads(changed_proc.stdout)
    assert document["valid"] is False
    assert any(item["code"] == "ZDM-L1200" for item in document["differences"])
