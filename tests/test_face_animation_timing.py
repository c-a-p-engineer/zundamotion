from zundamotion.components.video.clip.face import _enable_expr


def test_enable_expr_applies_time_shift() -> None:
    expr = _enable_expr(
        [{"start": 0.0, "end": 0.2, "state": "open"}],
        time_shift=0.5,
    )

    assert expr == "between(t,0.500,0.700)"


def test_enable_expr_clips_segments_before_start_offset_after_shift() -> None:
    expr = _enable_expr(
        [
            {"start": 0.0, "end": 0.2, "state": "half"},
            {"start": 0.2, "end": 0.5, "state": "open"},
        ],
        start_offset=0.4,
        time_shift=0.3,
    )

    assert expr == "between(t,0.400,0.500)+between(t,0.500,0.800)"
