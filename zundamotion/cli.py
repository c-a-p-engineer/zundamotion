"""Unified CLI dispatcher with backward-compatible render invocation."""

from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Iterator, Sequence

from . import __version__
from .authoring import (
    capabilities_document,
    compiled_document,
    load_canonical_config,
    validation_document,
)
from .main import cli as legacy_render_cli
from .output_qa import (
    create_contact_sheet,
    expected_from_config,
    expected_from_preset,
    inspect_output,
)
from .render_lock import (
    create_render_lock,
    load_render_lock,
    render_lock_json,
    verify_render_lock,
)

_MACHINE_COMMANDS = {
    "validate",
    "compile",
    "capabilities",
    "lock",
    "verify-lock",
    "inspect",
}


def _json_text(value: object, *, pretty: bool = False) -> str:
    if pretty:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ) + "\n"


@contextmanager
def _project_root(path: str | None) -> Iterator[None]:
    if not path:
        yield
        return

    root = Path(path).expanduser().resolve()
    if not root.exists():
        raise ValueError(f"--project-root does not exist: {root}")
    if not root.is_dir():
        raise ValueError(f"--project-root is not a directory: {root}")

    previous = Path.cwd()
    os.chdir(root)
    try:
        yield
    finally:
        os.chdir(previous)


def _common_script_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("script_path", help="Path to YAML/YML or Markdown input.")
    parser.add_argument(
        "--project-root",
        default=None,
        help="Base directory for resolving relative asset/include paths.",
    )


def _authoring_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="zundamotion",
        description=(
            "Generate video from YAML/Markdown, inspect canonical configuration, "
            "or verify a rendered deliverable."
        ),
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command")

    validate = subparsers.add_parser(
        "validate", help="Validate an input without starting FFmpeg or TTS."
    )
    _common_script_parser(validate)
    validate.add_argument(
        "--json", action="store_true", help="Emit the stable validation JSON contract."
    )

    compile_parser = subparsers.add_parser(
        "compile", help="Resolve and validate input into canonical compiled-config JSON."
    )
    _common_script_parser(compile_parser)
    compile_parser.add_argument(
        "-o", "--output", default=None, help="Output JSON path; stdout when omitted."
    )
    compile_parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")

    capabilities = subparsers.add_parser(
        "capabilities", help="List stable package capabilities without external runtimes."
    )
    capabilities.add_argument(
        "--json", action="store_true", help="Emit the stable capabilities JSON contract."
    )

    lock_parser = subparsers.add_parser(
        "lock", help="Create deterministic render provenance for a script and its assets."
    )
    _common_script_parser(lock_parser)
    lock_parser.add_argument(
        "-o",
        "--output",
        default="zundamotion.lock.json",
        help="Lock output path (default: zundamotion.lock.json).",
    )
    lock_parser.add_argument(
        "--compact", action="store_true", help="Write compact JSON instead of indented JSON."
    )

    verify_lock = subparsers.add_parser(
        "verify-lock", help="Recompute render provenance and compare it with a lock file."
    )
    _common_script_parser(verify_lock)
    verify_lock.add_argument(
        "--lock-file",
        default="zundamotion.lock.json",
        help="Lock file to verify (default: zundamotion.lock.json).",
    )
    verify_lock.add_argument(
        "--json", action="store_true", help="Emit machine-readable verification JSON."
    )

    inspect_parser = subparsers.add_parser(
        "inspect",
        help="Probe a rendered video, compare expected media parameters, and prepare visual QA.",
    )
    inspect_parser.add_argument("media_path", help="Rendered video to inspect.")
    expected_group = inspect_parser.add_mutually_exclusive_group()
    expected_group.add_argument(
        "--script",
        dest="inspect_script",
        default=None,
        help="Compare against the canonical output settings of this YAML/Markdown input.",
    )
    expected_group.add_argument(
        "--preset",
        default=None,
        help="Compare against a named Zundamotion export preset.",
    )
    inspect_parser.add_argument(
        "--project-root",
        default=None,
        help="Base directory for resolving --script assets/includes.",
    )
    inspect_parser.add_argument(
        "--contact-sheet",
        nargs="?",
        const="auto",
        default=None,
        metavar="PATH",
        help="Generate representative review frames as one PNG. PATH defaults beside the video.",
    )
    inspect_parser.add_argument(
        "--samples",
        type=int,
        default=5,
        help="Number of representative frames for --contact-sheet (1-12, default: 5).",
    )
    inspect_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the stable output-inspection JSON contract.",
    )

    subparsers.add_parser(
        "render",
        add_help=False,
        help="Explicit alias for the existing render CLI; accepts existing render options.",
    )
    return parser


def _run_legacy_render(argv: Sequence[str]) -> None:
    previous = sys.argv
    sys.argv = [previous[0], *argv]
    try:
        legacy_render_cli()
    finally:
        sys.argv = previous


