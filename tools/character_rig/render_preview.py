#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

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
EYE_IDS = ["eyes-open", "eyes-half", "eyes-closed"]
V2_JOINT_IDS = {
    "upper-arm-left",
    "forearm-left",
    "hand-left",
    "upper-arm-right",
    "forearm-right",
    "hand-right",
    "thigh-left",
    "calf-left",
    "foot-left",
    "thigh-right",
    "calf-right",
    "foot-right",
}


@dataclass(frozen=True)
class RigMetadata:
    ids: frozenset[str]
    pivots: dict[str, tuple[float, float]]
    parent_by_id: dict[str, str | None]
    viewbox_center: tuple[float, float]

    @property
    def has_v2_limbs(self) -> bool:
        return bool(self.ids & V2_JOINT_IDS)


def load_cairosvg():
    try:
        import cairosvg
    except ImportError as exc:
        raise SystemExit(
            "CairoSVG が必要です: python -m pip install cairosvg"
        ) from exc
    return cairosvg


def strip_style_animations(svg: str) -> str:
    return re.sub(r"<style\b[^>]*>.*?</style>", "", svg, flags=re.S)


def set_group_attrs(svg: str, group_id: str, attrs: dict[str, str]) -> str:
    pattern = re.compile(rf"<g\b[^>]*\bid=['\"]{re.escape(group_id)}['\"][^>]*>")
    match = pattern.search(svg)
    if not match:
        return svg

    tag = match.group(0)
    closing = "/>" if tag.endswith("/>") else ">"
    core = tag[:-2] if closing == "/>" else tag[:-1]
    for key, value in attrs.items():
        attr_pattern = rf"\s{re.escape(key)}=['\"][^'\"]*['\"]"
        if re.search(attr_pattern, core):
            core = re.sub(attr_pattern, f' {key}="{value}"', core)
        else:
            core += f' {key}="{value}"'
    return svg[: match.start()] + core + closing + svg[match.end() :]


def parse_viewbox_center(root: ET.Element) -> tuple[float, float]:
    raw = root.get("viewBox", "0 0 1 1").replace(",", " ").split()
    if len(raw) != 4:
        return (0.5, 0.5)
    try:
        x, y, width, height = (float(value) for value in raw)
    except ValueError:
        return (0.5, 0.5)
    return (x + width / 2, y + height / 2)


def parse_rig_metadata(svg: str) -> RigMetadata:
    root = ET.fromstring(svg)
    parent_lookup = {child: parent for parent in root.iter() for child in parent}
    ids: set[str] = set()
    pivots: dict[str, tuple[float, float]] = {}
    parent_by_id: dict[str, str | None] = {}

    for elem in root.iter():
        elem_id = elem.get("id")
        if not elem_id:
            continue
        ids.add(elem_id)
        pivot_x = elem.get("data-pivot-x")
        pivot_y = elem.get("data-pivot-y")
        if pivot_x is not None and pivot_y is not None:
            try:
                pivots[elem_id] = (float(pivot_x), float(pivot_y))
            except ValueError:
                pass
        parent = parent_lookup.get(elem)
        parent_by_id[elem_id] = parent.get("id") if parent is not None else None

    return RigMetadata(
        ids=frozenset(ids),
        pivots=pivots,
        parent_by_id=parent_by_id,
        viewbox_center=parse_viewbox_center(root),
    )


def rotate_transform(metadata: RigMetadata, group_id: str, angle: float) -> str:
    pivot = metadata.pivots.get(group_id)
    if pivot is None:
        return f"rotate({angle:.3f})"
    return f"rotate({angle:.3f} {pivot[0]:.3f} {pivot[1]:.3f})"


def set_rotation(svg: str, metadata: RigMetadata, group_id: str, angle: float) -> str:
    if group_id not in metadata.ids:
        return svg
    return set_group_attrs(
        svg, group_id, {"transform": rotate_transform(metadata, group_id, angle)}
    )


def set_rotation_chain(
    svg: str,
    metadata: RigMetadata,
    group_id: str,
    rotations: list[tuple[str, float]],
) -> str:
    if group_id not in metadata.ids:
        return svg
    transforms = [
        rotate_transform(metadata, source_id, angle)
        for source_id, angle in rotations
    ]
    return set_group_attrs(svg, group_id, {"transform": " ".join(transforms)})


def is_descendant(metadata: RigMetadata, child_id: str, ancestor_id: str) -> bool:
    current = metadata.parent_by_id.get(child_id)
    while current:
        if current == ancestor_id:
            return True
        current = metadata.parent_by_id.get(current)
    return False


def blink_state(time_sec: float) -> str:
    for blink_at in (1.25, 3.55):
        distance = abs(time_sec - blink_at)
        if distance < 0.04:
            return "closed"
        if distance < 0.085:
            return "half"
    return "open"


def apply_face_states(svg: str, time_sec: float, metadata: RigMetadata) -> str:
    eye_state = blink_state(time_sec)
    for eye_id in EYE_IDS:
        if eye_id in metadata.ids:
            svg = set_group_attrs(
                svg,
                eye_id,
                {"opacity": "1" if eye_id == f"eyes-{eye_state}" else "0"},
            )

    active_mouth = MOUTH_SEQUENCE[int(time_sec / 0.24) % len(MOUTH_SEQUENCE)]
    for mouth_id in MOUTH_IDS:
        if mouth_id in metadata.ids:
            svg = set_group_attrs(
                svg,
                mouth_id,
                {"opacity": "1" if mouth_id == active_mouth else "0"},
            )
    return svg


