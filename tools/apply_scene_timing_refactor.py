from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SCENE_TIMING = '''"""Scene timing mutation and derived render context.

This module is an internal SceneRenderer mixin; use scene_renderer.SceneRenderer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple


SceneLine = Tuple[int, Dict[str, Any]]


@dataclass(frozen=True)
class SceneTimingPlan:
    """Derived timing and cache context for one scene render."""

    lines: List[SceneLine]
    scene_duration: float
    start_time_by_idx: Dict[int, float]
    badge_line_markers: Dict[str, float]
    subtitle_entries: List[Dict[str, Any]]
    subtitle_timing_key: str
    component_keys: Dict[str, Any]


def _max_enabled_character_duration(
    characters: List[Dict[str, Any]],
    duration_key: str,
) -> float:
    """Return the maximum enabled enter/leave duration."""
    duration = 0.0
    enabled_key = duration_key.replace("_duration", "")
    for character in characters:
        if not character.get(enabled_key):
            continue
        try:
            candidate = float(character.get(duration_key, 0.0))
        except Exception:
            candidate = 0.0
        duration = max(duration, candidate)
    return duration


def _resolve_j_cut_padding(line: Dict[str, Any]) -> float:
    """Resolve non-negative J-cut padding while preserving legacy fallback."""
    j_cut_config = line.get("j_cut")
    try:
        value = float(
            (j_cut_config or {}).get(
                "duration",
                line.get("audio_delay", 0.0),
            )
            if isinstance(j_cut_config, dict)
            else line.get("audio_delay", 0.0)
        )
    except Exception:
        value = 0.0
    return max(0.0, value)


def _apply_line_duration_padding(
    *,
    scene_id: str,
    lines: List[SceneLine],
    line_data_map: Dict[str, Dict[str, Any]],
) -> None:
    """Mutate line timing with enter, J-cut, and leave padding."""
    for line_index, line in lines:
        line_data = line_data_map.get(f"{scene_id}_{line_index}")
        if not line_data:
            continue
        characters = line.get("characters", []) or []
        enter_padding = _max_enabled_character_duration(
            characters,
            "enter_duration",
        )
        leave_padding = _max_enabled_character_duration(
            characters,
            "leave_duration",
        )
        j_cut_padding = _resolve_j_cut_padding(line)
        line_data["pre_duration"] = enter_padding + j_cut_padding
        line_data["post_duration"] = leave_padding
        line_data["duration"] = (
            float(line_data.get("duration", 0.0))
            + enter_padding
            + j_cut_padding
            + leave_padding
        )


def _build_start_times(
    *,
    scene_id: str,
    lines: List[SceneLine],
    line_data_map: Dict[str, Dict[str, Any]],
) -> tuple[float, Dict[int, float]]:
    """Return scene duration and cumulative line start times."""
    scene_duration = sum(
        line_data_map[f"{scene_id}_{line_index}"]["duration"]
        for line_index, _line in lines
    )
    start_time_by_idx: Dict[int, float] = {}
    elapsed = 0.0
    for line_index, _line in lines:
        start_time_by_idx[line_index] = elapsed
        elapsed += line_data_map[f"{scene_id}_{line_index}"]["duration"]
    return scene_duration, start_time_by_idx


class SceneTimingMixin:
    """Build timing and cache-derived context before scene rendering."""

    def _build_scene_timing_plan(
        self,
        *,
        scene: Dict[str, Any],
        scene_hash_data: Dict[str, Any],
        scene_base_hash_data: Dict[str, Any],
    ) -> SceneTimingPlan:
        scene_id = scene["id"]
        lines = list(enumerate(scene.get("lines", []), start=1))
        _apply_line_duration_padding(
            scene_id=scene_id,
            lines=lines,
            line_data_map=self.line_data_map,
        )
        scene_duration, start_time_by_idx = _build_start_times(
            scene_id=scene_id,
            lines=lines,
            line_data_map=self.line_data_map,
        )
        badge_line_markers = self._build_badge_line_markers(
            start_time_by_idx=start_time_by_idx,
        )
        subtitle_entries = self._build_subtitle_entries(
            scene_id,
            start_time_by_idx,
        )
        component_keys = self._scene_cache_component_keys(
            scene_hash_data,
            scene_base_hash_data,
        )
        subtitle_timing_key = self._subtitle_timing_key(subtitle_entries)
        component_keys["subtitle_timing_key"] = subtitle_timing_key
        return SceneTimingPlan(
            lines=lines,
            scene_duration=scene_duration,
            start_time_by_idx=start_time_by_idx,
            badge_line_markers=badge_line_markers,
            subtitle_entries=subtitle_entries,
            subtitle_timing_key=subtitle_timing_key,
            component_keys=component_keys,
        )
'''

TIMING_TEST = '''import hashlib
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
'''

