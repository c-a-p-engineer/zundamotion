from __future__ import annotations

import asyncio
import json
from pathlib import Path
import shutil
import subprocess
import sys

from PIL import Image
import pytest

from zundamotion.output_qa import create_contact_sheet, inspect_output

ROOT = Path(__file__).resolve().parents[1]


def _require_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg/ffprobe are required for output QA integration")


def _make_fixture(path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=320x180:r=30:d=1",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=48000:cl=stereo",
            "-t",
            "1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-y",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def test_output_inspection_and_contact_sheet_with_real_ffmpeg(tmp_path: Path) -> None:
    _require_ffmpeg()
    media = tmp_path / "fixture.mp4"
    sheet = tmp_path / "fixture_contact_sheet.png"
    _make_fixture(media)

    document = asyncio.run(inspect_output(media))
    assert document["machine_valid"] is True
    assert document["media"]["video"]["width"] == 320
    assert document["media"]["video"]["height"] == 180
    assert document["media"]["audio"]["sample_rate"] == 48000

    review = asyncio.run(
        create_contact_sheet(
            media,
            sheet,
            duration=float(document["media"]["duration"]),
            samples=3,
        )
    )
    assert review["status"] == "pending_review"
    assert review["contact_sheet"] == str(sheet)
    assert len(review["timestamps"]) == 3
    assert sheet.is_file()
    with Image.open(sheet) as image:
        assert image.width > 0
        assert image.height > 0


def test_cli_inspect_json_with_real_ffmpeg(tmp_path: Path) -> None:
    _require_ffmpeg()
    media = tmp_path / "fixture.mp4"
    sheet = tmp_path / "review.png"
    _make_fixture(media)

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "zundamotion",
            "inspect",
            str(media),
            "--contact-sheet",
            str(sheet),
            "--samples",
            "3",
            "--json",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    document = json.loads(proc.stdout)
    assert document["machine_valid"] is True
    assert document["visual_review"]["status"] == "pending_review"
    assert Path(document["visual_review"]["contact_sheet"]) == sheet
    assert sheet.is_file()
