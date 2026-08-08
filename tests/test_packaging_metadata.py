from __future__ import annotations

from pathlib import Path
import tomllib


def test_pyproject_uses_pep639_license_metadata() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]
    assert project["license"] == "MIT"
    assert project["license-files"] == ["LICENSE"]
    assert "setuptools>=77.0.3" in pyproject["build-system"]["requires"]
    assert Path("LICENSE").read_text(encoding="utf-8").startswith("MIT License")
