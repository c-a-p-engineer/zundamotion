from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

import pytest
from PIL import Image

from zundamotion.components.video.character_rig_materializer import (
    CharacterRigMaterializer,
)


pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None
    or shutil.which("ffprobe") is None
    or importlib.util.find_spec("cairosvg") is None,
    reason="ffmpeg, ffprobe, and CairoSVG are required",
)


RIG_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="100">
<g id="character">
  <g id="body"><rect x="20" y="30" width="60" height="60" fill="#00ff00"/></g>
  <g id="head">
    <g id="face">
      <g id="face-base"><circle cx="50" cy="25" r="20" fill="#ffffff"/></g>
      <g id="eyes">
        <g id="eyes-open"><rect x="35" y="20" width="10" height="5" fill="#0000ff"/></g>
        <g id="eyes-closed"><rect x="35" y="20" width="10" height="5" fill="#ff0000"/></g>
      </g>
      <g id="mouth">
        <g id="mouth-closed"><rect x="45" y="32" width="10" height="2" fill="#000000"/></g>
        <g id="mouth-small"><rect x="46" y="31" width="8" height="4" fill="#ffff00"/></g>
        <g id="mouth-a"><rect x="45" y="29" width="10" height="8" fill="#ff00ff"/></g>
      </g>
    </g>
  </g>
</g>
</svg>"""


class _Cache:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.memo: dict[str, Path] = {}

    async def get_or_create(self, *, key_data, file_name, extension, creator_func):
        key = json.dumps(key_data, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        path = self.memo.get(digest)
        if path is not None and path.exists():
            return path
        path = self.root / f"{file_name}_{digest[:16]}.{extension}"
        result = Path(await creator_func(path))
        self.memo[digest] = result
        return result


def _frame(video: Path, at: float, output: Path) -> Image.Image:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-ss",
            f"{at:.3f}",
            "-i",
            str(video),
            "-frames:v",
            "1",
            str(output),
        ],
        check=True,
        capture_output=True,
    )
    return Image.open(output).convert("RGB")


def _duration(video: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            str(video),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


def test_materialized_svg_rig_face_state_renders_on_existing_ffmpeg_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    async def _materialize():
        monkeypatch.chdir(tmp_path)
        rig = tmp_path / "assets" / "characters" / "hero" / "character.svg"
        rig.parent.mkdir(parents=True)
        rig.write_text(RIG_SVG, encoding="utf-8")
        cache = _Cache(tmp_path / "cache")
        cache.root.mkdir(parents=True)
        return await CharacterRigMaterializer(cache).materialize(
            {
                "path": "assets/characters/hero/character.svg",
                "raster_width": 100,
            }
        )

    assets = asyncio.run(_materialize())
    output = tmp_path / "rig.mp4"

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=140x120:r=30:d=1.0",
            "-loop",
            "1",
            "-framerate",
            "30",
            "-i",
            str(assets.base),
            "-loop",
            "1",
            "-framerate",
            "30",
            "-i",
            str(assets.eyes["close"]),
            "-filter_complex",
            (
                "[0:v][1:v]overlay=x=10:y=10[base];"
                "[base][2:v]overlay=x=10:y=10:"
                "enable='between(t,0.4,0.6)',format=yuv420p[v]"
            ),
            "-map",
            "[v]",
            "-t",
            "1.0",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(output),
        ],
        check=True,
        capture_output=True,
    )

    before = _frame(output, 0.20, tmp_path / "before.png")
    closed = _frame(output, 0.50, tmp_path / "closed.png")
    bx, by = 10 + 39, 10 + 22

    before_r, _before_g, before_b = before.getpixel((bx, by))
    closed_r, _closed_g, closed_b = closed.getpixel((bx, by))

    assert before_b > before_r + 60
    assert closed_r > closed_b + 60
    # Body remains registered while the face state changes.
    _r, body_g, _b = closed.getpixel((10 + 30, 10 + 70))
    assert body_g > 180
    assert _duration(output) == pytest.approx(1.0, abs=0.08)
