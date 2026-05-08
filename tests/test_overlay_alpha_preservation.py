"""Ensure overlay filters preserve transparency when effects are applied."""

from zundamotion.components.video.overlays import OverlayMixin


class _DummyOverlay(OverlayMixin):
    def __init__(self) -> None:
        self.scale_flags = "bicubic"

    def _build_effect_filters(self, effects):  # type: ignore[override]
        # Reuse base implementation
        return super()._build_effect_filters(effects)


def test_overlay_chain_keeps_alpha_mask_when_effects_present():
    dummy = _DummyOverlay()

    filters, processed = dummy._build_overlay_filter_parts(  # type: ignore[attr-defined]
        "[1:v]",
        0,
        {
            "opacity": 0.85,
            "effects": [{"type": "blur", "sigma": 2.0}],
            "scale": {"w": 640, "h": 480, "keep_aspect": True},
        },
    )

    assert processed == "[ov0]"
    # First leg ensures split into color/alpha with format before effects
    assert any("split[ov0_c_in][ov0_a_in]" in part for part in filters)
    # Alpha leg must apply opacity scaling only on alpha channel
    assert any("lut=a='val*0.850000'" in part for part in filters)
    # Final merge should recombine color and preserved alpha
    assert any("alphamerge[ov0]" in part for part in filters)


def test_subtitle_png_chunks_split_continuous_ranges_by_count():
    subtitles = [
        {"text": str(idx), "start": float(idx), "duration": 0.9, "line_config": {}}
        for idx in range(7)
    ]

    chunks = OverlayMixin._split_subtitle_ranges_for_png(
        subtitles,
        base_duration=10.0,
        gap_threshold=0.20,
        max_subtitles=3,
    )

    assert [len(chunk["subtitles"]) for chunk in chunks] == [3, 3, 1]
    assert chunks[0]["start"] == 0.0
    assert chunks[0]["end"] == 2.9
    assert chunks[1]["start"] == 3.0


def test_subtitle_png_chunks_do_not_split_overlapping_subtitles():
    subtitles = [
        {"text": "a", "start": 0.0, "duration": 2.0, "line_config": {}},
        {"text": "b", "start": 1.0, "duration": 2.0, "line_config": {}},
        {"text": "c", "start": 2.0, "duration": 1.0, "line_config": {}},
    ]

    chunks = OverlayMixin._split_subtitle_ranges_for_png(
        subtitles,
        base_duration=3.0,
        gap_threshold=0.20,
        max_subtitles=1,
    )

    assert len(chunks) == 1
    assert len(chunks[0]["subtitles"]) == 3
