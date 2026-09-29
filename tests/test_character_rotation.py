from __future__ import annotations

import math
from types import SimpleNamespace

import pytest
from PIL import Image

from zundamotion.components.video.clip.characters import build_character_overlays
from zundamotion.components.video.clip.rotation import (
    build_rotate_expression,
    build_rotation_canvas,
    build_rotation_filter,
    correct_rotation_position,
    rotation_requested,
)


def test_static_rotate_expression_uses_degrees_and_clockwise_radians() -> None:
    expr, active = build_rotate_expression(
        move_config=None,
        to_rotate=90,
    )

    assert active is True
    assert float(expr) == pytest.approx(math.pi / 2.0, abs=1e-9)


def test_rotate_track_does_not_apply_shortest_path_normalization() -> None:
    expr, active = build_rotate_expression(
        move_config={
            "from": {"rotate": 350},
            "duration": 1.0,
            "easing": "linear",
        },
        to_rotate=10,
    )

    assert active is True
    assert f"{math.radians(350):.9f}" in expr
    assert f"{math.radians(10):.9f}" in expr


def test_rotate_track_accepts_sparse_waypoints_and_segment_easing() -> None:
    expr, active = build_rotate_expression(
        move_config={
            "from": {"rotate": -10},
            "start": 0.2,
            "duration": 1.0,
            "easing": "linear",
            "keyframes": [
                {"at": 0.25, "x": 20},
                {"at": 0.6, "rotate": 30, "easing": "ease_out"},
            ],
        },
        to_rotate=0,
    )

    assert active is True
    assert "0.800000" in expr
    assert f"{math.radians(-10):.9f}" in expr
    assert f"{math.radians(30):.9f}" in expr
    assert "1-(1-(" in expr


def test_rotation_canvas_places_bottom_center_anchor_at_canvas_center() -> None:
    canvas = build_rotation_canvas(
        source_width=100,
        source_height=200,
        move_config={"from": {"scale": 1.0}, "duration": 1.0},
        to_scale=1.0,
        anchor="bottom_center",
    )

    assert canvas.width % 2 == 0
    assert canvas.height % 2 == 0
    assert canvas.pad_x + 50 == pytest.approx(canvas.width / 2.0)
    assert canvas.pad_y + 200 == pytest.approx(canvas.height / 2.0)
    assert canvas.correction_x == pytest.approx(0.0)
    assert canvas.correction_y == pytest.approx(canvas.height / 2.0)


def test_rotation_canvas_accounts_for_largest_intermediate_scale() -> None:
    canvas = build_rotation_canvas(
        source_width=100,
        source_height=200,
        move_config={
            "from": {"scale": 0.8},
            "duration": 1.0,
            "keyframes": [{"at": 0.5, "scale": 1.5}],
        },
        to_scale=1.0,
        anchor="middle_center",
    )

    radius = math.hypot(75, 150)
    assert canvas.width >= math.ceil(radius * 2)
    assert canvas.height >= math.ceil(radius * 2)
    assert canvas.correction_x == pytest.approx(0.0)
    assert canvas.correction_y == pytest.approx(0.0)


def test_rotation_filter_keeps_fixed_transparent_dimensions() -> None:
    canvas = build_rotation_canvas(
        source_width=40,
        source_height=80,
        move_config=None,
        to_scale=1.0,
        anchor="top_left",
    )
    filter_expr = build_rotation_filter("if(lt(t,0.5),0,1.0)", canvas)

    assert f"pad=w={canvas.width}:h={canvas.height}" in filter_expr
    assert "rotate=angle='if(lt(t\,0.5)\,0\,1.0)'" in filter_expr
    assert "ow=iw:oh=ih" in filter_expr
    assert "fillcolor=0x00000000" in filter_expr


def test_rotation_position_correction_keeps_pivot_world_coordinate() -> None:
    canvas = build_rotation_canvas(
        source_width=40,
        source_height=80,
        move_config=None,
        to_scale=1.0,
        anchor="bottom_center",
    )

    corrected = correct_rotation_position("H-h-32", canvas.correction_y)

    assert corrected == f"(H-h-32)+({canvas.correction_y:.6f})"


def test_rotation_requested_detects_static_and_track_rotation() -> None:
    assert rotation_requested({"rotate": 5}) is True
    assert rotation_requested({"rotate": 0}) is False
    assert rotation_requested(
        {"rotate": 0, "move": {"from": {"rotate": -5}, "duration": 1.0}}
    ) is True
    assert rotation_requested(
        {
            "rotate": 0,
            "move": {
                "from": {"rotate": 0},
                "duration": 1.0,
                "keyframes": [{"at": 0.5, "rotate": 10}],
            },
        }
    ) is True



def test_standard_character_graph_applies_fixed_canvas_rotate(
    tmp_path,
) -> None:
    image_path = tmp_path / "hero.png"
    Image.new("RGBA", (20, 40), (0, 255, 0, 255)).save(image_path)
    renderer = SimpleNamespace(
        scale_flags="bicubic",
        video_params=SimpleNamespace(width=320, height=180),
    )
    filter_parts: list[str] = []
    overlay_streams: list[str] = []
    overlay_filters: list[str] = []

    placements = build_character_overlays(
        renderer=renderer,
        characters_config=[
            {
                "name": "hero",
                "visible": True,
                "anchor": "bottom_center",
                "position": {"x": 0, "y": -20},
                "scale": 1.0,
                "rotate": 90,
                "move": {
                    "from": {"rotate": 0},
                    "duration": 1.0,
                    "easing": "linear",
                },
            }
        ],
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

    assert len(filter_parts) == 1
    assert "pad=w=" in filter_parts[0]
    assert "rotate=angle=" in filter_parts[0]
    assert "fillcolor=0x00000000" in filter_parts[0]
    assert overlay_filters and overlay_filters[0].startswith("overlay=x=")
    assert placements["hero"]["rotate_active"] is True
    assert placements["hero"]["rotate_expr"] != "0"
    assert placements["hero"]["dynamic_position"] is True
