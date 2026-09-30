from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from zundamotion.cache import CacheManager
from zundamotion.components.pipeline_phases.video_phase.main import VideoPhase
from zundamotion.utils.ffmpeg_params import AudioParams, VideoParams


def _phase(config: dict) -> VideoPhase:
    phase = object.__new__(VideoPhase)
    phase.config = config
    phase.hw_kind = None
    phase.video_params = VideoParams(width=320, height=180, fps=30)
    phase.audio_params = AudioParams()
    return phase


def test_background_motion_keyframes_change_scene_cache_identity(
    tmp_path: Path,
) -> None:
    config = {
        "defaults": {
            "characters_persist": False,
            "background_persist": False,
            "characters": {},
        },
        "characters": {"default_scale": 1.0, "default_anchor": "bottom_center"},
    }
    effect = {
        "type": "bg:pan_zoom",
        "zoom": {"from": 1.0, "to": 1.4},
        "pan": {
            "from": {"x": 0.2, "y": 0.5},
            "to": {"x": 0.8, "y": 0.4},
        },
        "duration": 1.0,
        "easing": "linear",
        "keyframes": [
            {"at": 0.3, "zoom": 1.15, "easing": "ease_out"},
            {"at": 0.7, "pan": {"x": 0.6}},
        ],
    }
    cache = CacheManager(tmp_path / "cache")

    def digest(value: dict) -> str:
        scene = {
            "id": "demo",
            "lines": [{"text": "same", "background_effects": [value]}],
        }
        payload = _phase(config)._generate_scene_hash(scene)
        return cache._generate_hash(payload)

    original = digest(deepcopy(effect))
    assert digest(deepcopy(effect)) == original

    changed_at = deepcopy(effect)
    changed_at["keyframes"][0]["at"] = 0.35
    assert digest(changed_at) != original

    changed_value = deepcopy(effect)
    changed_value["keyframes"][1]["pan"]["x"] = 0.65
    assert digest(changed_value) != original

    changed_easing = deepcopy(effect)
    changed_easing["keyframes"][0]["easing"] = "ease_in"
    assert digest(changed_easing) != original
