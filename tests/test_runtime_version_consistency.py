from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from check_runtime_versions import EXPECTED_FFMPEG_COMMIT, collect_versions, validate_versions


def write_sources(root: Path, *, cpu: str, gpu: str, docs: str) -> None:
    for relative, commit in {
        ".devcontainer/Dockerfile.cpu": cpu,
        ".devcontainer/Dockerfile.gpu": gpu,
        "docs/guides/setup_and_runtime.md": docs,
    }.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"ARG FFMPEG_COMMIT={commit}\n", encoding="utf-8")


def test_versions_match_when_every_source_is_fixed(tmp_path: Path) -> None:
    write_sources(tmp_path, cpu=EXPECTED_FFMPEG_COMMIT, gpu=EXPECTED_FFMPEG_COMMIT, docs=EXPECTED_FFMPEG_COMMIT)

    assert validate_versions(collect_versions(tmp_path)) == []


def test_versions_report_each_mismatch(tmp_path: Path) -> None:
    write_sources(tmp_path, cpu="a" * 40, gpu="b" * 40, docs="c" * 40)

    errors = validate_versions(collect_versions(tmp_path))

    assert len(errors) == 3
    assert "Dockerfile.cpu" in errors[0]
    assert "Dockerfile.gpu" in errors[1]
    assert "setup_and_runtime.md" in errors[2]


def test_versions_report_missing_value(tmp_path: Path) -> None:
    write_sources(tmp_path, cpu=EXPECTED_FFMPEG_COMMIT, gpu=EXPECTED_FFMPEG_COMMIT, docs=EXPECTED_FFMPEG_COMMIT)
    (tmp_path / ".devcontainer/Dockerfile.gpu").write_text("FROM test\n", encoding="utf-8")

    assert validate_versions(collect_versions(tmp_path)) == ["Dockerfile.gpu: FFMPEG_COMMIT is missing"]
