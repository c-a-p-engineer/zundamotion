import pytest

from zundamotion.exceptions import ValidationError
from zundamotion.utils.export_presets import apply_export_preset


def test_export_preset_sets_missing_video_defaults():
    config = {"export_preset": "shorts_1080x1920", "video": {"fps": 60}}

    apply_export_preset(config)

    assert config["video"]["width"] == 1080
    assert config["video"]["height"] == 1920
    assert config["video"]["fps"] == 60
    assert config["video"]["audio_bitrate_kbps"] == 192


def test_unknown_export_preset_raises_validation_error():
    with pytest.raises(ValidationError):
        apply_export_preset({"export_preset": "unknown"})