def apply_hair_motion(svg: str, time_sec: float, metadata: RigMetadata) -> str:
    motions = {
        "hair-left": 1.8 * math.sin(2 * math.pi * time_sec / 3.2),
        "hair-right": -1.6 * math.sin(2 * math.pi * time_sec / 3.2 + 0.15),
        "ahoge": 3.2 * math.sin(2 * math.pi * time_sec / 2.1),
    }
    for group_id, angle in motions.items():
        svg = set_rotation(svg, metadata, group_id, angle)
    if "hair-front" in metadata.ids:
        offset = 0.55 * math.sin(2 * math.pi * time_sec / 2.7 + 0.5)
        svg = set_group_attrs(
            svg, "hair-front", {"transform": f"translate(0 {offset:.3f})"}
        )
    return svg


def apply_joint_chain(
    svg: str,
    metadata: RigMetadata,
    chain: tuple[str, str, str],
    angles: tuple[float, float, float],
) -> str:
    root_id, mid_id, end_id = chain
    root_angle, mid_angle, end_angle = angles
    svg = set_rotation(svg, metadata, root_id, root_angle)

    mid_rotations = [(mid_id, mid_angle)]
    if not is_descendant(metadata, mid_id, root_id):
        mid_rotations.insert(0, (root_id, root_angle))
    svg = set_rotation_chain(svg, metadata, mid_id, mid_rotations)

    end_rotations = [(end_id, end_angle)]
    if not is_descendant(metadata, end_id, mid_id):
        end_rotations.insert(0, (mid_id, mid_angle))
    if not is_descendant(metadata, end_id, root_id):
        end_rotations.insert(0, (root_id, root_angle))
    return set_rotation_chain(svg, metadata, end_id, end_rotations)


def apply_limb_motion(svg: str, time_sec: float, metadata: RigMetadata) -> str:
    if not metadata.has_v2_limbs:
        left = 2.0 * math.sin(2 * math.pi * time_sec / 2.8)
        right = -2.0 * math.sin(2 * math.pi * time_sec / 2.8 + 0.2)
        svg = set_rotation(svg, metadata, "arm-left", left)
        return set_rotation(svg, metadata, "arm-right", right)

    arm_wave = math.sin(2 * math.pi * time_sec / 2.8)
    leg_wave = math.sin(2 * math.pi * time_sec / 3.4 + 0.5)
    chains = [
        (
            ("upper-arm-left", "forearm-left", "hand-left"),
            (4.0 * arm_wave, 6.0 * arm_wave, 3.0 * arm_wave),
        ),
        (
            ("upper-arm-right", "forearm-right", "hand-right"),
            (-4.0 * arm_wave, -6.0 * arm_wave, -3.0 * arm_wave),
        ),
        (
            ("thigh-left", "calf-left", "foot-left"),
            (2.2 * leg_wave, 2.8 * leg_wave, 2.0 * leg_wave),
        ),
        (
            ("thigh-right", "calf-right", "foot-right"),
            (-2.2 * leg_wave, -2.8 * leg_wave, -2.0 * leg_wave),
        ),
    ]
    for chain, angles in chains:
        svg = apply_joint_chain(svg, metadata, chain, angles)
    return svg


def animate(svg: str, time_sec: float, metadata: RigMetadata | None = None) -> str:
    metadata = metadata or parse_rig_metadata(svg)
    body_angle = 0.25 * math.sin(2 * math.pi * time_sec / 4.8)
    body_dx = 0.7 * math.sin(2 * math.pi * time_sec / 3.8)
    body_dy = 0.9 * math.sin(2 * math.pi * time_sec / 2.9 + 0.3)
    center_x, center_y = metadata.viewbox_center
    svg = set_group_attrs(
        svg,
        "character",
        {
            "transform": (
                f"translate({body_dx:.3f} {body_dy:.3f}) "
                f"rotate({body_angle:.3f} {center_x:.3f} {center_y:.3f})"
            )
        },
    )
    svg = apply_face_states(svg, time_sec, metadata)
    svg = apply_hair_motion(svg, time_sec, metadata)
    return apply_limb_motion(svg, time_sec, metadata)


def build_ffmpeg_command(
    ffmpeg: str, frame_dir: Path, fps: int, output: Path
) -> list[str]:
    return [
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
        str(output),
    ]


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
    cairosvg = load_cairosvg()

    source = strip_style_animations(svg_path.read_text(encoding="utf-8"))
    metadata = parse_rig_metadata(source)
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
            frame_svg = animate(source, index / fps, metadata)
            cairosvg.svg2png(
                bytestring=frame_svg.encode("utf-8"),
                write_to=str(frame_dir / f"frame_{index:04d}.png"),
                output_width=width,
            )
        subprocess.run(
            build_ffmpeg_command(ffmpeg, frame_dir, fps, mp4_path), check=True
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
