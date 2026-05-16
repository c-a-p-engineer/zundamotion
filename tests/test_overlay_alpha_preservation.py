"""Ensure overlay filters preserve transparency when effects are applied."""

from zundamotion.components.video.overlays import OverlayMixin


class _DummyOverlay(OverlayMixin):
    def __init__(self) -> None:
        self.scale_flags = "bicubic"
        self.subtitle_gen = type(
            "SubtitleGen",
            (),
            {"subtitle_config": {}},
        )()

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


def test_auto_subtitle_png_chunk_size_scales_for_long_many_subtitle_scene():
    value = OverlayMixin._auto_subtitle_png_chunk_size(
        90,
        base_duration=534.25,
        cpu_count=12,
    )

    assert value == 15


def test_auto_subtitle_png_chunk_size_accounts_for_dense_continuous_subtitles():
    value = OverlayMixin._auto_subtitle_png_chunk_size(
        149,
        base_duration=975.77,
        cpu_count=12,
        subtitle_density=149 / 975.77,
        gap_duration=120.0,
        longest_zone=420.0,
    )

    assert value == 22


def test_auto_subtitle_png_chunk_size_allows_fewer_chunks_for_sparse_gap_heavy_scene():
    value = OverlayMixin._auto_subtitle_png_chunk_size(
        90,
        base_duration=534.25,
        cpu_count=12,
        subtitle_density=90 / 534.25,
        gap_duration=300.0,
        longest_zone=70.0,
    )

    assert value == 18


def test_explicit_subtitle_png_chunk_size_overrides_auto():
    dummy = _DummyOverlay()
    dummy.subtitle_gen.subtitle_config = {"png_chunk_size": 24}

    assert dummy._subtitle_png_chunk_size([{}] * 90, base_duration=534.25) == 24
