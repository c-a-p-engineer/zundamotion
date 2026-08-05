from __future__ import annotations

from pathlib import Path

from scripts.report_source_metrics import build_report, render_markdown


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_build_report_finds_large_files_and_functions(tmp_path: Path) -> None:
    _write(
        tmp_path / "package" / "large.py",
        "\n".join(
            [
                "class Renderer:",
                "    def render(self):",
                "        value = 1",
                "        return value",
                "",
                "def helper():",
                "    return 1",
            ]
        ),
    )
    _write(tmp_path / "package" / "small.py", "VALUE = 1\n")

    report = build_report(tmp_path, file_limit=5, function_limit=2)

    assert report.python_file_count == 2
    assert report.oversized_file_count == 1
    assert report.oversized_function_count == 1
    assert [item.path for item in report.files] == ["package/large.py"]
    metric = report.files[0]
    assert metric.longest_function is not None
    assert metric.longest_function.qualified_name == "Renderer.render"
    assert metric.longest_function.line_count == 3


def test_build_report_excludes_generated_directories(tmp_path: Path) -> None:
    _write(tmp_path / "source.py", "def source():\n    return 1\n")
    _write(tmp_path / ".venv" / "ignored.py", "def ignored():\n    return 1\n")
    _write(tmp_path / "output" / "ignored.py", "def ignored():\n    return 1\n")

    report = build_report(tmp_path, file_limit=100, function_limit=100)

    assert report.python_file_count == 1
    assert report.files == ()


def test_render_markdown_is_stable(tmp_path: Path) -> None:
    _write(
        tmp_path / "module.py",
        "def long_function():\n    first = 1\n    second = 2\n    return first + second\n",
    )

    report = build_report(tmp_path, file_limit=3, function_limit=3)
    markdown = render_markdown(report)

    assert "Files over 3 lines: 1" in markdown
    assert "Functions over 3 lines: 1" in markdown
    assert "| module.py | 4 | long_function | 4 | 1 |" in markdown
