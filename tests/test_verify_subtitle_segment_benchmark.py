from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from verify_subtitle_segment_benchmark import _framemd5_content_signature


def test_framemd5_content_signature_ignores_timestamp_fields() -> None:
    left = """#format: frame checksums\n0, 0, 0, 1, 100, abcdef\n0, 1, 1, 1, 120, 123456\n"""
    right = """#format: frame checksums\n0, 100, 100, 1, 100, abcdef\n0, 101, 101, 1, 120, 123456\n"""

    assert _framemd5_content_signature(left) == _framemd5_content_signature(right)


def test_framemd5_content_signature_detects_payload_difference() -> None:
    left = "0, 0, 0, 1, 100, abcdef\n"
    right = "0, 0, 0, 1, 100, fedcba\n"

    assert _framemd5_content_signature(left) != _framemd5_content_signature(right)
