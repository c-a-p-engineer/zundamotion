from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "site"))

from build import page


def test_page_escapes_title() -> None:
    assert "&lt;tag&gt;" in page("<tag>", "body")


def test_root_page_uses_relative_assets() -> None:
    content = page("Title", "body")

    assert 'href="assets/css/site.css"' in content
    assert 'href="index.html"' in content
    assert 'src="assets/js/site.js"' in content
    assert 'href="/assets/' not in content


def test_nested_page_uses_parent_relative_assets() -> None:
    content = page("Title", "body", prefix="../")

    assert 'href="../assets/css/site.css"' in content
    assert 'href="../index.html"' in content
    assert 'src="../assets/js/site.js"' in content


def test_static_assets_exist() -> None:
    assert Path("site/static/css/site.css").is_file()
    assert Path("site/static/js/site.js").is_file()
