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

