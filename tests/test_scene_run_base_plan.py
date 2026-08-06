from __future__ import annotations

from pathlib import Path

from zundamotion.components.pipeline_phases.video_phase.scene_run_base_plan import (
    build_run_base_plans,
)


def _norm(line):
    return {
        str(item["name"]): dict(item)
        for item in line.get("characters", [])
        if item.get("visible", True) is not False and item.get("name")
    }


def _talk(name="zunda", **extra):
    return {
        "characters": [{"name": name, "visible": True, "scale": 1.0}],
        **extra,
    }


def _data(*durations):
    return {
        f"scene_{index}": {"duration": duration}
        for index, duration in enumerate(durations, start=1)
    }


def test_consecutive_equal_lines_form_one_run() -> None:
    plans = build_run_base_plans(
        scene_id="scene",
        lines=[_talk(), _talk()],
        line_data_map=_data(1.0, 2.0),
        norm_char_entries=_norm,
        video_extensions={".mp4"},
    )

    assert len(plans) == 1
    plan = plans[0]
    assert (plan.start_line, plan.end_line) == (1, 2)
    assert plan.duration == 3.0
    assert plan.offsets == {1: 0.0, 2: 1.0}


def test_wait_splits_runs_and_preserves_original_indexes() -> None:
    plans = build_run_base_plans(
        scene_id="scene",
        lines=[_talk(), {"wait": 1.0}, _talk(), _talk()],
        line_data_map=_data(1.0, 1.0, 2.0, 3.0),
        norm_char_entries=_norm,
        video_extensions={".mp4"},
    )

    assert len(plans) == 1
    plan = plans[0]
    assert (plan.start_line, plan.end_line) == (3, 4)
    assert plan.duration == 5.0
    assert plan.offsets == {3: 0.0, 4: 2.0}


def test_signature_change_closes_previous_run_with_previous_insert(tmp_path: Path) -> None:
    first_insert = tmp_path / "first.png"
    second_insert = tmp_path / "second.png"
    first_insert.write_bytes(b"first")
    second_insert.write_bytes(b"second")
    lines = [
        _talk(insert={"path": str(first_insert), "scale": 1.0}),
        _talk(insert={"path": str(first_insert), "scale": 1.0}),
        _talk("metan", insert={"path": str(second_insert), "scale": 2.0}),
        _talk("metan", insert={"path": str(second_insert), "scale": 2.0}),
    ]

    plans = build_run_base_plans(
        scene_id="scene",
        lines=lines,
        line_data_map=_data(1.0, 1.0, 1.0, 1.0),
        norm_char_entries=_norm,
        video_extensions={".mp4"},
    )

    assert len(plans) == 2
    assert plans[0].overlays[-1]["path"] == str(first_insert.resolve())
    assert plans[0].character_keys == frozenset({"zunda"})
    assert plans[1].overlays[-1]["path"] == str(second_insert.resolve())
    assert plans[1].character_keys == frozenset({"metan"})


def test_character_state_change_breaks_run() -> None:
    lines = [_talk(), _talk(), _talk(), _talk()]
    lines[2]["characters"][0]["scale"] = 1.5
    lines[3]["characters"][0]["scale"] = 1.5

    plans = build_run_base_plans(
        scene_id="scene",
        lines=lines,
        line_data_map=_data(1.0, 1.0, 1.0, 1.0),
        norm_char_entries=_norm,
        video_extensions={".mp4"},
    )

    assert [(item.start_line, item.end_line) for item in plans] == [(1, 2), (3, 4)]


def test_image_layer_and_background_override_are_boundaries() -> None:
    plans = build_run_base_plans(
        scene_id="scene",
        lines=[
            _talk(),
            _talk(),
            {"type": "image_layer"},
            _talk(background={"path": "other.png"}),
            _talk(),
        ],
        line_data_map=_data(1.0, 1.0, 1.0, 1.0, 1.0),
        norm_char_entries=_norm,
        video_extensions={".mp4"},
    )

    assert [(item.start_line, item.end_line) for item in plans] == [(1, 2)]


def test_single_line_and_characterless_runs_are_ignored() -> None:
    plans = build_run_base_plans(
        scene_id="scene",
        lines=[_talk(), {"characters": []}, _talk()],
        line_data_map=_data(1.0, 1.0, 1.0),
        norm_char_entries=_norm,
        video_extensions={".mp4"},
    )

    assert plans == []
