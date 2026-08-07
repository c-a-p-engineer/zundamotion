from __future__ import annotations

import asyncio
from pathlib import Path

from zundamotion.components.pipeline_phases.video_phase.scene_assembly import (
    SceneAssemblyMixin,
)


class _VideoRenderer:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.concat_calls = []
        self.foreground_calls = []
        self.subtitle_calls = []

    async def concat_clips(self, clips, output_path):
        self.concat_calls.append((list(clips), output_path))
        Path(output_path).write_bytes(b"concat")

    async def apply_foreground_overlays(self, input_path, overlays):
        self.foreground_calls.append((Path(input_path), overlays))
        output = self.tmp_path / "foreground.mp4"
        output.write_bytes(b"foreground")
        return output

    async def apply_subtitle_overlays(self, input_path, subtitles, *, scene_id):
        self.subtitle_calls.append((Path(input_path), subtitles, scene_id))
        output = self.tmp_path / "subtitle.mp4"
        output.write_bytes(b"subtitle")
        return output


class _Subject(SceneAssemblyMixin):
    def __init__(self, tmp_path: Path, *, foreground=None) -> None:
        self.temp_dir = tmp_path
        self.video_renderer = _VideoRenderer(tmp_path)
        self.foreground = foreground or []
        self.resolve_calls = []

    async def _resolve_visual_overlays(
        self,
        container,
        *,
        scope_id,
        line_markers=None,
    ):
        self.resolve_calls.append((container, scope_id, line_markers))
        return self.foreground


def _clip(tmp_path: Path, name: str) -> Path:
    path = tmp_path / name
    path.write_bytes(name.encode())
    return path


def test_empty_line_results_skip_all_media_operations(tmp_path: Path) -> None:
    subject = _Subject(tmp_path)

    result = asyncio.run(
        subject._assemble_scene_media(
            scene_id="empty",
            line_results=[None, None],
            scene={"id": "empty"},
            badge_line_markers={},
            subtitle_entries=[],
        )
    )

    assert result is None
    assert subject.video_renderer.concat_calls == []
    assert subject.resolve_calls == []


def test_line_clips_are_filtered_without_changing_order(tmp_path: Path) -> None:
    subject = _Subject(tmp_path)
    first = _clip(tmp_path, "first.mp4")
    second = _clip(tmp_path, "second.mp4")

    result = asyncio.run(
        subject._assemble_scene_media(
            scene_id="demo",
            line_results=[None, first, None, second],
            scene={"id": "demo"},
            badge_line_markers={"1": 0.0},
            subtitle_entries=[],
        )
    )

    assert result is not None
    assert result.line_clips == (first, second)
    assert result.no_sub_path == tmp_path / "scene_output_demo.mp4"
    assert result.final_path == result.no_sub_path
    assert result.has_subtitles is False
    assert subject.video_renderer.concat_calls == [
        ([first, second], str(tmp_path / "scene_output_demo.mp4"))
    ]
    assert subject.resolve_calls == [
        ({"id": "demo"}, "demo", {"1": 0.0})
    ]


def test_foreground_is_applied_before_subtitles(tmp_path: Path) -> None:
    overlays = [{"src": "badge.png"}]
    subtitles = [{"text": "hello", "start": 0.0, "duration": 1.0}]
    subject = _Subject(tmp_path, foreground=overlays)
    clip = _clip(tmp_path, "line.mp4")

    result = asyncio.run(
        subject._assemble_scene_media(
            scene_id="demo",
            line_results=[clip],
            scene={"id": "demo", "fg_overlays": overlays},
            badge_line_markers={"line": 0.0},
            subtitle_entries=subtitles,
        )
    )

    assert result is not None
    assert result.no_sub_path == tmp_path / "foreground.mp4"
    assert result.final_path == tmp_path / "subtitle.mp4"
    assert result.has_subtitles is True
    assert subject.video_renderer.foreground_calls == [
        (tmp_path / "scene_output_demo.mp4", overlays)
    ]
    assert subject.video_renderer.subtitle_calls == [
        (tmp_path / "foreground.mp4", subtitles, "demo")
    ]


def test_subtitles_without_foreground_use_concatenated_input(tmp_path: Path) -> None:
    subtitles = [{"text": "hello", "start": 0.0, "duration": 1.0}]
    subject = _Subject(tmp_path)
    clip = _clip(tmp_path, "line.mp4")

    result = asyncio.run(
        subject._assemble_scene_media(
            scene_id="plain",
            line_results=[clip],
            scene={"id": "plain"},
            badge_line_markers={},
            subtitle_entries=subtitles,
        )
    )

    assert result is not None
    assert result.no_sub_path == tmp_path / "scene_output_plain.mp4"
    assert subject.video_renderer.foreground_calls == []
    assert subject.video_renderer.subtitle_calls[0][0] == result.no_sub_path
