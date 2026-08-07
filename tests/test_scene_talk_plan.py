from __future__ import annotations

from pathlib import Path

from zundamotion.components.pipeline_phases.video_phase.scene_line_context import (
    SceneLineContext,
)
from zundamotion.components.pipeline_phases.video_phase.scene_run_base_renderer import (
    RenderedRunBase,
)
from zundamotion.components.pipeline_phases.video_phase.scene_talk_plan import (
    SceneTalkPlanMixin,
)


class _Subject(SceneTalkPlanMixin):
    @staticmethod
    def _norm_char_entries(container):
        return {
            character["name"]: character
            for character in container.get("characters", [])
        }


def _context(
    *,
    characters=None,
    line_config=None,
    line_data=None,
    run_base=None,
) -> SceneLineContext:
    return SceneLineContext(
        line_index=3,
        line_id="demo_3",
        visual_container={"characters": characters or []},
        line_data=line_data or {"type": "talk", "text": "subtitle"},
        line_type="talk",
        duration=1.0,
        pre_duration=0.0,
        post_duration=0.0,
        scene_start_time=2.0,
        line_config=line_config or {},
        text="subtitle",
        audio_path=Path("voice.wav"),
        extra_audio_overlays=(),
        image_layer_overlays=(),
        background_layout={
            "fit": "contain",
            "fill_color": "black",
            "anchor": "middle_center",
            "position": {"x": "0", "y": "0"},
        },
        background_source="background.png",
        background_is_video=False,
        uses_scene_background=True,
        run_base=run_base,
        background_config={"type": "image", "path": "background.png"},
    )


def test_static_and_run_base_characters_are_removed_but_hidden_state_is_kept() -> None:
    run_base = RenderedRunBase(
        start_line=3,
        end_line=4,
        path=Path("run.mp4"),
        character_keys=frozenset({"B"}),
        has_insert_image=False,
        offsets={3: 0.0, 4: 1.0},
    )
    characters = [
        {"name": "A", "visible": True},
        {"name": "B", "visible": True},
        {"name": "C", "visible": True},
        {"name": "D", "visible": False},
    ]

    plan = _Subject()._build_scene_talk_plan(
        context=_context(characters=characters, run_base=run_base),
        static_character_keys={"A"},
        static_insert_in_base=False,
        scene_level_insert_video=None,
    )

    assert plan.effective_characters == (characters[2], characters[3])
    assert plan.has_visible_characters is True


def test_without_base_characters_original_order_is_preserved() -> None:
    characters = [
        {"name": "A", "visible": True},
        {"name": "B", "visible": False},
    ]

    plan = _Subject()._build_scene_talk_plan(
        context=_context(characters=characters),
        static_character_keys=set(),
        static_insert_in_base=False,
        scene_level_insert_video=None,
    )

    assert plan.effective_characters == tuple(characters)


def test_insert_in_scene_or_run_base_is_removed() -> None:
    line_config = {"insert": {"path": "insert.png"}}
    run_base = RenderedRunBase(
        start_line=3,
        end_line=4,
        path=Path("run.mp4"),
        character_keys=frozenset(),
        has_insert_image=True,
        offsets={3: 0.0, 4: 1.0},
    )
    subject = _Subject()

    static_plan = subject._build_scene_talk_plan(
        context=_context(line_config=line_config),
        static_character_keys=set(),
        static_insert_in_base=True,
        scene_level_insert_video=None,
    )
    run_plan = subject._build_scene_talk_plan(
        context=_context(line_config=line_config, run_base=run_base),
        static_character_keys=set(),
        static_insert_in_base=False,
        scene_level_insert_video=None,
    )

    assert static_plan.effective_insert is None
    assert run_plan.effective_insert is None


def test_common_insert_video_uses_normalized_path(tmp_path: Path) -> None:
    raw = tmp_path / "raw.mp4"
    raw.write_bytes(b"raw")
    normalized = tmp_path / "normalized.mp4"
    line_config = {
        "insert": {
            "path": str(raw),
            "scale": 0.5,
        }
    }

    plan = _Subject()._build_scene_talk_plan(
        context=_context(line_config=line_config),
        static_character_keys=set(),
        static_insert_in_base=False,
        scene_level_insert_video=normalized,
    )

    assert plan.effective_insert == {
        "path": str(normalized),
        "scale": 0.5,
        "normalized": True,
        "pre_scaled": True,
    }


def test_face_animation_and_classification_flags_match_line_inputs() -> None:
    animation = {
        "mouth": [{"state": "open"}],
        "meta": {"mouth_fps": 12, "thr_open": 0.7},
    }
    line_data = {
        "type": "talk",
        "text": "visible subtitle",
        "face_anim": [animation],
    }
    line_config = {
        "insert": {"path": "image.PNG"},
        "move": {"duration": 1.0},
        "screen_effects": ["flash"],
    }

    plan = _Subject()._build_scene_talk_plan(
        context=_context(
            characters=[{"name": "A", "visible": True}],
            line_config=line_config,
            line_data=line_data,
        ),
        static_character_keys=set(),
        static_insert_in_base=False,
        scene_level_insert_video=None,
    )

    assert plan.face_animations == (animation,)
    assert plan.animation_meta == {"mouth_fps": 12, "thr_open": 0.7}
    assert plan.has_subtitle is True
    assert plan.has_visible_characters is True
    assert plan.insert_is_image is True
    assert plan.has_move is True
    assert plan.has_effect is True


def test_single_face_animation_mapping_keeps_legacy_normalization() -> None:
    animation = {"meta": {"blink_close_frames": 2}}

    plan = _Subject()._build_scene_talk_plan(
        context=_context(
            line_data={"type": "talk", "text": "", "face_anim": animation}
        ),
        static_character_keys=set(),
        static_insert_in_base=False,
        scene_level_insert_video=None,
    )

    assert plan.face_animations == (animation,)
    assert plan.animation_meta == {"blink_close_frames": 2}
    assert plan.has_subtitle is False
