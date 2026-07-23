from pathlib import Path
import sys
import pytest
sys.path.insert(0, str(Path(__file__).parents[1] / "site"))
from inspect_media import inspect


def test_missing_media_is_rejected():
    with pytest.raises(ValueError, match="missing"):
        inspect(Path("does-not-exist.mp4"), {"width": 640, "height": 360, "max_duration_seconds": 12, "max_size_bytes": 1, "audio_required": False})
