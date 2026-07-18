from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from PIL import Image

from zundamotion.cache import CacheManager
from zundamotion.components.pipeline_phases.video_phase.character_render_state import (
    resolve_character_render_state,
    static_character_entry,
)
from zundamotion.components.pipeline_phases.video_phase.main import VideoPhase
from zundamotion.components.pipeline_phases.video_phase.scene_renderer import SceneRenderer
from zundamotion.utils.ffmpeg_params import AudioParams, VideoParams


def _phase(config: dict) -> VideoPhase:
    phase = object.__new__(VideoPhase)
    phase.config = config
    phase.hw_kind = None
    phase.video_params = VideoParams(width=320, height=180, fps=30)
    phase.audio_params = AudioParams()
    return phase


def _scene(character: dict | None = None) -> dict:
    line = {"text": "same"}
    if character is not None:
        line["characters"] = [character]
    return {"id": "demo", "lines": [line]}


def _write_character(root: Path, name: str, color: str = "red") -> Path:
    path = root / "assets" / "characters" / name / "default" / "base.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (4, 4), color).save(path)
    return path


def test_scene_fingerprint_same_input_is_stable_and_defaults_miss(tmp_path: Path) -> None:
    base_config = {
        "defaults": {
            "characters_persist": False,
            "background_persist": False,
            "characters": {"hero": {"scale": 0.8}},
        },
        "characters": {"default_scale": 1.0, "default_anchor": "bottom_center"},
    }
    scene = _scene({"name": "hero", "visible": True})
    first = _phase(deepcopy(base_config))._generate_scene_hash(deepcopy(scene))
    second = _phase(deepcopy(base_config))._generate_scene_hash(deepcopy(scene))
    assert first == second

    variants = []
    config = deepcopy(base_config)
    config["characters"]["default_scale"] = 0.9
    variants.append(config)
    config = deepcopy(base_config)
    config["characters"]["default_anchor"] = "bottom_left"
    variants.append(config)
    config = deepcopy(base_config)
    config["defaults"]["characters"]["hero"]["scale"] = 0.7
    variants.append(config)
    config = deepcopy(base_config)
    config["defaults"]["characters_persist"] = True
    variants.append(config)
    config = deepcopy(base_config)
    config["defaults"]["background_persist"] = True
    variants.append(config)

    assert all(_phase(item)._generate_scene_hash(deepcopy(scene)) != first for item in variants)


def test_same_scene_input_hits_and_subtitle_only_change_preserves_base(
    tmp_path: Path,
) -> None:
    cache = CacheManager(tmp_path / "cache")
    renderer = object.__new__(SceneRenderer)
    renderer.cache_manager = cache
    first = {
        "scene": "demo",
        "lines": [
            {
                "text": "spoken text",
                "subtitle_text": "first display",
                "subtitle": {"size": 48},
            }
        ],
        "subtitle_config": {"font_size": 48},
    }
    changed = deepcopy(first)
    changed["lines"][0]["subtitle_text"] = "changed display"
    changed["lines"][0]["subtitle"]["size"] = 52
    changed["subtitle_config"]["font_size"] = 52
    first_base = renderer._scene_base_cache_data(first)
    changed_base = renderer._scene_base_cache_data(changed)
    first_sub = renderer._scene_subtitle_cache_data(first, first_base)
    changed_sub = renderer._scene_subtitle_cache_data(changed, changed_base)

    assert cache._generate_hash(first_base) == cache._generate_hash(changed_base)
    assert cache._generate_hash(first_sub) != cache._generate_hash(changed_sub)

    cached = cache.get_cache_path(
        key_data=first_sub,
        file_name="scene_demo_sub",
        extension="mp4",
    )
    cached.write_bytes(b"cached")
    assert cache.get_cached_path(
        key_data=deepcopy(first_sub),
        file_name="scene_demo_sub",
        extension="mp4",
    ) == cached


def test_character_fingerprint_covers_visual_state_and_source_content(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    source = _write_character(tmp_path, "hero", "red")
    _write_character(tmp_path, "alternate", "blue")
    config = {"characters": {"default_scale": 1.0, "default_anchor": "bottom_center"}}
    base = {"name": "hero", "visible": True}
    cache = CacheManager(tmp_path / "cache")

    def digest(character: dict) -> str:
        payload = _phase(config)._generate_scene_hash(_scene(character))
        return cache._generate_hash(payload)

    original = digest(base)
    assert digest(base) == original
    assert digest({**base, "asset_name": "alternate"}) != original
    assert digest({**base, "flip_x": True}) != original
    assert digest({**base, "flip_y": True}) != original
    assert digest({**base, "color_filter": {"hue": 10}}) != original
    assert digest({**base, "z": 2}) != original

    Image.new("RGBA", (5, 4), "green").save(source)
    assert digest(base) != original


def test_dynamic_characters_are_not_static_scene_overlays(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_character(tmp_path, "hero")
    base = {"name": "hero", "visible": True}
    assert static_character_entry(base, {}) is not None

    dynamic_variants = [
        {**base, "move": {"to": {"x": 10}}},
        {**base, "move": {"to": {"scale": 1.2}}},
        {**base, "enter": "fade"},
        {**base, "leave": "slide_left"},
        {**base, "effects": [{"type": "shake"}]},
        {**base, "position": {"x": "10*t", "y": 0}},
    ]
    assert all(static_character_entry(item, {}) is None for item in dynamic_variants)


def test_color_filter_is_normalized_in_resolved_state() -> None:
    first = resolve_character_render_state(
        {"name": "hero", "color_filter": {"hue": 1, "saturation": 1, "brightness": 1}}
    )
    second = resolve_character_render_state(
        {
            "name": "hero",
            "color_filter": {"hue": 1.0, "saturation": 1.0, "brightness": 1.0},
        }
    )
    assert first["color_filter"] == second["color_filter"]
