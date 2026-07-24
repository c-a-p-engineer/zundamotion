"""Shared, deliberately small helpers for the feature-demo site tools."""
from __future__ import annotations

import hashlib
import json
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]


def load_manifest(path: Path | None = None) -> dict[str, Any]:
    with (path or ROOT / "site/features.yml").open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def sha256(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(str(path.relative_to(ROOT)).encode())
        digest.update(path.read_bytes())
    return f"sha256:{digest.hexdigest()}"


@lru_cache(maxsize=1)
def _common_feature_input_hash() -> str:
    tracked = [
        ROOT / "site/render_demos.py",
        ROOT / "site/site_lib.py",
        ROOT / ".devcontainer/runtime.lock.json",
        ROOT / "pyproject.toml",
    ]
    tracked.extend(sorted((ROOT / "zundamotion").rglob("*.py")))
    tracked.extend(
        sorted(path for path in (ROOT / "assets").rglob("*") if path.is_file())
    )
    return sha256(tracked)


def feature_input_hash(feature: dict[str, Any]) -> str:
    demo = ROOT / feature["demo"]["script"]
    digest = hashlib.sha256()
    digest.update(_common_feature_input_hash().encode())
    digest.update(str(demo.relative_to(ROOT)).encode())
    digest.update(demo.read_bytes())
    return f"sha256:{digest.hexdigest()}"


def run_json(command: list[str]) -> dict[str, Any]:
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
