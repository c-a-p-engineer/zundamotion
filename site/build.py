"""Build accessible static HTML from the feature manifest and inspected media."""

from __future__ import annotations

import argparse
import html
import shutil
import subprocess
import sys
from pathlib import Path

from site_lib import ROOT, load_manifest, write_json


def page(title: str, body: str, *, prefix: str = "") -> str:
    """Return a complete page using paths relative to the generated document."""

    escaped_title = html.escape(title)
    return (
        "<!doctype html>"
        '<html lang="ja">'
        "<head>"
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{escaped_title}</title>"
        f'<link rel="stylesheet" href="{prefix}assets/css/site.css">'
        "</head>"
        "<body>"
        f'<header><a href="{prefix}index.html">Zundamotion</a></header>'
        f"<main>{body}</main>"
        f'<script src="{prefix}assets/js/site.js"></script>'
        "</body>"
        "</html>"
    )


def video(feature: dict, prefix: str = "") -> str:
    demo = feature["demo"]
    poster = html.escape(f'{prefix}assets/posters/{demo["poster"]}')
    source = html.escape(f'{prefix}assets/videos/{demo["output"]}')
    return (
        f'<video controls preload="metadata" poster="{poster}">'
        f'<source src="{source}" type="video/mp4">'
        "</video>"
    )


def _list_items(values: list[str]) -> str:
    return "".join(f"<li>{html.escape(value)}</li>" for value in values)


def _write_page(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _build_index(manifest: dict, commit: str) -> str:
    cards = "".join(
        (
            "<article>"
            f'<h2><a href="features/{feature["id"]}.html">'
            f'{html.escape(feature["title"])}</a></h2>'
            f'<p>{html.escape(feature["summary"])}</p>'
            f"{video(feature)}"
            "</article>"
        )
        for feature in manifest["features"]
    )
    body = (
        f'<h1>{html.escape(manifest["site"]["description"])}</h1>'
        f"<p>生成元 commit: <code>{html.escape(commit)}</code></p>"
        f'<section class="grid">{cards}</section>'
    )
    return page(manifest["site"]["title"], body)


def _build_feature(feature: dict, commit: str) -> str:
    demo = feature["demo"]
    yaml_text = (ROOT / demo["script"]).read_text(encoding="utf-8")
    body = (
        f'<h1>{html.escape(feature["title"])}</h1>'
        f'<p>{html.escape(feature["summary"])}</p>'
        f'{video(feature, "../")}'
        "<h2>何が起きるか</h2>"
        f'<ul>{_list_items(feature["description"])}</ul>'
        "<h2>使いどころ</h2>"
        f'<ul>{_list_items(feature["use_cases"])}</ul>'
        "<h2>制限</h2>"
        f'<ul>{_list_items(feature["limitations"])}</ul>'
        "<h2>YAML</h2>"
        '<button data-copy="yaml">コピー</button>'
        f'<pre id="yaml">{html.escape(yaml_text)}</pre>'
        f'<p><a href="../demos/{html.escape(Path(demo["script"]).name)}">'
        "完全なYAML</a></p>"
        f"<p>生成元 commit: <code>{html.escape(commit)}</code></p>"
    )
    return page(feature["title"], body, prefix="../")


def _build_category(category: dict, features: list[dict]) -> str:
    links = "".join(
        f'<li><a href="../features/{feature["id"]}.html">'
        f'{html.escape(feature["title"])}</a></li>'
        for feature in features
    )
    body = f'<h1>{html.escape(category["title"])}</h1><ul>{links}</ul>'
    return page(category["title"], body, prefix="../")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, default=Path("site-work"))
    parser.add_argument("--output", type=Path, default=Path("site-dist"))
    parser.add_argument("--render", action="store_true")
    args = parser.parse_args()

    if args.render:
        subprocess.run([sys.executable, "site/validate.py"], cwd=ROOT, check=True)
        subprocess.run(
            [sys.executable, "site/render_demos.py", "--output", str(args.work_dir)],
            cwd=ROOT,
            check=True,
        )
        subprocess.run(
            [
                sys.executable,
                "site/inspect_media.py",
                "--work-dir",
                str(args.work_dir),
            ],
            cwd=ROOT,
            check=True,
        )

    if args.output.exists():
        shutil.rmtree(args.output)

    for name in ("videos", "posters", "metadata"):
        shutil.copytree(args.work_dir / name, args.output / "assets" / name)
    shutil.copytree(ROOT / "site/static", args.output / "assets", dirs_exist_ok=True)

    manifest = load_manifest()
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
    ).strip()

    _write_page(
        args.output / "index.html",
        _build_index(manifest, commit),
    )

    for feature in manifest["features"]:
        _write_page(
            args.output / "features" / f'{feature["id"]}.html',
            _build_feature(feature, commit),
        )

    for category in manifest["categories"]:
        entries = [
            feature
            for feature in manifest["features"]
            if feature["category"] == category["id"]
        ]
        _write_page(
            args.output / "categories" / f'{category["id"]}.html',
            _build_category(category, entries),
        )

    shutil.copytree(ROOT / "site/demos", args.output / "demos")
    (args.output / "source-commit.txt").write_text(
        commit + "\n",
        encoding="utf-8",
    )
    (args.output / ".nojekyll").touch()
    write_json(
        args.output / "build-manifest.json",
        {
            "source_commit": commit,
            "features": {
                feature["id"]: {"video": feature["demo"]["output"]}
                for feature in manifest["features"]
            },
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
