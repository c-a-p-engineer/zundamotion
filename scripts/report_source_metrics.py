#!/usr/bin/env python3
"""Report Python source-size metrics for staged refactoring work.

The report is deterministic for a given tree and intentionally measures only
repository Python files. Generated directories and virtual environments are
excluded so CI and local runs produce comparable results.
"""

from __future__ import annotations

import argparse
import ast
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


DEFAULT_FILE_LIMIT = 500
DEFAULT_FUNCTION_LIMIT = 80
EXCLUDED_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "build",
    "dist",
    "node_modules",
    "output",
    "site-packages",
    "venv",
}


@dataclass(frozen=True)
class FunctionMetric:
    qualified_name: str
    start_line: int
    end_line: int
    line_count: int


@dataclass(frozen=True)
class FileMetric:
    path: str
    line_count: int
    functions_over_limit: tuple[FunctionMetric, ...]
    longest_function: FunctionMetric | None


@dataclass(frozen=True)
class SourceMetricsReport:
    root: str
    file_limit: int
    function_limit: int
    python_file_count: int
    oversized_file_count: int
    oversized_function_count: int
    files: tuple[FileMetric, ...]


def _is_excluded(path: Path) -> bool:
    return any(part in EXCLUDED_PARTS for part in path.parts)


def iter_python_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root)
        if not _is_excluded(relative):
            yield path


def _qualified_function_name(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    parents: tuple[str, ...],
) -> str:
    return ".".join((*parents, node.name))


def collect_function_metrics(tree: ast.AST) -> list[FunctionMetric]:
    metrics: list[FunctionMetric] = []

    def visit(node: ast.AST, parents: tuple[str, ...] = ()) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                visit(child, (*parents, child.name))
                continue
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                end_line = int(getattr(child, "end_lineno", child.lineno))
                metrics.append(
                    FunctionMetric(
                        qualified_name=_qualified_function_name(child, parents),
                        start_line=int(child.lineno),
                        end_line=end_line,
                        line_count=end_line - int(child.lineno) + 1,
                    )
                )
                visit(child, (*parents, child.name))
                continue
            visit(child, parents)

    visit(tree)
    return sorted(
        metrics,
        key=lambda item: (-item.line_count, item.qualified_name, item.start_line),
    )


def analyze_file(path: Path, root: Path, function_limit: int) -> FileMetric:
    source = path.read_text(encoding="utf-8")
    line_count = len(source.splitlines())
    tree = ast.parse(source, filename=str(path))
    functions = collect_function_metrics(tree)
    oversized = tuple(item for item in functions if item.line_count > function_limit)
    return FileMetric(
        path=path.relative_to(root).as_posix(),
        line_count=line_count,
        functions_over_limit=oversized,
        longest_function=functions[0] if functions else None,
    )


def build_report(
    root: Path,
    *,
    file_limit: int = DEFAULT_FILE_LIMIT,
    function_limit: int = DEFAULT_FUNCTION_LIMIT,
) -> SourceMetricsReport:
    root = root.resolve()
    files = tuple(
        analyze_file(path, root, function_limit) for path in iter_python_files(root)
    )
    relevant = tuple(
        metric
        for metric in files
        if metric.line_count > file_limit or metric.functions_over_limit
    )
    return SourceMetricsReport(
        root=root.as_posix(),
        file_limit=file_limit,
        function_limit=function_limit,
        python_file_count=len(files),
        oversized_file_count=sum(item.line_count > file_limit for item in files),
        oversized_function_count=sum(
            len(item.functions_over_limit) for item in files
        ),
        files=tuple(
            sorted(
                relevant,
                key=lambda item: (
                    -(item.line_count > file_limit),
                    -item.line_count,
                    item.path,
                ),
            )
        ),
    )


def render_markdown(report: SourceMetricsReport) -> str:
    lines = [
        "# Source metrics",
        "",
        f"- Python files: {report.python_file_count}",
        f"- Files over {report.file_limit} lines: {report.oversized_file_count}",
        (
            f"- Functions over {report.function_limit} lines: "
            f"{report.oversized_function_count}"
        ),
        "",
        "| File | Lines | Longest function | Function lines | Over-limit functions |",
        "| --- | ---: | --- | ---: | ---: |",
    ]
    for item in report.files:
        longest = item.longest_function
        lines.append(
            "| {path} | {lines_count} | {name} | {function_lines} | {over_limit} |".format(
                path=item.path,
                lines_count=item.line_count,
                name=longest.qualified_name if longest else "-",
                function_lines=longest.line_count if longest else 0,
                over_limit=len(item.functions_over_limit),
            )
        )
    return "\n".join(lines) + "\n"


def _write_outputs(
    report: SourceMetricsReport,
    *,
    json_output: Path | None,
    markdown_output: Path | None,
) -> None:
    if json_output is not None:
        json_output.parent.mkdir(parents=True, exist_ok=True)
        json_output.write_text(
            json.dumps(asdict(report), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    markdown = render_markdown(report)
    if markdown_output is not None:
        markdown_output.parent.mkdir(parents=True, exist_ok=True)
        markdown_output.write_text(markdown, encoding="utf-8")
    print(markdown, end="")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--file-limit", type=int, default=DEFAULT_FILE_LIMIT)
    parser.add_argument(
        "--function-limit", type=int, default=DEFAULT_FUNCTION_LIMIT
    )
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_report(
        args.root,
        file_limit=args.file_limit,
        function_limit=args.function_limit,
    )
    _write_outputs(
        report,
        json_output=args.json_output,
        markdown_output=args.markdown_output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
