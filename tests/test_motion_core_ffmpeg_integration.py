from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from zundamotion.components.video.clip.camera import append_camera_transform
from zundamotion.components.video.clip.movement import (
    build_dynamic_scale_filter,
    build_move_expressions,
    build_scale_expression,
)
from zundamotion.components.video.clip.opacity import (
    build_alpha_multiplier_filter_parts,
    build_opacity_expression,
)
from zundamotion.components.video.clip.rotation import (
    build_rotate_expression,
    build_rotation_canvas,
    build_rotation_filter,
    correct_rotation_position,
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


def _red_center(image: Image.Image) -> tuple[float, float]:
    pixels = image.load()
    points: list[tuple[int, int]] = []
    for y in range(image.height):
        for x in range(image.width):
            r, g, b = pixels[x, y]
            if r > 150 and r > g * 1.4 and r > b * 1.4:
                points.append((x, y))
    assert points
    return (
        sum(point[0] for point in points) / len(points),
        sum(point[1] for point in points) / len(points),
    )


def _center_green(image: Image.Image) -> int:
    x = image.width // 2
    y = image.height // 2
    _r, g, _b = image.getpixel((x, y))
    return int(g)


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



def test_rotate_track_keeps_bottom_center_pivot_and_clockwise_direction(
    tmp_path: Path,
) -> None:
    character = tmp_path / "rotate-character.png"
    source = Image.new("RGBA", (20, 40), (0, 255, 0, 255))
    for y in range(0, 6):
        for x in range(7, 13):
            source.putpixel((x, y), (255, 0, 0, 255))
    source.save(character)

    move = {
        "from": {"rotate": 0},
        "duration": 1.0,
        "easing": "linear",
        "keyframes": [{"at": 0.5, "rotate": 45}],
    }
    rotate_expr, rotate_active = build_rotate_expression(
        move_config=move,
        to_rotate=90,
    )
    assert rotate_active is True
    scale_expr, _ = build_scale_expression(
        move_config=move,
        to_scale=1.0,
    )
    scale_filter = build_dynamic_scale_filter(
        scale_expr=scale_expr,
        move_config=move,
        to_scale=1.0,
        source_width=20,
        source_height=40,
        anchor="bottom_center",
        scale_flags="bicubic",
    )
    canvas = build_rotation_canvas(
        source_width=20,
        source_height=40,
        move_config=move,
        to_scale=1.0,
        anchor="bottom_center",
    )
    rotation_filter = build_rotation_filter(rotate_expr, canvas)
    x_expr = correct_rotation_position("(W-w)/2", canvas.correction_x)
    y_expr = correct_rotation_position("H-h-40", canvas.correction_y)
    escaped_x = x_expr.replace(",", "\\,")
    escaped_y = y_expr.replace(",", "\\,")

    output = tmp_path / "rotate.mp4"
    filter_complex = (
        f"[1:v]{scale_filter},{rotation_filter}[char];"
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
            "color=c=black:s=200x160:r=30:d=1.2",
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

    start_image = _extract_frame(output, 0.03, tmp_path / "rotate-start.png")
    end_image = _extract_frame(output, 1.08, tmp_path / "rotate-end.png")
    start_bounds = _green_bounds(start_image)
    end_bounds = _green_bounds(end_image)
    start_red = _red_center(start_image)
    end_red = _red_center(end_image)

    # Pivot world coordinate is (100, 120): source grows upward before rotation.
    assert abs((start_bounds[0] + start_bounds[2]) / 2.0 - 100) <= 3
    assert abs(start_bounds[3] - 120) <= 3

    # +90 degrees is clockwise in screen coordinates: top moves to the right.
    assert end_red[0] > 120
    assert abs(end_red[1] - 120) <= 5
    assert abs(end_bounds[0] - 100) <= 4
    assert abs((end_bounds[1] + end_bounds[3]) / 2.0 - 120) <= 4

    # Fixed canvas preserves the source instead of clipping it.
    assert (end_bounds[2] - end_bounds[0]) >= 36
    assert (end_bounds[3] - end_bounds[1]) >= 17
    assert _probe_duration(output) == pytest.approx(1.2, abs=0.08)



def test_opacity_multiplies_source_alpha_and_lifecycle_fade(
    tmp_path: Path,
) -> None:
    character = tmp_path / "opacity-character.png"
    Image.new("RGBA", (20, 20), (0, 255, 0, 128)).save(character)

    opacity_expr, active = build_opacity_expression(
        move_config=None,
        to_opacity=0.5,
    )
    assert active is True

    parts = [
        "[1:v]format=rgba,fade=t=in:st=0:d=1.0:alpha=1[pre]"
    ]
    parts.extend(
        build_alpha_multiplier_filter_parts(
            input_label="[pre]",
            output_label="[char]",
            opacity_expr=opacity_expr,
            prefix="opacity_ffmpeg",
        )
    )
    parts.append(
        "[0:v][char]overlay=x=(W-w)/2:y=(H-h)/2:shortest=1,"
        "format=yuv420p[v]"
    )

    output = tmp_path / "opacity.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=100x100:r=30:d=1.2",
            "-loop",
            "1",
            "-framerate",
            "30",
            "-i",
            str(character),
            "-filter_complex",
            ";".join(parts),
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

    mid = _extract_frame(output, 0.50, tmp_path / "opacity-mid.png")
    end = _extract_frame(output, 1.08, tmp_path / "opacity-end.png")
    mid_green = _center_green(mid)
    end_green = _center_green(end)

    # source alpha ~= 0.5, opacity=0.5, fade at t=0.5 ~= 0.5
    assert 20 <= mid_green <= 45
    # source alpha ~= 0.5, opacity=0.5, fade completed => ~= 0.25 effective alpha
    assert 50 <= end_green <= 80
    assert end_green > mid_green
    assert _probe_duration(output) == pytest.approx(1.2, abs=0.08)



def test_camera_moves_world_but_keeps_screen_overlay_fixed(
    tmp_path: Path,
) -> None:
    world = tmp_path / "camera-world.png"
    world_image = Image.new("RGBA", (120, 80), (0, 0, 0, 255))
    for y in range(30, 50):
        for x in range(10, 30):
            world_image.putpixel((x, y), (0, 255, 0, 255))
    world_image.save(world)

    marker = tmp_path / "screen-marker.png"
    Image.new("RGBA", (10, 10), (255, 0, 0, 255)).save(marker)

    camera = {
        "focus": {"x": 0.25, "y": 0.5},
        "zoom": 2.0,
        "move": {
            "from": {
                "focus": {"x": 0.5},
                "zoom": 1.0,
            },
            "duration": 1.0,
            "easing": "linear",
            "keyframes": [
                {"at": 0.5, "zoom": 1.5, "easing": "ease_out"},
            ],
        },
    }
    parts: list[str] = []
    camera_label = append_camera_transform(
        camera_config=camera,
        input_label="[0:v]",
        width=120,
        height=80,
        fps=30,
        parts=parts,
    )
    parts.append(
        f"{camera_label}[1:v]overlay=x=105:y=5:shortest=1,"
        "format=yuv420p[v]"
    )

    output = tmp_path / "camera.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-loop",
            "1",
            "-framerate",
            "30",
            "-i",
            str(world),
            "-loop",
            "1",
            "-framerate",
            "30",
            "-i",
            str(marker),
            "-filter_complex",
            ";".join(parts),
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

    start = _extract_frame(output, 0.05, tmp_path / "camera-start.png")
    end = _extract_frame(output, 1.08, tmp_path / "camera-end.png")
    start_green = _green_bounds(start)
    end_green = _green_bounds(end)
    start_red = _red_center(start)
    end_red = _red_center(end)

    start_green_width = start_green[2] - start_green[0]
    start_green_height = start_green[3] - start_green[1]
    end_green_width = end_green[2] - end_green[0]
    end_green_height = end_green[3] - end_green[1]

    assert 16 <= start_green_width <= 24
    assert 16 <= start_green_height <= 24
    assert end_green_width > start_green_width
    assert end_green_height >= 35
    assert end_green[0] < start_green[0]

    # Red marker is composed after camera and remains screen-fixed.
    assert start_red[0] == pytest.approx(end_red[0], abs=1.0)
    assert start_red[1] == pytest.approx(end_red[1], abs=1.0)
    assert start_red[0] >= 108
    assert start_red[1] <= 11

    assert _probe_duration(output) == pytest.approx(1.2, abs=0.08)
