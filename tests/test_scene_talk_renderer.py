from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from zundamotion.components.pipeline_phases.video_phase.scene_line_context import (
    SceneLineContext,
)
from zundamotion.components.pipeline_phases.video_phase.scene_talk_plan import (
    SceneTalkPlan,
)
from zundamotion.components.pipeline_phases.video_phase.scene_talk_renderer import (
    SceneTalkRendererMixin,
)
from zundamotion.exceptions import PipelineError


class _CacheManager:
    def __init__(self, tmp_path: Path, *, cached: bool = False) -> None:
        self.tmp_path = tmp_path
        self.cached = cached
        self.calls = []

    @staticmethod
    def _generate_hash(value):
        assert value["text"] == "hello"
        return "audio-hash"

    async def get_or_create(
        self,
        *,
        key_data,
        file_name,
        extension,
        creator_func,
    ):
        self.calls.append((key_data, file_name, extension))
        output = self.tmp_path / f"{file_name}.{extension}"
        if self.cached:
            output.write_bytes(b"cached")
            return output
        return await creator_func(output)


class _VideoRenderer:
    def __init__(self, tmp_path: Path, *, fail: bool = False) -> None:
        self.tmp_path = tmp_path
        self.fail = fail
        self.render_calls = []
        self.foreground_calls = []

    async def render_clip(self, **kwargs):
        self.render_calls.append(kwargs)
        if self.fail:
            return None
        output = self.tmp_path / f"{kwargs['output_filename']}.mp4"
        output.write_bytes(b"rendered")
        return output

    async def apply_foreground_overlays(self, clip_path, overlays):
        self.foreground_calls.append((Path(clip_path), overlays))
        output = self.tmp_path / "foreground.mp4"
        output.write_bytes(b"foreground")
        return output


class _Subject(SceneTalkRendererMixin):
    def __init__(
        self,
        tmp_path: Path,
        *,
        cached: bool = False,
        fail: bool = False,
        foreground=None,
    ) -> None:
        self.config = {
            "voice": {"speed": 1.0},
            "video": {"fps": 30},
            "bgm": {"volume": 0.2},
        }
        self.hw_kind = "cpu"
        self.video_params = SimpleNamespace(width=1920, height=1080, fps=30)
        self.audio_params = SimpleNamespace(sample_rate=48000, channels=2)
        self.cache_manager = _CacheManager(tmp_path, cached=cached)
        self.video_renderer = _VideoRenderer(tmp_path, fail=fail)
        self.foreground = foreground or []
        self.resolve_calls = []

    async def _resolve_visual_overlays(self, container, *, scope_id):
        self.resolve_calls.append((container, scope_id))
        return self.foreground


def _context() -> SceneLineContext:
    line_config = {
        "screen_effects": ["flash"],
        "background_effects": ["zoom"],
        "subtitle": {"font_size": 64},
    }
    return SceneLineContext(
        line_index=3,
        line_id="demo_3",
        visual_container={"id": "line-3"},
        line_data={"type": "talk", "text": "hello"},
        line_type="talk",
        duration=1.5,
        pre_duration=0.2,
        post_duration=0.3,
        scene_start_time=4.25,
        line_config=line_config,
        text="hello",
        audio_path=Path("voice.wav"),
        extra_audio_overlays=({"src": "sfx.wav"},),
        image_layer_overlays=({"id": "layer"},),
        background_layout={
            "fit": "contain",
            "fill_color": "black",
            "anchor": "middle_center",
            "position": {"x": "0", "y": "0"},
        },
        background_source="background.mp4",
        background_is_video=True,
        uses_scene_background=True,
        run_base=None,
        background_config={
            "type": "video",
            "path": "base.mp4",
            "start_time": 0.75,
            "video_filter": "grayscale",
        },
    )


def _plan() -> SceneTalkPlan:
    return SceneTalkPlan(
        effective_characters=({"name": "A", "visible": True},),
        effective_insert={"path": "insert.mp4", "normalized": True},
        face_animations=(
            {
                "mouth": [{"state": "open"}],
                "meta": {
                    "mouth_fps": 12,
                    "thr_half": 0.4,
                    "thr_open": 0.7,
                    "blink_min_interval": 2,
                    "blink_max_interval": 5,
                    "blink_close_frames": 2,
                },
            },
        ),
        animation_meta={
            "mouth_fps": 12,
            "thr_half": 0.4,
            "thr_open": 0.7,
            "blink_min_interval": 2,
            "blink_max_interval": 5,
            "blink_close_frames": 2,
        },
        has_subtitle=True,
        has_visible_characters=True,
        insert_is_image=False,
        has_move=False,
        has_effect=True,
    )