def _run_inspect(args: argparse.Namespace) -> int:
    media_path = Path(args.media_path).expanduser().resolve()
    requested_contact_sheet = (
        None
        if args.contact_sheet is None
        else (
            media_path.with_name(f"{media_path.stem}_contact_sheet.png")
            if args.contact_sheet == "auto"
            else Path(args.contact_sheet).expanduser().resolve()
        )
    )

    expected = None
    if args.inspect_script:
        with _project_root(args.project_root):
            expected = expected_from_config(load_canonical_config(args.inspect_script))
    elif args.preset:
        expected = expected_from_preset(args.preset)

    document = asyncio.run(inspect_output(media_path, expected=expected))
    if requested_contact_sheet is not None:
        duration = (document.get("media") or {}).get("duration")
        if duration is None or float(duration) <= 0.0:
            raise ValueError("contact sheet requires a positive media duration")
        document["visual_review"] = asyncio.run(
            create_contact_sheet(
                media_path,
                requested_contact_sheet,
                duration=float(duration),
                samples=args.samples,
            )
        )

    if args.json:
        sys.stdout.write(_json_text(document))
    else:
        media = document["media"]
        video = media.get("video") or {}
        audio = media.get("audio") or {}
        duration = media.get("duration")
        state = "MACHINE PASS" if document["machine_valid"] else "MACHINE FAIL"
        sys.stdout.write(
            f"{state}: {document['path']} — {duration}s, "
            f"{video.get('width')}x{video.get('height')}, {video.get('fps')} fps, "
            f"{video.get('codec_name') or '-'}, {audio.get('codec_name') or '-'} "
            f"{audio.get('sample_rate') or '-'} Hz {audio.get('channels') or '-'} ch\n"
        )
        passed = sum(1 for item in document["checks"] if item["status"] == "pass")
        sys.stdout.write(f"Checks: {passed}/{len(document['checks'])} pass\n")
        for item in document["checks"]:
            if item["status"] != "pass":
                sys.stdout.write(
                    f"  FAIL {item['id']}: expected={item.get('expected')!r} "
                    f"actual={item.get('actual')!r}\n"
                )
        visual = document["visual_review"]
        if visual.get("contact_sheet"):
            sys.stdout.write(f"Contact sheet: {visual['contact_sheet']}\n")
            sys.stdout.write("Visual review: pending (inspect the PNG; metadata is not visual QA)\n")
        else:
            sys.stdout.write("Visual review: not generated\n")
    return 0 if document["machine_valid"] else 1


def _run_authoring(argv: Sequence[str]) -> int:
    parser = _authoring_parser()
    args = parser.parse_args(list(argv))

    if args.command == "capabilities":
        document = capabilities_document()
        if args.json:
            sys.stdout.write(_json_text(document))
        else:
            sys.stdout.write(
                "Zundamotion capabilities\n"
                f"  version: {document['zundamotion_version']}\n"
                f"  inputs: {', '.join(document['inputs'])}\n"
                f"  export presets: {', '.join(document['export_presets'])}\n"
                f"  TTS providers: {', '.join(document['tts']['providers'])}\n"
                f"  built-in plugins: {len(document['plugins'])}\n"
            )
        return 0

    if args.command == "inspect":
        try:
            return _run_inspect(args)
        except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as exc:
            parser.error(str(exc))
            return 2

    if args.command not in {"validate", "compile", "lock", "verify-lock"}:
        parser.print_help()
        return 0

    try:
        with _project_root(args.project_root):
            if args.command == "validate":
                document = validation_document(args.script_path)
                if args.json:
                    sys.stdout.write(_json_text(document))
                elif document["valid"]:
                    sys.stdout.write(f"valid: {args.script_path}\n")
                else:
                    for error in document["errors"]:
                        sys.stderr.write(f"{error['code']}: {error['message']}\n")
                return 0 if document["valid"] else 1

            if args.command == "compile":
                document = compiled_document(args.script_path)
                text = _json_text(document, pretty=args.pretty)
                if args.output:
                    output = Path(args.output)
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_text(text, encoding="utf-8")
                else:
                    sys.stdout.write(text)
                return 0

            if args.command == "lock":
                document = create_render_lock(args.script_path, project_root=Path.cwd())
                output = Path(args.output)
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(
                    render_lock_json(document, pretty=not args.compact), encoding="utf-8"
                )
                sys.stdout.write(f"render lock: {output}\n")
                return 0

            lock_document = load_render_lock(args.lock_file)
            document = verify_render_lock(
                args.script_path,
                lock_document,
                project_root=Path.cwd(),
            )
            if args.json:
                sys.stdout.write(_json_text(document))
            elif document["valid"]:
                sys.stdout.write(f"lock valid: {args.lock_file}\n")
            else:
                for difference in document["differences"]:
                    sys.stderr.write(
                        f"{difference['code']}: {difference['subject']} "
                        f"expected={difference['expected']!r} actual={difference['actual']!r}\n"
                    )
            return 0 if document["valid"] else 1
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
        return 2


def cli() -> None:
    """Dispatch machine-readable commands while preserving historical render CLI."""

    argv = sys.argv[1:]
    if argv and argv[0] == "render":
        _run_legacy_render(argv[1:])
        return
    if argv and argv[0] in _MACHINE_COMMANDS:
        raise SystemExit(_run_authoring(argv))
    if not argv or argv[0] in {"-h", "--help", "--version"}:
        raise SystemExit(_run_authoring(argv))

    # Backward compatibility: `zundamotion script.yaml ...` keeps rendering.
    _run_legacy_render(argv)


if __name__ == "__main__":
    cli()
