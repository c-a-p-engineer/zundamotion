from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parents[1] / "site"))
from build import page


def test_page_escapes_title():
    assert "&lt;tag&gt;" in page("<tag>", "body")


def test_static_assets_exist():
    assert Path("site/static/css/site.css").is_file()
    assert Path("site/static/js/site.js").is_file()