def test_talk_cache_payload_preserves_legacy_fields(tmp_path: Path) -> None:
    subject = _Subject(tmp_path)
    context = _context()
    plan = _plan()

    payload = subject._build_talk_cache_data(
        context=context,
        plan=plan,
        static_character_keys={"A"},
        static_insert_in_base=False,
    )

    assert payload == {
        "type": "talk",
        "clip_render_version": "20260330_face_overlay_args_v2",
        "audio_cache_key": "audio-hash",
        "duration": 1.5,
        "audio_delay": 0.2,
        "post_duration": 0.3,
        "bg_image_path": "background.mp4",
        "is_bg_video": True,
        "start_time": 4.25,
        "video_config": {"fps": 30},
        "bgm_config": {"volume": 0.2},
        "insert_config": plan.effective_insert,
        "image_layer_overlays": [{"id": "layer"}],
        "extra_audio_overlays": [{"src": "sfx.wav"}],
        "static_chars_in_base": True,
        "static_insert_in_base": False,
        "hw_kind": "cpu",
        "video_params": {"width": 1920, "height": 1080, "fps": 30},
        "audio_params": {"sample_rate": 48000, "channels": 2},
        "lip_eye_version": "v2",
        "face_anim_enabled": True,
        "mouth_fps": 12,
        "thr_half": 0.4,
        "thr_open": 0.7,
        "blink_min_interval": 2,
        "blink_max_interval": 5,
        "blink_close_frames": 2,
        "screen_effects": ["flash"],
        "background_effects": ["zoom"],
        "background_layout": context.background_layout,
        "video_filter": "grayscale",
    }


def test_talk_render_uses_cache_creator_and_resolved_plan(tmp_path: Path) -> None:
    subject = _Subject(tmp_path)
    context = _context()
    plan = _plan()

    outcome = asyncio.run(
        subject._render_talk_line(
            context=context,
            plan=plan,
            static_character_keys={"A"},
            static_insert_in_base=False,
        )
    )

    assert outcome.path.name == "demo_3.mp4"
    assert outcome.cache_status == "miss"
    assert outcome.render_ms >= 0.0
    assert outcome.cache_lookup_ms >= 0.0
    assert outcome.cache_store_ms >= 0.0
    assert len(subject.video_renderer.render_calls) == 1
    call = subject.video_renderer.render_calls[0]
    assert call == {
        "audio_path": Path("voice.wav"),
        "duration": 1.5,
        "background_config": context.background_config,
        "characters_config": list(plan.effective_characters),
        "output_filename": "demo_3",
        "subtitle_text": None,
        "subtitle_line_config": context.line_config,
        "insert_config": plan.effective_insert,
        "image_layer_overlays": [{"id": "layer"}],
        "extra_audio_overlays": [{"src": "sfx.wav"}],
        "background_effects": ["zoom"],
        "screen_effects": ["flash"],
        "face_anim": list(plan.face_animations),
        "audio_delay": 0.2,
        "_force_cpu": True,
    }
    assert subject.resolve_calls == [({"id": "line-3"}, "demo_3")]


def test_cache_hit_skips_render_and_applies_foreground(tmp_path: Path) -> None:
    overlays = [{"src": "badge.png"}]
    subject = _Subject(tmp_path, cached=True, foreground=overlays)

    outcome = asyncio.run(
        subject._render_talk_line(
            context=_context(),
            plan=_plan(),
            static_character_keys=set(),
            static_insert_in_base=False,
        )
    )

    assert outcome.path.name == "foreground.mp4"
    assert outcome.cache_status == "hit"
    assert outcome.render_ms == 0.0
    assert outcome.cache_store_ms == 0.0
    assert subject.video_renderer.render_calls == []
    assert len(subject.video_renderer.foreground_calls) == 1


def test_failed_talk_render_raises_pipeline_error(tmp_path: Path) -> None:
    subject = _Subject(tmp_path, fail=True)

    with pytest.raises(PipelineError, match="demo_3"):
        asyncio.run(
            subject._render_talk_line(
                context=_context(),
                plan=_plan(),
                static_character_keys=set(),
                static_insert_in_base=False,
            )
        )
