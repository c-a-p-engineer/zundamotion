import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / "site"))
from validate import validate
from site_lib import load_manifest


def test_checked_in_manifest_is_valid():
    assert validate(load_manifest()) == []


def test_manifest_rejects_duplicate_id():
    manifest = load_manifest(); manifest["features"].append(dict(manifest["features"][0]))
    assert any("duplicate" in item for item in validate(manifest))
