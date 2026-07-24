"""Check local href/src references in generated site HTML."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from urllib.parse import urlsplit


_REFERENCE_PATTERN = re.compile(r'(?:href|src)="([^"]+)"')
_EXTERNAL_SCHEMES = {"http", "https", "mailto", "tel", "data"}


def check_links(site_dir: Path) -> list[str]:
    """Return generated-site link errors without assuming domain-root hosting."""

    root = site_dir.resolve()
    errors: list[str] = []

    for page in site_dir.rglob("*.html"):
        content = page.read_text(encoding="utf-8")
        for value in _REFERENCE_PATTERN.findall(content):
            parsed = urlsplit(value)
            if parsed.scheme in _EXTERNAL_SCHEMES or value.startswith("#"):
                continue
            if value.startswith("//"):
                continue
            if value.startswith("/"):
                errors.append(
                    f"{page}: project Pagesではルート絶対パスを使用できません: {value}"
                )
                continue
            if not parsed.path:
                continue

            target = (page.parent / parsed.path).resolve()
            try:
                target.relative_to(root)
            except ValueError:
                errors.append(f"{page}: site外への参照です: {value}")
                continue

            if not target.is_file():
                errors.append(f"{page}: 参照先がありません: {value}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-dir", type=Path, default=Path("site-dist"))
    args = parser.parse_args()

    errors = check_links(args.site_dir)
    if errors:
        raise SystemExit("broken links:\n" + "\n".join(errors))

    print("site link check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
