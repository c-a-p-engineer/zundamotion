from __future__ import annotations

from types import SimpleNamespace

import pytest
from PIL import Image

from zundamotion.components.video.clip.characters import build_character_overlays
from zundamotion.components.video.clip.opacity import (
    build_alpha_multiplier_filter_parts,
    build_opacity_expression,
    opacity_requested,
)
from zundamotion.exceptions import ValidationError


def test_no_opacity_request_keeps_legacy_path_inactive() -> None:
    expr, active = build_opacity_expression(
        move_config=None,
        to_opacity=None,
    )

    assert expr == "1.000000"
    assert active is False
    assert opacity_requested({"visible": True}) is False


def test_static_opacity_is_explicit_alpha_owner() -> None:
    expr, active = build_opacity_expression(
        move_config=None,
        to_opacity=0.4,
    )

    assert expr == "0.400000"
    assert active is True
    assert opacity_requested({"opacity": 1.0}) is True


def test_animated_opacity_uses_geq_time_variable_and_segment_easing() -> None:
    expr, active = build_opacity_expression(
        move_config={
            "from": {"opacity": 0.0},
            "start": 0.2,
            "duration": 1.0,
            "easing": "linear",
            "keyframes": [
                {"at": 0.4, "opacity": 1.0, "easing": "ease_out"},
            ],
        },
        to_opacity=0.5,
    )

    assert active is True
    assert "lt(T,0.200000)" in expr
    assert "0.600000" in expr
    assert "1-(1-(" in expr
    assert "0.500000" in expr
    assert "lt(t," not in expr


def test_alpha_multiplier_filter_preserves_color_branch() -> None:
    parts = build_alpha_multiplier_filter_parts(
        input_label="[in]",
        output_label="[out]",
        opacity_expr="if(lt(T,0.5),0.5,1.0)",
        prefix="hero_opacity",
    )

    assert parts[0] == "[in]split[hero_opacity_color][hero_opacity_alpha_in]"
    assert "alphaextract" in parts[1]
    assert "geq=lum='lum(X\,Y)*(if(lt(T\,0.5)\,0.5\,1.0))'" in parts[1]
    assert parts[2] == (
        "[hero_opacity_color][hero_opacity_alpha]alphamerge[out]"
    )


@pytest.mark.parametrize("value", [-0.1, 1.1, float("nan"), float("inf"), True])
def test_opacity_expression_rejects_invalid_domain(value) -> None:
    with pytest.raises(ValidationError):
        build_opacity_expression(
            move_config=None,
            to_opacity=value,
        )


def test_standard_character_graph_adds_opacity_only_when_requested(tmp_path) -> None:
    image_path = tmp_path / "hero.png"
    Image.new("RGBA", (20, 40), (0, 255, 0, 128)).save(image_path)
    renderer = SimpleNamespace(
        scale_flags="bicubic",
        video_params=SimpleNamespace(width=320, height=180),
    )

    def render_parts(character):
        filter_parts: list[str] = []
        overlay_streams: list[str] = []
        overlay_filters: list[str] = []
        placements = build_character_overlays(
            renderer=renderer,
            characters_config=[character],
            duration=1.2,
            character_indices={0: 1},
            char_effective_scale={0: 1.0},
            filter_complex_parts=filter_parts,
            overlay_streams=overlay_streams,
            overlay_filters=overlay_filters,
            use_cuda_filters=False,
            use_opencl=False,
            metadata={
                0: {
                    "name": "hero",
                    "asset_name": "hero",
                    "expression": "default",
                    "image_path": image_path,
                    "source_width": 20,
                    "source_height": 40,
                    "preprocessed_flip_x": False,
                    "preprocessed_flip_y": False,
                }
            },
        )
        return filter_parts, placements

    legacy_parts, legacy_placements = render_parts(
        {
            "name": "hero",
            "visible": True,
            "position": {"x": 0, "y": -20},
            "scale": 1.0,
        }
    )
    opacity_parts, opacity_placements = render_parts(
        {
            "name": "hero",
            "visible": True,
            "position": {"x": 0, "y": -20},
            "scale": 1.0,
            "opacity": 0.5,
            "enter": "fade",
            "enter_duration": 0.4,
        }
    )

    assert len(legacy_parts) == 1
    assert not any("alphaextract" in part for part in legacy_parts)

    assert any("fade=t=in:st=0:d=0.4:alpha=1" in part for part in opacity_parts)
    assert any("alphaextract" in part for part in opacity_parts)
    assert any("geq=lum=" in part for part in opacity_parts)
    assert opacity_placements["hero"]["opacity_active"] is True
    assert opacity_placements["hero"]["opacity_expr"] == "0.500000"
