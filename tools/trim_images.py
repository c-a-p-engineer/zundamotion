#!/usr/bin/env python3
"""フォルダ配下の画像を自動トリムして上書き保存するツール。

使い方:
  python tools/trim_images.py <target_dir> [--tolerance 10]
                                      [--alpha-threshold 8] [--margin 1]

指定ディレクトリ以下の画像を再帰的に探索し、余白を自動トリムします。
トリム結果は元ファイルへ上書き保存されます。
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Sequence

from PIL import Image, ImageChops

SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}


@dataclass
class TrimStats:
    processed: int = 0
    trimmed: int = 0
    skipped: int = 0
    errors: int = 0


def iter_images(root: Path) -> Iterable[Path]:
    """指定ディレクトリ配下の画像ファイルを列挙する。"""
    yield from (
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTS
    )


def _apply_tolerance(mask: Image.Image, tolerance: int) -> Image.Image:
    """差分マスクにしきい値を適用し、不要な微小差分を除去する。"""
    if mask.mode != "L":
        mask = mask.convert("L")
    if tolerance <= 0:
        return mask
    return mask.point(lambda p: 255 if p > tolerance else 0)


def _unique_sorted(values: Sequence[int]) -> list[int]:
    """整数の重複を除き昇順にしたリストを得る。"""
    seen: set[int] = set()
    ordered: list[int] = []
    for v in values:
        v = max(0, min(255, int(v)))
        if v not in seen:
            seen.add(v)
            ordered.append(v)
    return ordered


def _alpha_candidates(base: int) -> list[int]:
    return _unique_sorted([base, 0, 1, 2, 3, 4, 5, 8, 10, 16, 24, 32, 48, 64, 96, 128])


def _tolerance_candidates(base: int) -> list[int]:
    return _unique_sorted([base, 0, 1, 3, 5, 8, 10, 15, 20, 30, 40, 60, 80, 100, 128])


def compute_trim_box(
    img: Image.Image, tolerance: int, alpha_threshold: int
) -> Optional[tuple[int, int, int, int]]:
    """画像の有効部分を囲うバウンディングボックスを算出する。"""
    rgba = img.convert("RGBA")
    width, height = rgba.size
    full_box = (0, 0, width, height)

    alpha = rgba.getchannel("A")
    alpha_extrema = alpha.getextrema()
    if alpha_extrema is not None:
        alpha_min, alpha_max = alpha_extrema
    else:
        alpha_min = alpha_max = None

    if alpha_max == 0:
        return None  # 完全に透明な画像

    if alpha_min is not None and alpha_min < 255:
        for threshold in _alpha_candidates(alpha_threshold):
            if threshold >= 255:
                continue
            mask = alpha.point(lambda p, t=threshold: 255 if p > t else 0)
            box = mask.getbbox()
            if box and box != full_box:
                return box
            if box is None and threshold >= alpha_max:
                break

    rgb = rgba.convert("RGB")
    background_color = rgb.getpixel((0, 0))
    background = Image.new("RGB", rgb.size, background_color)
    diff = ImageChops.difference(rgb, background).convert("L")

    for tol in _tolerance_candidates(tolerance):
        mask = _apply_tolerance(diff, tol)
        box = mask.getbbox()
        if box and box != full_box:
            return box

    box = diff.getbbox()
    if box and box != full_box:
        return box
    return None


def expand_box(box: tuple[int, int, int, int], margin: int, width: int, height: int) -> tuple[int, int, int, int]:
    """マージンを考慮してバウンディングボックスを拡張する。"""
    if margin <= 0:
        return box
    left, upper, right, lower = box
    left = max(0, left - margin)
    upper = max(0, upper - margin)
    right = min(width, right + margin)
    lower = min(height, lower + margin)
    return left, upper, right, lower


def process_image(
    path: Path,
    tolerance: int,
    alpha_threshold: int,
    margin: int,
    dry_run: bool,
) -> tuple[bool, str]:
    """1枚の画像をトリムして保存する。"""
    try:
        with Image.open(path) as img:
            box = compute_trim_box(img, tolerance, alpha_threshold)
            if box is None:
                return False, f"Skip (blank or uniform): {path}"

            box = expand_box(box, margin, img.width, img.height)
            if box == (0, 0, img.width, img.height):
                return False, f"Skip (no trim needed): {path}"

            trimmed = img.crop(box)
            if dry_run:
                return True, f"Would trim {path.name}: {img.size} -> {trimmed.size}"

            save_kwargs = {}
            if img.format:
                save_kwargs["format"] = img.format
            if "exif" in img.info:
                save_kwargs["exif"] = img.info["exif"]
            if "icc_profile" in img.info:
                save_kwargs["icc_profile"] = img.info["icc_profile"]

            trimmed.save(path, **save_kwargs)
            return True, f"Trimmed {path.name}: {img.size} -> {trimmed.size}"
    except Exception as exc:  # pragma: no cover - runtime safety
        return False, f"Error {path}: {exc}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Auto-trim images under a directory and overwrite originals.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("target", help="Target directory containing images")
    parser.add_argument(
        "--tolerance",
        type=int,
        default=0,
        help="Ignore differences up to this value (0-255) when detecting borders",
    )
    parser.add_argument(
        "--margin",
        type=int,
        default=0,
        help="Pixels to keep around detected content after trimming",
    )
    parser.add_argument(
        "--alpha-threshold",
        type=int,
        default=0,
        help="Treat alpha values at or below this as transparent background",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be trimmed without rewriting files",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    target = Path(args.target).expanduser().resolve()
    tolerance = max(0, min(255, args.tolerance))
    alpha_threshold = max(0, min(255, args.alpha_threshold))
    margin = max(0, args.margin)

    if not target.is_dir():
        print(f"Target directory not found: {target}")
        return 2

    stats = TrimStats()
    for path in iter_images(target):
        stats.processed += 1
        success, message = process_image(
            path,
            tolerance,
            alpha_threshold,
            margin,
            args.dry_run,
        )
        if success:
            if args.dry_run:
                print(message)
            else:
                stats.trimmed += 1
                print(message)
        else:
            if message.startswith("Skip"):
                stats.skipped += 1
            else:
                stats.errors += 1
            print(message)

    print(
        f"Done. processed={stats.processed} trimmed={stats.trimmed} "
        f"skipped={stats.skipped} errors={stats.errors}"
    )
    if stats.errors > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
