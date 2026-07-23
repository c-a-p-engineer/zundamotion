from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parents[1] / "site"))
from site_lib import load_manifest


def test_initial_eleven_demos_are_present():
    ids = {item["id"] for item in load_manifest()["features"]}
    assert {"minimal", "voicevox", "subtitle", "character-basic", "character-move", "background-pan-zoom", "bgm-control", "transition", "overlay-compositing", "insert-video-speed", "output-shorts"} <= ids
