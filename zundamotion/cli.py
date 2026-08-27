"""Unified CLI dispatcher with backward-compatible render invocation."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sys
from typing import Iterator, Sequence

from . import __version__
from .authoring import capabilities_document, compiled_document, validation_document
from .main import cli as legacy_render_cli

_AUTHORING_COMMANDS = {"validate", "compile", "capabilities"}


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
            "Generate a video from YAML/Markdown, or inspect the same canonical "
            "configuration without rendering."
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
    compile_parser.add_argument("-o", "--output", default=None, help="Output JSON path; stdout when omitted.")
    compile_parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")

    capabilities = subparsers.add_parser(
        "capabilities", help="List stable package capabilities without external runtimes."
    )
    capabilities.add_argument(
        "--json", action="store_true", help="Emit the stable capabilities JSON contract."
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

    if args.command not in {"validate", "compile"}:
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
                        sys.stderr.write(
                            f"{error['code']}: {error['message']}\n"
                        )
                return 0 if document["valid"] else 1

            document = compiled_document(args.script_path)
            text = _json_text(document, pretty=args.pretty)
            if args.output:
                output = Path(args.output)
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(text, encoding="utf-8")
            else:
                sys.stdout.write(text)
            return 0
    except ValueError as exc:
        parser.error(str(exc))
        return 2


def cli() -> None:
    """Dispatch authoring commands while preserving the historical render CLI."""

    argv = sys.argv[1:]
    if argv and argv[0] == "render":
        _run_legacy_render(argv[1:])
        return
    if argv and argv[0] in _AUTHORING_COMMANDS:
        raise SystemExit(_run_authoring(argv))
    if not argv or argv[0] in {"-h", "--help", "--version"}:
        raise SystemExit(_run_authoring(argv))

    # Backward compatibility: `zundamotion script.yaml ...` keeps rendering.
    _run_legacy_render(argv)


if __name__ == "__main__":
    cli()
