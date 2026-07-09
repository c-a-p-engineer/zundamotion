from zundamotion.components.video.clip_renderer import _atempo_chain, _media_speed


def test_media_speed_is_clamped_to_supported_range():
    assert _media_speed("bad") == 1.0
    assert _media_speed(0.1) == 0.25
    assert _media_speed(5.0) == 4.0


def test_atempo_chain_splits_values_outside_single_filter_range():
    assert _atempo_chain(1.25) == "atempo=1.250000"
    assert _atempo_chain(4.0) == "atempo=2.000000,atempo=2.000000"
    assert _atempo_chain(0.25) == "atempo=0.500000,atempo=0.500000"
