#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

try:
    import cairosvg
except ImportError as exc:
    raise SystemExit(
        "CairoSVG が必要です: python -m pip install cairosvg"
    ) from exc

MOUTH_SEQUENCE = [
    "mouth-closed",
    "mouth-a",
    "mouth-i",
    "mouth-u",
    "mouth-e",
    "mouth-o",
    "mouth-small",
    "mouth-a",
    "mouth-closed",
]
MOUTH_IDS = sorted(set(MOUTH_SEQUENCE))


def set_group_attrs(svg: str, group_id: str, attrs: dict[str, str]) -> str:
    pattern = re.compile(rf'<g\b[^>]*\bid="{re.escape(group_id)}"[^>]*>')
    match = pattern.search(svg)
    if not match:
        return svg

    tag = match.group(0)
    closing = "/>" if tag.endswith("/>") else ">"
    core = tag[:-2] if closing == "/>" else tag[:-1]
    for key, value in attrs.items():
        attr_pattern = rf'\s{re.escape(key)}="[^"]*"'
        if re.search(attr_pattern, core):
            core = re.sub(attr_pattern, f' {key}="{value}"', core)
        else:
            core += f' {key}="{value}"'
    replacement = core + closing
    return svg[: match.start()] + replacement + svg[match.end() :]


def strip_style_animations(svg: str) -> str:
    return re.sub(r"<style\b[^>]*>.*?</style>", "", svg, flags=re.S)


def animate(svg: str, time_sec: float) -> str:
    body_angle = 0.25 * math.sin(2 * math.pi * time_sec / 4.8)
    svg = set_group_attrs(
        svg,
        "character",
        {
            "transform": f"rotate({body_angle:.3f})",
            "transform-origin": "center center",
        },
    )
    svg = set_group_attrs(
        svg,
        "hair-left",
        {"transform": f"rotate({1.8 * math.sin(2 * math.pi * time_sec / 3.2):.3f})"},
    )
    svg = set_group_attrs(
        svg,
        "hair-right",
        {
            "transform": (
                f"rotate({-1.6 * math.sin(2 * math.pi * time_sec / 3.2 + 0.15):.3f})"
            )
        },
    )
    svg = set_group_attrs(
        svg,
        "hair-front",
        {
            "transform": (
                f"translate(0 {0.55 * math.sin(2 * math.pi * time_sec / 2.7 + 0.5):.3f})"
            )
        },
    )
    svg = set_group_attrs(
        svg,
        "ahoge",
        {"transform": f"rotate({3.2 * math.sin(2 * math.pi * time_sec / 2.1):.3f})"},
    )

    blink = any(abs(time_sec - blink_at) < 0.085 for blink_at in (1.25, 3.55))
    svg = set_group_attrs(svg, "eyes-open", {"opacity": "0" if blink else "1"})
    svg = set_group_attrs(svg, "eyes-closed", {"opacity": "1" if blink else "0"})

    active_mouth = MOUTH_SEQUENCE[int(time_sec / 0.24) % len(MOUTH_SEQUENCE)]
    for mouth_id in MOUTH_IDS:
        svg = set_group_attrs(
            svg,
            mouth_id,
            {"opacity": "1" if mouth_id == active_mouth else "0"},
        )
    return svg


def render(
    svg_path: Path,
    out_dir: Path,
    duration: float,
    fps: int,
    width: int,
) -> tuple[Path, Path]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SystemExit("ffmpeg が PATH にありません。")

    source = strip_style_animations(svg_path.read_text(encoding="utf-8"))
    out_dir.mkdir(parents=True, exist_ok=True)
    png_path = out_dir / f"{svg_path.stem}.png"
    mp4_path = out_dir / f"{svg_path.stem}_preview.mp4"

    cairosvg.svg2png(
        bytestring=source.encode("utf-8"),
        write_to=str(png_path),
        output_width=width,
    )

    with tempfile.TemporaryDirectory(prefix="zundamotion-rig-") as tmp:
        frame_dir = Path(tmp)
        frame_count = max(1, round(duration * fps))
        for index in range(frame_count):
            frame_svg = animate(source, index / fps)
            cairosvg.svg2png(
                bytestring=frame_svg.encode("utf-8"),
                write_to=str(frame_dir / f"frame_{index:04d}.png"),
                output_width=width,
            )

        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-framerate",
                str(fps),
                "-i",
                str(frame_dir / "frame_%04d.png"),
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-crf",
                "18",
                "-movflags",
                "+faststart",
                str(mp4_path),
            ],
            check=True,
        )

    return png_path, mp4_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Render SVG character rig QA preview")
    parser.add_argument("svg", type=Path)
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=Path("output/character_rig"),
    )
    parser.add_argument("--duration", type=float, default=5.0)
    parser.add_argument("--fps", type=int, default=20)
    parser.add_argument("--width", type=int, default=768)
    args = parser.parse_args()

    if args.duration <= 0 or args.fps <= 0 or args.width <= 0:
        parser.error("duration / fps / width は正の値にしてください。")

    png_path, mp4_path = render(
        args.svg,
        args.output_dir,
        args.duration,
        args.fps,
        args.width,
    )
    print(png_path)
    print(mp4_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
