from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from verify_reproducibility import compare_values


def test_compare_values_reports_nested_media_difference() -> None:
    differences = compare_values(
        {"streams": [{"width": 1920, "height": 1080}]},
        {"streams": [{"width": 1280, "height": 1080}]},
    )
    assert differences == [{"path": "$.streams[0].width", "left": 1920, "right": 1280}]


def test_compare_values_accepts_identical_structures() -> None:
    value = {"duration": "1.000", "hash": ["a", "b"]}
    assert compare_values(value, value) == []