OLD_TIMING_BLOCK = '''        # キャラクターの登場/退場アニメーション秒数を行ごとに反映
        for idx, line in enumerate(scene.get("lines", []), start=1):
            line_id = f"{scene_id}_{idx}"
            data = line_data_map.get(line_id)
            if not data:
                continue
            chars = line.get("characters", []) or []

            def _max_dur(key: str) -> float:
                """Return max duration for enter/leave across characters."""
                dur = 0.0
                flag = key.replace("_duration", "")
                for ch in chars:
                    if ch.get(flag):
                        try:
                            d = float(ch.get(key, 0.0))
                        except Exception:
                            d = 0.0
                        dur = max(dur, d)
                return dur

            enter_pad = _max_dur("enter_duration")
            leave_pad = _max_dur("leave_duration")
            j_cut_cfg = line.get("j_cut")
            try:
                j_cut_pad = float(
                    (j_cut_cfg or {}).get(
                        "duration",
                        line.get("audio_delay", 0.0),
                    )
                    if isinstance(j_cut_cfg, dict)
                    else line.get("audio_delay", 0.0)
                )
            except Exception:
                j_cut_pad = 0.0
            j_cut_pad = max(0.0, j_cut_pad)
            data["pre_duration"] = enter_pad + j_cut_pad
            data["post_duration"] = leave_pad
            data["duration"] = float(data.get("duration", 0.0)) + enter_pad + j_cut_pad + leave_pad

        scene_duration = sum(
            line_data_map[f"{scene_id}_{idx + 1}"]["duration"]
            for idx, line in enumerate(scene.get("lines", []))
        )

        lines = list(enumerate(scene.get("lines", []), start=1))
        start_time_by_idx: Dict[int, float] = {}
        t_acc = 0.0
        for idx, _line in lines:
            line_id2 = f"{scene_id}_{idx}"
            d = line_data_map[line_id2]["duration"]
            start_time_by_idx[idx] = t_acc
            t_acc += d
        badge_line_markers = self._build_badge_line_markers(
            start_time_by_idx=start_time_by_idx,
        )
        subtitle_entries = self._build_subtitle_entries(scene_id, start_time_by_idx)
        component_keys = self._scene_cache_component_keys(
            scene_hash_data,
            scene_base_hash_data,
        )
        subtitle_timing_key = self._subtitle_timing_key(subtitle_entries)
        component_keys["subtitle_timing_key"] = subtitle_timing_key
'''

NEW_TIMING_BLOCK = '''        timing_plan = self._build_scene_timing_plan(
            scene=scene,
            scene_hash_data=scene_hash_data,
            scene_base_hash_data=scene_base_hash_data,
        )
        lines = timing_plan.lines
        scene_duration = timing_plan.scene_duration
        start_time_by_idx = timing_plan.start_time_by_idx
        badge_line_markers = timing_plan.badge_line_markers
        subtitle_entries = timing_plan.subtitle_entries
        component_keys = timing_plan.component_keys
        subtitle_timing_key = timing_plan.subtitle_timing_key
'''


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise RuntimeError(f"Expected one replacement in {path}: found {text.count(old)}")
    path.write_text(text.replace(old, new), encoding="utf-8")


def main() -> None:
    video_phase = ROOT / "zundamotion/components/pipeline_phases/video_phase"
    (video_phase / "scene_timing.py").write_text(SCENE_TIMING, encoding="utf-8")
    (ROOT / "tests/test_scene_renderer_timing.py").write_text(
        TIMING_TEST,
        encoding="utf-8",
    )

    replace_once(
        video_phase / "scene_renderer.py",
        "from .scene_standard_renderer import SceneStandardRendererMixin\n",
        "from .scene_standard_renderer import SceneStandardRendererMixin\n"
        "from .scene_timing import SceneTimingMixin\n",
    )
    replace_once(
        video_phase / "scene_renderer.py",
        "    SceneCacheMixin,\n    SceneStandardRendererMixin,\n",
        "    SceneCacheMixin,\n    SceneTimingMixin,\n"
        "    SceneStandardRendererMixin,\n",
    )
    replace_once(
        video_phase / "scene_standard_renderer.py",
        OLD_TIMING_BLOCK,
        NEW_TIMING_BLOCK,
    )
    replace_once(
        ROOT / "tests/test_scene_renderer_module_split.py",
        '        "_scene_base_cache_data": "scene_cache",\n',
        '        "_scene_base_cache_data": "scene_cache",\n'
        '        "_build_scene_timing_plan": "scene_timing",\n',
    )

    plan_path = ROOT / "docs/guides/source_refactoring_plan.md"
    if plan_path.exists():
        marker = "#### 6A-1: タイミングと scene context の分離\n"
        progress = (
            marker
            + "\n進捗:\n\n"
            + "- 2026-08-06: enter / leave / J カット、scene duration、開始時刻、"
            + "badge marker、subtitle timing、cache component context を `scene_timing.py` へ分離\n"
            + "- timing の characterization test を追加。6A-0 の base / line / assembly 保護は後続 PR で継続\n"
        )
        replace_once(plan_path, marker, progress)


if __name__ == "__main__":
    main()
