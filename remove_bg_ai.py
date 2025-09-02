#!/usr/bin/env python3
"""
AI-based background removal for images in a folder using rembg.

Usage:
  python remove_bg_ai.py --input <in_dir> --output <out_dir> [--recursive]
                         [--model isnet-general-use|isnet-anime|u2net|u2netp|u2net_human_seg]

Notes:
  - Outputs are always saved as PNG with transparency.
  - Requires: pip install rembg Pillow
  - GPU: install onnxruntime-gpu to leverage CUDA (if available).
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Iterable, Optional

from PIL import Image
import onnxruntime as ort

try:
    from rembg import remove, new_session
except Exception as e:  # pragma: no cover - import guidance
    print("rembg is required. Install with: pip install rembg", file=sys.stderr)
    raise


SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}


def list_images(input_dir: str, recursive: bool) -> Iterable[str]:
    """Yield image file paths from *input_dir*.

    Args:
        input_dir: Directory to search for images.
        recursive: Whether to traverse subdirectories recursively.

    Yields:
        Paths to files with supported extensions.
    """
    if recursive:
        for root, _dirs, files in os.walk(input_dir):
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if ext in SUPPORTED_EXTS:
                    yield os.path.join(root, f)
    else:
        for f in os.listdir(input_dir):
            p = os.path.join(input_dir, f)
            if os.path.isfile(p) and os.path.splitext(f)[1].lower() in SUPPORTED_EXTS:
                yield p


def ensure_dir(path: str) -> None:
    """Create *path* if it does not already exist."""
    os.makedirs(path, exist_ok=True)


def compute_output_path(input_path: str, root_in: str, root_out: str) -> str:
    """Determine the output file path for an input image."""
    base_no_ext = os.path.splitext(os.path.basename(input_path))[0]
    rel_dir = os.path.relpath(os.path.dirname(input_path), root_in)
    if rel_dir == os.curdir:
        rel_dir = ""
    out_dir = os.path.join(root_out, rel_dir)
    ensure_dir(out_dir)
    return os.path.join(out_dir, base_no_ext + ".png")


def remove_bg_with_session(img: Image.Image, session) -> Image.Image:
    """Remove the background from *img* using a prepared *session*."""
    # rembg accepts bytes or PIL.Image, returns bytes or PIL.Image depending on input
    out = remove(img, session=session)
    # When input is PIL.Image, output is PIL.Image
    if isinstance(out, Image.Image):
        return out.convert("RGBA")
    # Fallback if bytes were returned for some reason
    from io import BytesIO

    return Image.open(BytesIO(out)).convert("RGBA")


def process_image(path: str, session, in_root: str, out_root: str, overwrite: bool) -> tuple[bool, str]:
    """Apply background removal to a single image and save the result."""
    try:
        with Image.open(path) as im:
            # Convert to RGBA early for consistency
            if im.mode != "RGBA":
                im = im.convert("RGBA")
            out_im = remove_bg_with_session(im, session)
            out_path = compute_output_path(path, in_root, out_root)
            if (not overwrite) and os.path.exists(out_path):
                return False, f"Skip (exists): {out_path}"
            out_im.save(out_path, format="PNG")
            return True, out_path
    except Exception as e:
        return False, f"Error processing {path}: {e}"


def main(argv: Optional[list[str]] = None) -> int:
    """Command-line interface for batch background removal."""
    parser = argparse.ArgumentParser(
        description="Remove backgrounds with AI (rembg) and save as PNGs",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--input", "-i", required=True, help="Input directory")
    parser.add_argument("--output", "-o", required=True, help="Output directory")
    parser.add_argument("--recursive", action="store_true", help="Process subdirectories")
    parser.add_argument("--no-overwrite", action="store_true", help="Do not overwrite outputs")
    parser.add_argument("--show-providers", action="store_true", help="Show ONNX Runtime providers info")
    force_group = parser.add_mutually_exclusive_group()
    force_group.add_argument("--force-cpu", action="store_true", help="Force CPUExecutionProvider")
    force_group.add_argument("--force-gpu", action="store_true", help="Force CUDAExecutionProvider (falls back to CPU if unavailable)")
    parser.add_argument(
        "--model",
        default="isnet-general-use",
        help=(
            "rembg model name (e.g., isnet-general-use|isnet-anime|u2net|u2netp|u2net_human_seg)"
        ),
    )

    args = parser.parse_args(argv)

    in_dir = os.path.abspath(args.input)
    out_dir = os.path.abspath(args.output)
    recursive = bool(args.recursive)
    overwrite = not bool(args.no_overwrite)
    model_name = str(args.model)
    show_providers = bool(args.show_providers)
    force_cpu = bool(args.force_cpu)
    force_gpu = bool(args.force_gpu)

    if not os.path.isdir(in_dir):
        print(f"Input directory not found: {in_dir}", file=sys.stderr)
        return 2

    ensure_dir(out_dir)

    available_providers = list(ort.get_available_providers())

    print(
        "Settings: input=",
        in_dir,
        " output=",
        out_dir,
        " model=",
        model_name,
        " recursive=",
        recursive,
    )
    print("ONNX Runtime available providers:", available_providers)

    # Decide providers order
    providers = None
    if force_cpu:
        providers = ["CPUExecutionProvider"]
    elif force_gpu:
        if "CUDAExecutionProvider" in available_providers:
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        else:
            print(
                "Warning: CUDAExecutionProvider not available; using CPUExecutionProvider",
                file=sys.stderr,
            )
            providers = ["CPUExecutionProvider"]

    # Load model once and reuse for all images
    try:
        session = new_session(model_name, providers=providers)
    except Exception as e:
        print(f"Failed to load rembg model '{model_name}': {e}", file=sys.stderr)
        return 2

    # Show providers information
    try:
        # BaseSession exposes the selected providers list
        selected = getattr(session, "providers", None)
        inner = getattr(session, "inner_session", None)
        inner_providers = None
        if inner is not None and hasattr(inner, "get_providers"):
            inner_providers = list(inner.get_providers())

        print("Session providers (requested):", selected)
        if inner_providers is not None:
            print("Session providers (active in ORT):", inner_providers)
    except Exception:
        pass

    if show_providers:
        # If only info was requested, exit successfully
        print("Provider info displayed. Proceeding with processing...")

    total = 0
    ok = 0
    for in_path in list_images(in_dir, recursive):
        total += 1
        success, msg = process_image(in_path, session, in_dir, out_dir, overwrite)
        if success:
            ok += 1
            print(f"OK: {msg}")
        else:
            print(msg, file=sys.stderr)

    print(f"Done. {ok}/{total} images processed.")
    return 0 if ok == total and total > 0 else (1 if ok > 0 else 2)


if __name__ == "__main__":
    raise SystemExit(main())
