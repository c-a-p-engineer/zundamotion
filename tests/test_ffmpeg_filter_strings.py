import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from zundamotion.utils.ffmpeg_filter_strings import build_scale_opencl_filter


def test_build_scale_opencl_filter_uses_named_options():
    assert build_scale_opencl_filter(32, 32) == "scale_opencl=w=32:h=32"


def test_build_scale_opencl_filter_accepts_string_tokens():
    assert build_scale_opencl_filter("iw", "ih") == "scale_opencl=w=iw:h=ih"
