from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from zundamotion.components.pipeline_phases.video_phase.scene_line_context import (
    SceneLineContext,
)
from zundamotion.components.pipeline_phases.video_phase.scene_wait_renderer import (
    SceneWaitRendererMixin,
)
from zundamotion.exceptions import PipelineError


class _CacheManager:
    def __init__(self, tmp_path: Path, *, cached: bool = False) -> None:
        self.tmp_path = tmp_path
        self.cached = cached
        self.calls = []

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
        self.wait_calls = []
        self.foreground_calls = []

    async def render_wait_clip(
        self,
        duration,
        background_config,
        output_name,
        line_config,
        *,
        characters_config,
        image_layer_overlays,
        extra_audio_overlays,
    ):
        self.wait_calls.append(
            {
                "duration": duration,
                "background_config": background_config,
                "output_name": output_name,
                "line_config": line_config,
                "characters_config": characters_config,
                "image_layer_overlays": image_layer_overlays,
                "extra_audio_overlays": extra_audio_overlays,
            }
        )
        if self.fail:
            return None
        output = self.tmp_path / f"{output_name}.mp4"
        output.write_bytes(b"rendered")
        return output

    async def apply_foreground_overlays(self, clip_path, overlays):
        self.foreground_calls.append((Path(clip_path), overlays))
        output = self.tmp_path / "foreground.mp4"
        output.write_bytes(b"foreground")
        return output


class _Subject(SceneWaitRendererMixin):
    def __init__(
        self,
        tmp_path: Path,
        *,
        cached: bool = False,
        fail: bool = False,
        foreground=None,
    ) -> None:
        self.config = {"video": {"fps": 30}}
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
        "characters": [{"name": "A", "visible": True}],
        "screen_effects": ["flash"],
        "background_effects": ["zoom"],
    }
    return SceneLineContext(
        line_index=3,
        line_id="demo_3",
        visual_container={"id": "line-3"},
        line_data={"type": "wait"},
        line_type="wait",
        duration=1.5,
        pre_duration=0.0,
        post_duration=0.0,
        scene_start_time=4.25,
        line_config=line_config,
        text="",
        audio_path=None,
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


def test_wait_cache_payload_preserves_legacy_fields(tmp_path: Path) -> None:
    subject = _Subject(tmp_path)

    payload = subject._build_wait_cache_data(_context())

    assert payload == {
        "type": "wait",
        "duration": 1.5,
        "bg_image_path": "background.mp4",
        "is_bg_video": True,
        "start_time": 4.25,
        "video_config": {"fps": 30},
        "line_config": _context().line_config,
        "image_layer_overlays": [{"id": "layer"}],
        "extra_audio_overlays": [{"src": "sfx.wav"}],
        "hw_kind": "cpu",
        "video_params": {"width": 1920, "height": 1080, "fps": 30},
        "audio_params": {"sample_rate": 48000, "channels": 2},
        "screen_effects": ["flash"],
        "background_effects": ["zoom"],
        "background_layout": _context().background_layout,
        "video_filter": "grayscale",
    }


def test_wait_render_uses_cache_creator_and_resolved_context(tmp_path: Path) -> None:
    subject = _Subject(tmp_path)
    context = _context()

    result = asyncio.run(subject._render_wait_line(context))

    assert result.name == "demo_3.mp4"
    assert len(subject.cache_manager.calls) == 1
    assert subject.cache_manager.calls[0][1:] == ("demo_3", "mp4")
    assert subject.video_renderer.wait_calls == [
        {
            "duration": 1.5,
            "background_config": context.background_config,
            "output_name": "demo_3",
            "line_config": context.line_config,
            "characters_config": context.line_config["characters"],
            "image_layer_overlays": [{"id": "layer"}],
            "extra_audio_overlays": [{"src": "sfx.wav"}],
        }
    ]
    assert subject.resolve_calls == [({"id": "line-3"}, "demo_3")]


def test_cache_hit_skips_wait_render_but_still_applies_foreground(tmp_path: Path) -> None:
    overlays = [{"src": "badge.png"}]
    subject = _Subject(tmp_path, cached=True, foreground=overlays)

    result = asyncio.run(subject._render_wait_line(_context()))

    assert result.name == "foreground.mp4"
    assert subject.video_renderer.wait_calls == []
    assert len(subject.video_renderer.foreground_calls) == 1
    cached_path, applied = subject.video_renderer.foreground_calls[0]
    assert cached_path.name == "demo_3.mp4"
    assert applied == overlays


def test_failed_wait_render_raises_pipeline_error(tmp_path: Path) -> None:
    subject = _Subject(tmp_path, fail=True)

    with pytest.raises(PipelineError, match="demo_3"):
        asyncio.run(subject._render_wait_line(_context()))
