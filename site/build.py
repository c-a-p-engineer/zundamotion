"""Build accessible static HTML from the feature manifest and inspected media."""
from __future__ import annotations

import argparse
import html
import sys
import shutil
import subprocess
from pathlib import Path

from site_lib import ROOT, load_manifest, run_json, write_json


def page(title: str, body: str) -> str:
    return f'<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title><link rel="stylesheet" href="/assets/css/site.css"></head><body><header><a href="/index.html">Zundamotion</a></header><main>{body}</main><script src="/assets/js/site.js"></script></body></html>'


def video(feature: dict, prefix: str = "") -> str:
    demo = feature["demo"]
    return f'<video controls preload="metadata" poster="{prefix}assets/posters/{demo["poster"]}"><source src="{prefix}assets/videos/{demo["output"]}" type="video/mp4"></video>'


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, default=Path("site-work"))
    parser.add_argument("--output", type=Path, default=Path("site-dist"))
    parser.add_argument("--render", action="store_true")
    args = parser.parse_args()
    if args.render:
        subprocess.run([sys.executable, "site/validate.py"], cwd=ROOT, check=True)
        subprocess.run([sys.executable, "site/render_demos.py", "--output", str(args.work_dir)], cwd=ROOT, check=True)
        subprocess.run([sys.executable, "site/inspect_media.py", "--work-dir", str(args.work_dir)], cwd=ROOT, check=True)
    if args.output.exists(): shutil.rmtree(args.output)
    for name in ("videos", "posters", "metadata"):
        shutil.copytree(args.work_dir / name, args.output / "assets" / name)
    shutil.copytree(ROOT / "site/static", args.output / "assets", dirs_exist_ok=True)
    manifest = load_manifest(); commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    categories = {item["id"]: item for item in manifest["categories"]}
    cards = "".join(f'<article><h2><a href="features/{f["id"]}.html">{html.escape(f["title"])}</a></h2><p>{html.escape(f["summary"])}</p>{video(f)}</article>' for f in manifest["features"])
    (args.output / "index.html").write_text(page(manifest["site"]["title"], f'<h1>{html.escape(manifest["site"]["description"])}</h1><p>生成元 commit: <code>{commit}</code></p><section class="grid">{cards}</section>'), encoding="utf-8")
    for feature in manifest["features"]:
        demo = feature["demo"]; yaml_text = (ROOT / demo["script"]).read_text(encoding="utf-8")
        body = f'<h1>{html.escape(feature["title"])}</h1><p>{html.escape(feature["summary"])}</p>{video(feature, "../")}<h2>何が起きるか</h2><ul>{"".join(f"<li>{html.escape(x)}</li>" for x in feature["description"])}</ul><h2>使いどころ</h2><ul>{"".join(f"<li>{html.escape(x)}</li>" for x in feature["use_cases"])}</ul><h2>制限</h2><ul>{"".join(f"<li>{html.escape(x)}</li>" for x in feature["limitations"])}</ul><h2>YAML</h2><button data-copy="yaml">コピー</button><pre id="yaml">{html.escape(yaml_text)}</pre><p><a href="../demos/{Path(demo["script"]).name}">完全なYAML</a></p><p>生成元 commit: <code>{commit}</code></p>'
        path = args.output / "features" / f'{feature["id"]}.html'; path.parent.mkdir(exist_ok=True); path.write_text(page(feature["title"], body), encoding="utf-8")
    for ident, category in categories.items():
        entries = [f for f in manifest["features"] if f["category"] == ident]
        links = "".join(f'<li><a href="../features/{f["id"]}.html">{html.escape(f["title"])}</a></li>' for f in entries)
        path = args.output / "categories" / f"{ident}.html"; path.parent.mkdir(exist_ok=True); path.write_text(page(category["title"], f'<h1>{html.escape(category["title"])}</h1><ul>{links}</ul>'), encoding="utf-8")
    shutil.copytree(ROOT / "site/demos", args.output / "demos")
    (args.output / "source-commit.txt").write_text(commit + "\n", encoding="utf-8"); (args.output / ".nojekyll").touch()
    write_json(args.output / "build-manifest.json", {"source_commit": commit, "features": {f["id"]: {"video": f["demo"]["output"]} for f in manifest["features"]}})
    return 0


if __name__ == "__main__": raise SystemExit(main())
