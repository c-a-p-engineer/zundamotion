from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from zundamotion.components.video.clip.movement import (
    build_dynamic_scale_filter,
    build_move_expressions,
    build_scale_expression,
)


pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg and ffprobe are required",
)


def _extract_frame(video: Path, at: float, output: Path) -> Image.Image:
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


def _green_bounds(image: Image.Image) -> tuple[int, int, int, int]:
    pixels = image.load()
    xs: list[int] = []
    ys: list[int] = []
    for y in range(image.height):
        for x in range(image.width):
            r, g, b = pixels[x, y]
            if g > 160 and g > r * 1.5 and g > b * 1.5:
                xs.append(x)
                ys.append(y)
    assert xs and ys
    return min(xs), min(ys), max(xs) + 1, max(ys) + 1


def _probe_duration(video: Path) -> float:
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


def test_multi_keyframe_motion_renders_position_scale_and_keeps_duration(
    tmp_path: Path,
) -> None:
    character = tmp_path / "character.png"
    Image.new("RGBA", (20, 20), (0, 255, 0, 255)).save(character)

    move = {
        "from": {"x": 20, "y": 50, "scale": 1.0},
        "duration": 1.2,
        "easing": "linear",
        "keyframes": [
            {"at": 0.4, "x": 100, "easing": "ease_out"},
            {"at": 0.5, "scale": 2.0, "easing": "ease_in_out"},
            {"at": 0.8, "x": 180, "easing": "ease_in"},
        ],
    }
    x_expr, y_expr, position_dynamic = build_move_expressions(
        move_config=move,
        anchor="top_left",
        from_position=None,
        to_position={"x": 260, "y": 50},
        to_x_expr="260",
        to_y_expr="50",
    )
    scale_expr, scale_dynamic = build_scale_expression(
        move_config=move,
        to_scale=1.0,
    )
    scale_filter = build_dynamic_scale_filter(
        scale_expr=scale_expr,
        move_config=move,
        to_scale=1.0,
        source_width=20,
        source_height=20,
        anchor="top_left",
        scale_flags="bicubic",
    )

    assert position_dynamic is True
    assert scale_dynamic is True

    escaped_x = x_expr.replace(",", "\\,")
    escaped_y = y_expr.replace(",", "\\,")
    output = tmp_path / "motion.mp4"
    filter_complex = (
        f"[1:v]{scale_filter}[char];"
        f"[0:v][char]overlay=x={escaped_x}:y={escaped_y}:shortest=1,"
        "format=yuv420p[v]"
    )
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=320x180:r=30:d=1.2",
            "-loop",
            "1",
            "-framerate",
            "30",
            "-i",
            str(character),
            "-filter_complex",
            filter_complex,
            "-map",
            "[v]",
            "-t",
            "1.2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(output),
        ],
        check=True,
        capture_output=True,
    )

    start = _green_bounds(_extract_frame(output, 0.05, tmp_path / "start.png"))
    peak = _green_bounds(_extract_frame(output, 0.50, tmp_path / "peak.png"))
    end = _green_bounds(_extract_frame(output, 1.15, tmp_path / "end.png"))

    start_width = start[2] - start[0]
    peak_width = peak[2] - peak[0]
    end_width = end[2] - end[0]

    assert 18 <= start_width <= 23
    assert peak_width >= 36
    assert 18 <= end_width <= 24
    assert start[0] < peak[0] < end[0]
    assert abs(start[1] - 50) <= 2
    assert abs(peak[1] - 50) <= 2
    assert abs(end[1] - 50) <= 2
    assert _probe_duration(output) == pytest.approx(1.2, abs=0.08)
