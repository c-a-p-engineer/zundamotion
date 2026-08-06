import hashlib
import json
from pathlib import Path

import pytest

from zundamotion.components.pipeline_phases.video_phase.scene_renderer import (
    SceneRenderer,
)


class _NoCacheManager:
    no_cache = True

    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir

    @staticmethod
    def _generate_hash(data) -> str:
        payload = json.dumps(data, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _renderer(
    *,
    tmp_path: Path,
    scene: dict,
    line_data_map: dict,
) -> SceneRenderer:
    renderer = object.__new__(SceneRenderer)
    renderer.scene = scene
    renderer.line_data_map = line_data_map
    renderer.cache_manager = _NoCacheManager(tmp_path / "cache")
    return renderer


def test_scene_timing_plan_preserves_enter_j_cut_leave_and_subtitle_timing(
    tmp_path: Path,
) -> None:
    scene = {
        "id": "demo",
        "lines": [
            {
                "id": "opening",
                "text": "first",
                "j_cut": {"duration": 0.4},
                "characters": [
                    {
                        "enter": "fade",
                        "enter_duration": 0.3,
                        "leave": "fade",
                        "leave_duration": 0.2,
                    },
                    {
                        "enter": "slide_left",
                        "enter_duration": 0.5,
                    },
                ],
            },
            {
                "id": "middle",
                "text": "second",
                "audio_delay": 0.25,
                "characters": [
                    {
                        "leave": "fade",
                        "leave_duration": 0.1,
                    }
                ],
            },
            {
                "id": "visual",
                "type": "image_layer",
            },
        ],
    }
    line_data_map = {
        "demo_1": {
            "type": "talk",
            "text": "first",
            "duration": 1.0,
            "line_config": {"subtitle": {"size": 48}},
        },
        "demo_2": {
            "type": "talk",
            "text": "second",
            "duration": 2.0,
            "line_config": {},
        },
        "demo_3": {
            "type": "image_layer",
            "text": "",
            "duration": 0.5,
            "line_config": {},
        },
    }
    renderer = _renderer(
        tmp_path=tmp_path,
        scene=scene,
        line_data_map=line_data_map,
    )

    plan = renderer._build_scene_timing_plan(
        scene=scene,
        scene_hash_data={"scene": "demo", "subtitle_config": {}},
        scene_base_hash_data={"scene": "demo", "scene_cache_layer": "base"},
    )

    assert line_data_map["demo_1"]["pre_duration"] == pytest.approx(0.9)
    assert line_data_map["demo_1"]["post_duration"] == pytest.approx(0.2)
    assert line_data_map["demo_1"]["duration"] == pytest.approx(2.1)
    assert line_data_map["demo_2"]["pre_duration"] == pytest.approx(0.25)
    assert line_data_map["demo_2"]["post_duration"] == pytest.approx(0.1)
    assert line_data_map["demo_2"]["duration"] == pytest.approx(2.35)
    assert line_data_map["demo_3"]["duration"] == pytest.approx(0.5)

    assert plan.scene_duration == pytest.approx(4.95)
    assert plan.start_time_by_idx == pytest.approx({1: 0.0, 2: 2.1, 3: 4.45})
    assert plan.badge_line_markers == pytest.approx(
        {
            "1": 0.0,
            "opening": 0.0,
            "2": 2.1,
            "middle": 2.1,
            "3": 4.45,
            "visual": 4.45,
        }
    )
    assert [item["text"] for item in plan.subtitle_entries] == ["first", "second"]
    assert plan.subtitle_entries[0]["start"] == pytest.approx(0.0)
    assert plan.subtitle_entries[0]["duration"] == pytest.approx(2.1)
    assert plan.subtitle_entries[1]["start"] == pytest.approx(2.1)
    assert plan.subtitle_entries[1]["duration"] == pytest.approx(2.35)
    assert plan.component_keys["subtitle_timing_key"] == plan.subtitle_timing_key


def test_scene_timing_plan_keeps_legacy_invalid_padding_fallbacks(
    tmp_path: Path,
) -> None:
    scene = {
        "id": "demo",
        "lines": [
            {
                "text": "invalid",
                "j_cut": {"duration": "invalid"},
                "characters": [
                    {
                        "enter": True,
                        "enter_duration": "invalid",
                        "leave": True,
                        "leave_duration": -0.5,
                    }
                ],
            },
            {
                "text": "negative",
                "j_cut": {"duration": -2.0},
                "characters": [],
            },
        ],
    }
    line_data_map = {
        "demo_1": {
            "type": "talk",
            "text": "invalid",
            "duration": 1.0,
            "line_config": {},
        },
        "demo_2": {
            "type": "talk",
            "text": "negative",
            "duration": 2.0,
            "line_config": {},
        },
    }
    renderer = _renderer(
        tmp_path=tmp_path,
        scene=scene,
        line_data_map=line_data_map,
    )

    plan = renderer._build_scene_timing_plan(
        scene=scene,
        scene_hash_data={"scene": "demo"},
        scene_base_hash_data={"scene": "demo", "scene_cache_layer": "base"},
    )

    assert line_data_map["demo_1"]["pre_duration"] == 0.0
    assert line_data_map["demo_1"]["post_duration"] == 0.0
    assert line_data_map["demo_1"]["duration"] == 1.0
    assert line_data_map["demo_2"]["pre_duration"] == 0.0
    assert line_data_map["demo_2"]["post_duration"] == 0.0
    assert line_data_map["demo_2"]["duration"] == 2.0
    assert plan.scene_duration == 3.0
    assert plan.start_time_by_idx == {1: 0.0, 2: 1.0}
