"""Check local href/src references in generated site HTML."""
from __future__ import annotations
import argparse, re
from pathlib import Path

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--site-dir", type=Path, default=Path("site-dist")); args = parser.parse_args()
    missing=[]
    for page in args.site_dir.rglob("*.html"):
        for value in re.findall(r'(?:href|src)="([^"]+)"', page.read_text(encoding="utf-8")):
            if value.startswith(("http", "#")): continue
            target = args.site_dir / value.lstrip("/") if value.startswith("/") else page.parent / value
            if not target.is_file(): missing.append(f"{page}: {value}")
    if missing: raise SystemExit("broken links:\n" + "\n".join(missing))
    print("site link check passed"); return 0
if __name__ == "__main__": raise SystemExit(main())
