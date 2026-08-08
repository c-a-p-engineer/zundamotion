"""Sidecar dimensions and alpha-bbox inspection for subtitle PNGs."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict

from PIL import Image

logger = logging.getLogger(__name__)


def _subtitle_meta_path(png_path: Path) -> Path:
    return png_path.with_suffix(".json")


def _read_subtitle_dimensions_meta(png_path: Path) -> Dict[str, int] | None:
    path = _subtitle_meta_path(png_path)
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as stream:
            meta = json.load(stream)
        width, height = int(meta.get("w", 0)), int(meta.get("h", 0))
        if width > 0 and height > 0:
            return {"w": width, "h": height}
    except Exception:
        return None
    return None


def _write_subtitle_dimensions_meta(png_path: Path, width: int, height: int) -> None:
    try:
        with _subtitle_meta_path(png_path).open("w", encoding="utf-8") as stream:
            json.dump({"w": int(width), "h": int(height)}, stream, ensure_ascii=False)
    except Exception:
        logger.debug("Failed to write subtitle PNG metadata: %s", png_path, exc_info=True)


def _inspect_subtitle_png_bbox(png_path: Path) -> Dict[str, int | bool | str]:
    with Image.open(png_path) as image:
        rgba = image.convert("RGBA")
        bbox = rgba.getchannel("A").getbbox()
        width, height = rgba.size
    if bbox is None:
        return {
            "width": width, "height": height,
            "transparent_left": width, "transparent_top": height,
            "transparent_right": width, "transparent_bottom": height,
            "full_canvas": False, "bbox_mode": "empty",
        }
    x0, y0, x1, y1 = bbox
    left, top = x0, y0
    right, bottom = max(0, width - x1), max(0, height - y1)
    mode = "tight" if any((left, top, right, bottom)) else "full"
    return {
        "width": width, "height": height,
        "transparent_left": left, "transparent_top": top,
        "transparent_right": right, "transparent_bottom": bottom,
        "full_canvas": mode == "full", "bbox_mode": mode,
    }
