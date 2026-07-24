from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "site"))

from link_check import check_links


def test_relative_links_are_valid(tmp_path: Path) -> None:
    site = tmp_path / "site-dist"
    (site / "assets" / "css").mkdir(parents=True)
    (site / "features").mkdir(parents=True)
    (site / "assets" / "css" / "site.css").write_text("", encoding="utf-8")
    (site / "index.html").write_text(
        '<link rel="stylesheet" href="assets/css/site.css">',
        encoding="utf-8",
    )
    (site / "features" / "demo.html").write_text(
        '<a href="../index.html">home</a>',
        encoding="utf-8",
    )

    assert check_links(site) == []


def test_project_root_absolute_link_is_rejected(tmp_path: Path) -> None:
    site = tmp_path / "site-dist"
    site.mkdir()
    (site / "index.html").write_text(
        '<link rel="stylesheet" href="/assets/css/site.css">',
        encoding="utf-8",
    )

    errors = check_links(site)

    assert len(errors) == 1
    assert "ルート絶対パス" in errors[0]


def test_site_escape_is_rejected(tmp_path: Path) -> None:
    site = tmp_path / "site-dist"
    site.mkdir()
    (tmp_path / "outside.txt").write_text("outside", encoding="utf-8")
    (site / "index.html").write_text(
        '<a href="../outside.txt">outside</a>',
        encoding="utf-8",
    )

    errors = check_links(site)

    assert len(errors) == 1
    assert "site外" in errors[0]
