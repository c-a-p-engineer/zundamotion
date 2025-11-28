from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from zundamotion.components.video.overlay_effects import resolve_overlay_effects


def test_overlay_effects_are_resolved_in_order():
    effects = [
        {"type": "blur", "sigma": 5},
        {"type": "eq", "brightness": 0.05, "contrast": 1.1},
        {"type": "hue", "h": 90, "s": 1.2},
        {"type": "curves", "preset": "medium_contrast"},
        {"type": "unsharp", "lx": 3, "ly": 3, "la": 0.5, "cx": 0, "cy": 0, "ca": 0},
        {"type": "lut3d", "file": "foo.cube"},
        {"type": "rotate", "degrees": 90, "fill": "0x11223344"},
        "vignette",
    ]

    assert resolve_overlay_effects(effects) == [
        "gblur=sigma=5.0000",
        "eq=contrast=1.100000:brightness=0.050000",
        "hue=h=90.000000:s=1.200000",
        "curves=preset=medium_contrast",
        "unsharp=3:3:0.5:0:0:0.0",
        "lut3d=file=foo.cube",
        "rotate=1.570796:fillcolor=0x11223344",
        "vignette",
    ]


def test_unknown_effects_are_ignored():
    assert resolve_overlay_effects([{"type": "unknown"}]) == []
