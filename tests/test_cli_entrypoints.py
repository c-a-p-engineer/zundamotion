from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from zundamotion.components.script.loader import load_script_and_config
from zundamotion.exceptions import ValidationError
from zundamotion.main import _apply_project_root


def test_python_module_entrypoint_help():
    proc = subprocess.run(
        [sys.executable, "-m", "zundamotion", "--help"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    # argparse prints help to stdout for --help
    assert "Generate a video" in (proc.stdout + proc.stderr)


def test_project_root_changes_relative_path_resolution(tmp_path):
    asset_path = tmp_path / "assets" / "bg" / "only_in_tmp.png"
    asset_path.parent.mkdir(parents=True, exist_ok=True)
    asset_path.write_bytes(b"")

    default_config_path = tmp_path / "default.yaml"
    default_config_path.write_text(
        yaml.safe_dump({"script": {"scenes": []}, "defaults": {}}),
        encoding="utf-8",
    )

    script_path = tmp_path / "script.yaml"
    script_path.write_text(
        yaml.safe_dump(
            {
                "meta": {"title": "project_root_test", "version": 3},
                "scenes": [
                    {
                        "id": "s1",
                        "bg": "assets/bg/only_in_tmp.png",
                        "lines": [{"text": "hello"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="does not exist"):
        load_script_and_config(str(script_path), str(default_config_path))

    prev = _apply_project_root(str(tmp_path))
    try:
        cfg = load_script_and_config(str(script_path), str(default_config_path))
        assert cfg["script"]["scenes"][0]["bg"] == "assets/bg/only_in_tmp.png"
    finally:
        if prev is not None:
            os.chdir(prev)

