#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
集中線（スピードライン）PNGを生成するユーティリティ。

概要:
- 透過背景(RGBA)に白い放射状の線を描画します。
- デフォルトは 1920x1080、線本数 180、本数や太さ、内外の余白など可変。

使い方:
    python scripts/gen_speedlines.py --width 1920 --height 1080 \
        --lines 180 --min_thickness 2 --max_thickness 6 \
        --inner_radius 60 --outer_margin 8 \
        --output assets/overlay/speedlines.png

パラメータは省略可能で、上記が既定値です。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

from PIL import Image, ImageDraw


@dataclass
class SpeedLinesConfig:
    width: int = 1920
    height: int = 1080
    lines: int = 180
    min_thickness: int = 2
    max_thickness: int = 6
    inner_radius: int = 60
    outer_margin: int = 8
    color: Tuple[int, int, int, int] = (255, 255, 255, 255)  # white
    center_bias_y: float = 0.0  # 画面中心からの縦方向バイアス（比率, -0.5〜0.5程度）


def _draw_speedlines(img: Image.Image, cfg: SpeedLinesConfig) -> None:
    draw = ImageDraw.Draw(img)
    cx = cfg.width / 2.0
    cy = cfg.height / 2.0 + cfg.center_bias_y * cfg.height
    max_r = math.hypot(max(cx, cfg.width - cx), max(cy, cfg.height - cy))
    outer_r = max_r - cfg.outer_margin

    for i in range(cfg.lines):
        t = i / float(cfg.lines)
        # 太さを周方向でゆるく変化（見栄え用）
        thickness = int(
            cfg.min_thickness + (cfg.max_thickness - cfg.min_thickness) * (0.5 + 0.5 * math.sin(2 * math.pi * t))
        )
        thickness = max(cfg.min_thickness, min(cfg.max_thickness, thickness))

        theta = 2 * math.pi * t
        # 始点は内側の半径から
        x0 = cx + cfg.inner_radius * math.cos(theta)
        y0 = cy + cfg.inner_radius * math.sin(theta)
        # 終点は外側（画面外）へ伸ばす
        x1 = cx + outer_r * math.cos(theta)
        y1 = cy + outer_r * math.sin(theta)

        draw.line((x0, y0, x1, y1), fill=cfg.color, width=thickness)


def generate_speedlines(output: Path, cfg: SpeedLinesConfig) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGBA", (cfg.width, cfg.height), (0, 0, 0, 0))
    _draw_speedlines(img, cfg)
    img.save(output)
    return output


def main() -> None:
    import argparse

    p = argparse.ArgumentParser(description="Generate transparent speedlines PNG")
    p.add_argument("--width", type=int, default=1920)
    p.add_argument("--height", type=int, default=1080)
    p.add_argument("--lines", type=int, default=180)
    p.add_argument("--min_thickness", type=int, default=2)
    p.add_argument("--max_thickness", type=int, default=6)
    p.add_argument("--inner_radius", type=int, default=60)
    p.add_argument("--outer_margin", type=int, default=8)
    p.add_argument("--center_bias_y", type=float, default=0.0)
    p.add_argument(
        "--output",
        type=Path,
        default=Path("assets/overlay/speedlines.png"),
        help="Output PNG path",
    )
    args = p.parse_args()

    cfg = SpeedLinesConfig(
        width=args.width,
        height=args.height,
        lines=args.lines,
        min_thickness=args.min_thickness,
        max_thickness=args.max_thickness,
        inner_radius=args.inner_radius,
        outer_margin=args.outer_margin,
        center_bias_y=args.center_bias_y,
    )
    out_path = generate_speedlines(args.output, cfg)
    print(f"Generated: {out_path}")


if __name__ == "__main__":
    main()

