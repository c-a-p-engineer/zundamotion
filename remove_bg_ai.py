#!/usr/bin/env python3
"""rembg を用いてフォルダ内の画像背景を一括除去するスクリプト。

使い方:
  python remove_bg_ai.py --input <in_dir> --output <out_dir> [--recursive]
                         [--model isnet-general-use|isnet-anime|u2net|u2netp|u2net_human_seg]

注意:
  - 出力は常に透過PNG。
  - 必須: pip install rembg Pillow
  - GPU 利用: onnxruntime-gpu をインストール（利用可能な場合）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable, Optional, Tuple

from PIL import Image
import onnxruntime as ort

try:
    from rembg import remove, new_session
except Exception as e:  # pragma: no cover - import guidance
    print("rembg is required. Install with: pip install rembg", file=sys.stderr)
    raise


SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}


def list_images(input_dir: Path, recursive: bool) -> Iterable[Path]:
    """指定ディレクトリ内の画像パスを列挙する。

    Args:
        input_dir: 探索対象ディレクトリ。
        recursive: サブディレクトリを再帰的に探索するか。

    Yields:
        サポート対象拡張子を持つファイルの :class:`Path` 。
    """
    if recursive:
        yield from (p for p in input_dir.rglob("*") if p.suffix.lower() in SUPPORTED_EXTS)
    else:
        yield from (
            p
            for p in input_dir.iterdir()
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS
        )


def ensure_dir(path: Path) -> None:
    """ディレクトリ *path* が存在しなければ作成する。"""
    path.mkdir(parents=True, exist_ok=True)


def compute_output_path(input_path: Path, root_in: Path, root_out: Path) -> Path:
    """入力画像に対応する出力先パスを算出する。"""
    rel_dir = input_path.parent.relative_to(root_in)
    out_dir = root_out / rel_dir
    ensure_dir(out_dir)
    return out_dir / f"{input_path.stem}.png"


def remove_bg_with_session(img: Image.Image, session) -> Image.Image:
    """学習済みセッションを用いて画像から背景を除去する。"""
    out = remove(img, session=session)
    if isinstance(out, Image.Image):
        return out.convert("RGBA")
    from io import BytesIO

    return Image.open(BytesIO(out)).convert("RGBA")


def process_image(
    path: Path,
    session,
    in_root: Path,
    out_root: Path,
    overwrite: bool,
) -> tuple[bool, str]:
    """単一の画像に背景除去を適用し結果を保存する。"""
    try:
        with Image.open(path) as im:
            if im.mode != "RGBA":
                im = im.convert("RGBA")
            out_im = remove_bg_with_session(im, session)
            out_path = compute_output_path(path, in_root, out_root)
            if not overwrite and out_path.exists():
                return False, f"Skip (exists): {out_path}"
            out_im.save(out_path, format="PNG")
            return True, str(out_path)
    except Exception as e:
        return False, f"Error processing {path}: {e}"


def parse_args(argv: Optional[list[str]]) -> argparse.Namespace:
    """コマンドライン引数を解析する。"""
    parser = argparse.ArgumentParser(
        description="Remove backgrounds with AI (rembg) and save as PNGs",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--input", "-i", required=True, help="Input directory")
    parser.add_argument("--output", "-o", required=True, help="Output directory")
    parser.add_argument("--recursive", action="store_true", help="Process subdirectories")
    parser.add_argument("--no-overwrite", action="store_true", help="Do not overwrite outputs")
    force_group = parser.add_mutually_exclusive_group()
    force_group.add_argument("--force-cpu", action="store_true", help="Force CPUExecutionProvider")
    force_group.add_argument(
        "--force-gpu",
        action="store_true",
        help="Force CUDAExecutionProvider (falls back to CPU if unavailable)",
    )
    parser.add_argument(
        "--model",
        default="isnet-general-use",
        help=(
            "rembg model name (e.g., isnet-general-use|isnet-anime|u2net|u2netp|u2net_human_seg)"
        ),
    )
    return parser.parse_args(argv)


def create_session(
    model_name: str, force_cpu: bool, force_gpu: bool
) -> Tuple[object, list[str]]:
    """rembg セッションを初期化し利用可能なプロバイダ情報を返す。"""
    available_providers = list(ort.get_available_providers())
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

    session = new_session(model_name, providers=providers)
    return session, available_providers


def remove_background_in_directory(
    in_dir: Path,
    out_dir: Path,
    session,
    recursive: bool,
    overwrite: bool,
) -> Tuple[int, int]:
    """ディレクトリ内の画像すべてから背景を除去する。"""
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
    return ok, total


def main(argv: Optional[list[str]] = None) -> int:
    """バッチ背景除去のCLIエントリポイント。"""
    args = parse_args(argv)

    in_dir = Path(args.input).resolve()
    out_dir = Path(args.output).resolve()
    recursive = bool(args.recursive)
    overwrite = not bool(args.no_overwrite)
    model_name = str(args.model)
    force_cpu = bool(args.force_cpu)
    force_gpu = bool(args.force_gpu)

    if not in_dir.is_dir():
        print(f"Input directory not found: {in_dir}", file=sys.stderr)
        return 2

    ensure_dir(out_dir)

    try:
        session, available_providers = create_session(model_name, force_cpu, force_gpu)
    except Exception as e:
        print(f"Failed to load rembg model '{model_name}': {e}", file=sys.stderr)
        return 2

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
    try:
        selected = getattr(session, "providers", None)
        inner = getattr(session, "inner_session", None)
        inner_providers = list(inner.get_providers()) if inner and hasattr(inner, "get_providers") else None
        print("Session providers (requested):", selected)
        if inner_providers is not None:
            print("Session providers (active in ORT):", inner_providers)
    except Exception:
        pass

    ok, total = remove_background_in_directory(
        in_dir, out_dir, session, recursive, overwrite
    )
    print(f"Done. {ok}/{total} images processed.")
    return 0 if ok == total and total > 0 else (1 if ok > 0 else 2)


if __name__ == "__main__":
    raise SystemExit(main())
